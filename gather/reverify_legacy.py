#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml", "brotli"]
# ///
"""Re-verify legacy events that are still unverifiable (pilot-2025 history the
2026-09-30 / 2026-10-01 passes could not check): deterministic fetching into a
cache, a mechanical audit of the (LLM-judged) results, and ledger records.

  reverify_legacy.py list <section>
        still-unverifiable legacy events (legacy, not superseded), one JSON per line
  reverify_legacy.py fetch <section> [--ids ID ..] [--retry-failed]
        fetch every source of those events into the cache: the live URL, then
        Wayback captures (CDX API, closest to the event's retrieved/published
        dates, raw id_ captures). Resumable: cached documents are kept.
  reverify_legacy.py fetch-url <section> <event-id> <url>
        fetch an alternative source (live + Wayback) for one event into its cache
  reverify_legacy.py show <section> <event-id>
        the event and its cached documents (manifest)
  reverify_legacy.py audit <section> <results.jsonl> [--partial]
        mechanical audit of judged results (quotes verbatim in a cached document,
        every figure and year of a new claim inside a quote, sources fetched)
  reverify_legacy.py stage <section> <results.jsonl> --tag T --by B [--today D]
        audit, then write ledger/reverify/<section>.<today>-<T>.jsonl (the log)
        and <cache>/<section>/staged-<T>.jsonl (records for `ledger.py merge`)

Network discipline: ONE request at a time across all processes (an flock on
<cache>/.net.lock around every request) and archive.org requests spaced by a
shared pacer (>= 5 s apart, state in <cache>/.pacer.json). 429/5xx, connection
errors and archive.org interstitials back off exponentially (Retry-After honoured,
capped at 10 min); after a 429 the spacing itself grows. Memory: the process
address space is capped (RLIMIT_AS 2 GB) and downloads are capped at 25 MB.

Cache: $GE_REVERIFY_CACHE, default ~/.cache/grand-endeavors/reverify;
<section>/<event-id>/manifest.json lists the fetched documents, NN.txt their text.

Results file (one JSON per event, written by the judge):
  {"id", "result": verified|corrected|refuted|unverifiable,
   "claim": new claim (corrected; verified keeps the legacy claim),
   "sources": [{"url", "title", "primary"}]   original or alternative source URLs
                                               (must have been fetched for this event),
   "evidence": [{"doc": NN, "quote": "verbatim text from that document"}],
   "date": optional corrected event date (verified/corrected; the new id takes it),
   "note": "..."}   (notes may cite "doc NN"; the log lists every fetched document by number)
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import fcntl
import html
import html.parser
import json
import os
import re
import resource
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "core"))
import kpi  # noqa: E402
import ledger  # noqa: E402

CACHE = os.environ.get("GE_REVERIFY_CACHE") or os.path.expanduser("~/.cache/grand-endeavors/reverify")
# archive.org answers a browser-like User-Agent from a script with 429 (bot check), so it
# gets an honest one; publishers' sites often refuse non-browser agents, so they get a browser's
UA_ARCHIVE = "grand-endeavors-reverify/1 (+https://github.com/pasky/grand-endeavors)"
UA_BROWSER = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/128.0 Safari/537.36")
MAX_BYTES = 25 * 1024 * 1024
ARCHIVE_GAP = 5.0          # seconds between archive.org requests (grows after a 429)
OTHER_GAP = 1.0
MAX_TRIES = 7              # 5+10+20+40+80+160 s of backoff before giving up on a request
MAX_WAIT = 600
CAPTURES_PER_URL = 2       # distinct captures fetched per source URL
CDX_PAUSE = 900            # after a CDX failure, use the availability API for 15 min
MIN_TEXT = 1500            # a capture with less text than this triggers one more capture


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# --- events ---------------------------------------------------------------------------
def pending(section: str) -> list[dict]:
    evs = ledger.events(section)
    sup = {s for e in evs for s in e.get("supersedes") or []}
    return [ledger.clean(e) for e in evs if e["verification"]["status"] == "legacy" and e["id"] not in sup]


# --- network --------------------------------------------------------------------------
class Net:
    """One request at a time (cross-process flock), archive.org paced and backed off."""

    def __init__(self, cache: str = CACHE):
        os.makedirs(cache, exist_ok=True)
        self.lock_p = os.path.join(cache, ".net.lock")
        self.pacer_p = os.path.join(cache, ".pacer.json")
        self.fail_streak = 0
        self.cdx_down_until = 0.0

    def _pacer(self) -> dict:
        try:
            with open(self.pacer_p) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"last": 0.0, "gap": ARCHIVE_GAP}

    def _save_pacer(self, p: dict):
        tmp = self.pacer_p + f".tmp{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(p, f)
        os.replace(tmp, self.pacer_p)

    @staticmethod
    def _interstitial(url: str, body: bytes) -> str | None:
        """archive.org error/rate-limit pages served instead of a capture."""
        if "archive.org" not in urllib.parse.urlsplit(url).netloc:
            return None
        head = body[:4000].lower()
        if b"too many requests" in head or b"rate limit" in head:
            return "retry"
        if b"scheduled maintenance" in head or b"temporarily unavailable" in head:
            return "retry"
        if b"<title>wayback machine</title>" in head and (b"hrm." in body[:20000].lower()
                                                          or b"has not archived" in body[:20000].lower()):
            return "fail"
        return None

    def get(self, url: str, tries: int = MAX_TRIES, breaker: bool = True) -> dict:
        """{status, final_url, ctype, body | error}. Never raises for HTTP/network errors.
        breaker: count a request that exhausts its retries towards the abort (3 in a row)."""
        archive = "archive.org" in urllib.parse.urlsplit(url).netloc
        last_err = ""
        for attempt in range(tries):
            with open(self.lock_p, "a") as lk:
                fcntl.flock(lk, fcntl.LOCK_EX)
                p = self._pacer()
                gap = p["gap"] if archive else OTHER_GAP
                last = p["last"] if archive else p.get("last_other", 0.0)
                wait = last + gap - time.time()
                if wait > 0:
                    time.sleep(wait)
                res, retry_after = self._once(url)
                p[("last" if archive else "last_other")] = time.time()
                transient = res.get("status") in (429, 500, 502, 503, 504, 520, 522, 524) or \
                    ("error" in res and not res.get("status")) or res.get("interstitial") == "retry"
                if archive and res.get("status") == 429:
                    p["gap"] = min(p["gap"] * 1.5, 30.0)
                elif archive and not transient and p["gap"] > ARCHIVE_GAP:
                    p["gap"] = max(ARCHIVE_GAP, p["gap"] * 0.95)
                self._save_pacer(p)
            if not transient:
                self.fail_streak = 0
                return res
            last_err = res.get("error") or f"HTTP {res.get('status')}"
            if (not archive and attempt >= 2) or attempt == tries - 1:
                break
            backoff = min(MAX_WAIT, max(retry_after or 0, (ARCHIVE_GAP if archive else 2) * 2 ** attempt))
            log(f"    transient ({last_err}) on {url[:120]}; backing off {backoff:.0f}s")
            time.sleep(backoff)
        if archive and breaker:
            self.fail_streak += 1
            if self.fail_streak >= 3:
                raise SystemExit("archive.org keeps failing (3 requests exhausted their retries); "
                                 "stopping. The run is resumable: re-run later with --retry-failed.")
        return {"status": None, "error": f"gave up after retries: {last_err}"}

    def _once(self, url: str) -> tuple[dict, float | None]:
        ua = UA_ARCHIVE if "archive.org" in urllib.parse.urlsplit(url).netloc else UA_BROWSER
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*",
                                                   "Accept-Language": "en"})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                body = _decode(r.read(MAX_BYTES + 1), r.headers.get("Content-Encoding", ""))
                res = {"status": r.status, "final_url": r.geturl(),
                       "ctype": r.headers.get("Content-Type", ""), "body": body[:MAX_BYTES]}
                if len(body) > MAX_BYTES:
                    res["truncated"] = True
                kind = self._interstitial(r.geturl(), body)
                if kind:
                    res["interstitial"] = kind
                    res["error"] = "archive.org interstitial"
                return res, None
        except urllib.error.HTTPError as e:
            ra = e.headers.get("Retry-After") if e.headers else None
            return {"status": e.code, "error": f"HTTP {e.code}"}, _retry_after(ra)
        except Exception as e:  # noqa: BLE001 - network errors of every kind are data here
            return {"status": None, "error": f"{type(e).__name__}: {e}"[:300]}, None


def _decode(body: bytes, enc: str) -> bytes:
    """Raw (id_) captures keep the original Content-Encoding; undo gzip/deflate/br."""
    import zlib
    enc = (enc or "").lower()
    try:
        if body[:2] == b"\x1f\x8b" or "gzip" in enc:
            return zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(body, MAX_BYTES)
        if "deflate" in enc:
            return zlib.decompressobj().decompress(body, MAX_BYTES)
        if "br" in enc:
            import brotli
            return brotli.decompress(body)[:MAX_BYTES]
    except Exception:  # noqa: BLE001 - mislabelled encoding: keep the bytes
        pass
    return body


def _retry_after(v: str | None) -> float | None:
    if not v:
        return None
    if v.strip().isdigit():
        return float(v)
    try:
        return max(0.0, email.utils.parsedate_to_datetime(v).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


# --- text extraction ------------------------------------------------------------------
class _Text(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
             "article", "header", "footer", "table", "ul", "ol", "blockquote", "td", "th", "time"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.meta, self.ld, self.skip, self.in_ld, self.title = [], [], [], 0, False, []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").lower() == "application/ld+json":
            self.in_ld = True
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            k = (a.get("name") or a.get("property") or a.get("itemprop") or "").lower()
            if a.get("content") and any(x in k for x in ("description", "title", "published", "date", "modified")):
                self.meta.append(f"{k}: {a['content']}")
        if tag == "time" and a.get("datetime"):
            self.out.append(f" [{a['datetime']}] ")
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "script":
            self.in_ld = False
        if tag == "title":
            self.in_title = False
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.in_ld:
            self.ld.append(data)
        elif self.in_title:
            self.title.append(data)
        elif not self.skip:
            self.out.append(data)


def _ld_text(raw: str) -> list[str]:
    out = []
    try:
        d = json.loads(raw)
    except ValueError:
        return out
    stack = [d]
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            stack += x
        elif isinstance(x, dict):
            for k in ("headline", "datePublished", "dateModified", "description", "articleBody"):
                if isinstance(x.get(k), str):
                    out.append(f"{k}: {html.unescape(x[k])}")
            stack += [v for v in x.values() if isinstance(v, (dict, list))]
    return out


def html_text(body: bytes, ctype: str) -> str:
    m = re.search(r"charset=([\w-]+)", ctype or "") or re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', body[:3000])
    enc = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)) if m else "utf-8"
    try:
        s = body.decode(enc, errors="replace")
    except LookupError:
        s = body.decode("utf-8", errors="replace")
    p = _Text()
    try:
        p.feed(s)
        p.close()
    except Exception:  # noqa: BLE001 - malformed markup: keep what was parsed
        pass
    lines = [re.sub(r"[ \t\r\f\v\xa0]+", " ", ln).strip() for ln in "".join(p.out).split("\n")]
    body_txt = "\n".join(ln for ln in lines if ln)
    head = ["TITLE: " + " ".join("".join(p.title).split())] + ["META " + m for m in p.meta]
    for raw in p.ld:
        head += ["LD " + t for t in _ld_text(raw)]
    return "\n".join(head) + "\n\n" + body_txt + "\n"


def doc_text(body: bytes, ctype: str) -> str:
    if body[:5] == b"%PDF-" or "pdf" in (ctype or "").lower():
        try:
            r = subprocess.run(["pdftotext", "-q", "-", "-"], input=body, capture_output=True, timeout=180)
            return r.stdout.decode("utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            return ""
    if (ctype or "").startswith("text/plain") or (ctype or "").startswith("text/csv"):
        return body.decode("utf-8", errors="replace")
    return html_text(body, ctype)


# --- cache ----------------------------------------------------------------------------
def ev_dir(section: str, eid: str) -> str:
    return os.path.join(CACHE, section, eid)


def load_manifest(section: str, eid: str) -> list[dict]:
    try:
        with open(os.path.join(ev_dir(section, eid), "manifest.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_manifest(section: str, eid: str, man: list[dict]):
    d = ev_dir(section, eid)
    os.makedirs(d, exist_ok=True)
    tmp = os.path.join(d, f".manifest.tmp{os.getpid()}")
    with open(tmp, "w") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    os.replace(tmp, os.path.join(d, "manifest.json"))


def doc_path(section: str, eid: str, n: int) -> str:
    return os.path.join(ev_dir(section, eid), f"{n:02d}.txt")


def _store(section: str, eid: str, man: list[dict], entry: dict, res: dict) -> dict:
    """Append a manifest entry (and the document text when fetched)."""
    old = [m for m in man if m["url"] == entry["url"]]
    n = old[0]["n"] if old else (max((m["n"] for m in man), default=0) + 1)
    entry |= {"n": n, "status": res.get("status"), "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    if res.get("body") is not None and res.get("status") == 200 and not res.get("interstitial"):
        text = doc_text(res["body"], res.get("ctype", ""))
        os.makedirs(ev_dir(section, eid), exist_ok=True)
        with open(doc_path(section, eid, n), "w", encoding="utf-8") as f:
            f.write(f"SOURCE: {entry['source_url']}\nFETCHED: {entry['url']}\n"
                    f"FINAL-URL: {res.get('final_url')}\nCONTENT-TYPE: {res.get('ctype')}\n\n{text}")
        entry |= {"ok": True, "chars": len(text), "ctype": res.get("ctype", ""),
                  "final_url": res.get("final_url"), "truncated": bool(res.get("truncated"))}
    else:
        entry |= {"ok": False, "error": res.get("error") or f"HTTP {res.get('status')}"}
    if old:
        man[man.index(old[0])] = entry
    else:
        man.append(entry)
    save_manifest(section, eid, man)
    return entry


def _ts(day: str) -> str:
    return re.sub(r"\D", "", day)[:8]


def cdx(net: Net, url: str, target: str, limit: int = 8) -> tuple[list[dict], str | None]:
    q = urllib.parse.urlencode({"url": url, "output": "json", "fl": "timestamp,original,statuscode,mimetype,digest,length",
                                "filter": "statuscode:[23]..", "sort": "closest", "closest": target, "limit": str(limit)})
    if time.time() < net.cdx_down_until:
        return available(net, url, target, "CDX server down (skipped)")
    res = net.get("https://web.archive.org/cdx/search/cdx?" + q, tries=3, breaker=False)
    if res.get("status") != 200:
        net.cdx_down_until = time.time() + CDX_PAUSE
        return available(net, url, target, res.get("error") or f"CDX HTTP {res.get('status')}")
    try:
        rows = json.loads(res["body"].decode("utf-8") or "[]")
    except ValueError:
        return [], "CDX: unparsable response"
    if not rows:
        return [], None
    hdr = rows[0]
    return [dict(zip(hdr, r)) for r in rows[1:]], None


def available(net: Net, url: str, target: str, cdx_err: str) -> tuple[list[dict], str | None]:
    """Fallback when the CDX server is down (it goes 'Temporarily Offline' while the
    rest of the Wayback Machine works): the availability API's closest capture."""
    q = urllib.parse.urlencode({"url": url, "timestamp": target})
    res = net.get("https://archive.org/wayback/available?" + q)
    if res.get("status") != 200:
        return [], f"{cdx_err}; availability API: {res.get('error') or res.get('status')}"
    try:
        snap = json.loads(res["body"].decode("utf-8")).get("archived_snapshots", {}).get("closest") or {}
    except ValueError:
        return [], f"{cdx_err}; availability API: unparsable response"
    m = re.match(r"https?://web\.archive\.org/web/(\d+)/(.+)", snap.get("url", ""))
    if not snap.get("available") or not m:
        return [], None
    return [{"timestamp": m.group(1), "original": m.group(2), "statuscode": snap.get("status", ""),
             "mimetype": "", "digest": "ts:" + m.group(1), "length": ""}], None


def fetch_source(net: Net, section: str, ev: dict, url: str, alt: bool = False, retry_failed: bool = False):
    eid, man = ev["id"], load_manifest(section, ev["id"])
    pre = "alt-" if alt else ""

    def have(u):
        return next((m for m in man if m["url"] == u and (m.get("ok") or not retry_failed)), None)

    # 1) the live URL
    if not have(url):
        log(f"  live {url[:110]}")
        e = _store(section, eid, man, {"url": url, "source_url": url, "kind": pre + "live"}, net.get(url))
        log(f"    -> {e.get('status')} {e.get('chars', e.get('error'))}")
    # 2) Wayback captures closest to the dates the claim was read/published
    key = f"cdx:{url}"
    cdx_done = next((m for m in man if m["url"] == key), None)
    if cdx_done and (cdx_done.get("ok") or not retry_failed):
        caps = cdx_done.get("captures", [])
    else:
        caps, err = [], None
        seen_ts = set()
        for target in dict.fromkeys([_ts(ev.get("retrieved", "")), _ts(ev.get("published", ""))]):
            if not target:
                continue
            rows, err = cdx(net, url, target)
            if err:
                break
            for r in rows:
                if r["timestamp"] not in seen_ts:
                    seen_ts.add(r["timestamp"])
                    caps.append(r | {"target": target})
        entry = {"url": key, "source_url": url, "kind": pre + "cdx", "captures": caps}
        entry |= {"ok": err is None, "error": err} if err else {"ok": True}
        entry |= {"n": 0, "status": None, "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        man = [m for m in man if m["url"] != key] + [entry]
        save_manifest(section, eid, man)
        log(f"  cdx {url[:100]}: {len(caps)} captures{' ERROR ' + err if err else ''}")
    # pick: the capture closest to each target, distinct digests; one more if text is tiny
    picked, digests = [], set()
    for target in dict.fromkeys(c["target"] for c in caps):
        for c in caps:
            if c["target"] == target and c["digest"] not in digests:
                picked.append(c)
                digests.add(c["digest"])
                break
    rest = [c for c in caps if c["digest"] not in digests]
    picked = picked[:CAPTURES_PER_URL]
    got_text = False
    for c in picked + rest[:2]:
        if c in rest and got_text:
            break
        cap_url = f"https://web.archive.org/web/{c['timestamp']}id_/{c['original']}"
        e = have(cap_url)
        if not e:
            log(f"  capture {c['timestamp']} {c['original'][:90]}")
            e = _store(section, eid, man, {"url": cap_url, "source_url": url, "kind": pre + "wayback",
                                            "timestamp": c["timestamp"]}, net.get(cap_url))
            log(f"    -> {e.get('status')} {e.get('chars', e.get('error'))}")
        if e.get("ok") and e.get("chars", 0) >= MIN_TEXT:
            got_text = True
        if c in rest:
            digests.add(c["digest"])


def cmd_fetch(section: str, ids: list[str] | None, retry_failed: bool):
    net = Net()
    evs = pending(section)
    if ids:
        evs = [e for e in evs if e["id"] in ids]
    os.makedirs(os.path.join(CACHE, section), exist_ok=True)
    with open(os.path.join(CACHE, section, "events.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in pending(section))
    for i, ev in enumerate(evs, 1):
        log(f"[{i}/{len(evs)}] {ev['id']}")
        for s in ev["sources"]:
            fetch_source(net, section, ev, s["url"], retry_failed=retry_failed)
    summary(section, evs)


def summary(section: str, evs: list[dict]):
    no = []
    for ev in evs:
        man = load_manifest(section, ev["id"])
        good = [m for m in man if m.get("ok") and m.get("chars", 0) >= MIN_TEXT]
        if not good:
            no.append(ev["id"])
    log(f"{section}: {len(evs) - len(no)}/{len(evs)} events have a cached document with >= {MIN_TEXT} chars")
    for i in no:
        log(f"  none: {i}")


# --- audit ----------------------------------------------------------------------------
QUOTE_MAP = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-",
                           "\u2014": "-", "\u2212": "-", "\xa0": " ", "\u2009": " ", "\u202f": " "})


def norm(s: str) -> str:
    return " ".join(html.unescape(s).translate(QUOTE_MAP).split()).lower()


YEAR_RE = re.compile(r"(?<![\d.,])(19\d\d|20\d\d)(?![\d])")


def audit_one(section: str, r: dict, ev: dict | None) -> list[str]:
    errs = []
    if ev is None:
        return [f"{r.get('id')}: not a still-unverifiable legacy event of {section}"]
    res = r.get("result")
    if res not in ("verified", "corrected", "refuted", "unverifiable"):
        return [f"{r['id']}: bad result {res!r}"]
    if not r.get("note"):
        errs.append(f"{r['id']}: missing note")
    if res == "unverifiable":
        return errs
    man = {m["n"]: m for m in load_manifest(section, r["id"]) if m.get("ok") and m.get("n")}
    ev_q = r.get("evidence") or []
    if not ev_q:
        errs.append(f"{r['id']}: {res} needs evidence quotes")
    texts = {}
    for q in ev_q:
        n = q.get("doc")
        if n not in man:
            errs.append(f"{r['id']}: evidence doc {n!r} is not a fetched document of this event")
            continue
        if n not in texts:
            with open(doc_path(section, r["id"], n), encoding="utf-8") as f:
                texts[n] = norm(f.read())
        qt = norm(str(q.get("quote", "")))
        if len(qt) < 15:
            errs.append(f"{r['id']}: quote too short: {q.get('quote')!r}")
        elif qt not in texts[n]:
            errs.append(f"{r['id']}: quote not verbatim in doc {n}: {q.get('quote')[:100]!r}")
    fetched_sources = {m["source_url"] for m in man.values()}
    srcs = r.get("sources") or []
    if res in ("verified", "corrected"):
        if not srcs:
            errs.append(f"{r['id']}: needs sources")
        for s in srcs:
            if s.get("url") not in fetched_sources:
                errs.append(f"{r['id']}: source {s.get('url')} was not fetched for this event")
        used = {man[q["doc"]]["source_url"] for q in ev_q if q.get("doc") in man}
        if srcs and not used & {s.get("url") for s in srcs}:
            errs.append(f"{r['id']}: no evidence quote comes from a listed source")
        claim = ev["claim"] if res == "verified" else r.get("claim") or ""
        if res == "corrected" and not r.get("claim"):
            errs.append(f"{r['id']}: corrected needs a claim")
        if res == "verified" and r.get("claim") and norm(r["claim"]) != norm(ev["claim"]):
            errs.append(f"{r['id']}: verified must keep the legacy claim (reworded -> corrected)")
        errs += _figure_errs(r["id"], claim, ev_q)
        if r.get("date") is not None:
            d = str(r["date"])
            if not ledger._valid_date(d):
                errs.append(f"{r['id']}: bad date {d!r} (YYYY, YYYY-MM or YYYY-MM-DD)")
            elif d[:4] not in norm(" | ".join(str(q.get("quote", "")) for q in ev_q)):
                errs.append(f"{r['id']}: the year of the corrected date {d} is in no evidence quote")
    elif r.get("date") is not None:
        errs.append(f"{r['id']}: only a verified/corrected result may move the event date")
    if res == "refuted":
        claim = str(r.get("claim") or "")
        if not claim.startswith("Withdrawn after re-verification: "):
            errs.append(f"{r['id']}: a refuted result needs a tombstone claim 'Withdrawn after re-verification: ...'")
        # the tombstone may restate the legacy (wrong) figures; any other figure needs a quote
        errs += _figure_errs(r["id"], claim, ev_q, also=ev["claim"])
    return errs


def _figure_errs(eid: str, claim: str, ev_q: list[dict], also: str = "") -> list[str]:
    errs = []
    quotes = " | ".join(str(q.get("quote", "")) for q in ev_q)
    pool = {abs(x) for x in kpi.quantities(quotes + " | " + also)}
    for v in sorted(kpi.quantities(claim)):
        if abs(v) not in pool:
            errs.append(f"{eid}: figure {v:g} of the claim is in no evidence quote")
    qn = norm(quotes + " | " + also)
    for y in sorted(set(YEAR_RE.findall(claim))):
        if y not in qn:
            errs.append(f"{eid}: year {y} of the claim is in no evidence quote")
    return errs


def load_results(p: str) -> list[dict]:
    out = []
    with open(p, encoding="utf-8") as f:
        for i, ln in enumerate(f, 1):
            if ln.strip():
                try:
                    out.append(json.loads(ln))
                except ValueError as e:
                    raise SystemExit(f"{p}:{i}: bad JSON: {e}")
    return out


def cmd_audit(section: str, results: list[dict], partial: bool = False) -> list[str]:
    evs = {e["id"]: e for e in pending(section)}
    errs = []
    seen = set()
    for r in results:
        if r.get("id") in seen:
            errs.append(f"{r.get('id')}: duplicate result")
        seen.add(r.get("id"))
        errs += audit_one(section, r, evs.get(r.get("id")))
    missing = sorted(set(evs) - seen)
    if missing and not partial:
        errs.append(f"no result for {len(missing)} event(s): {', '.join(missing)}")
    return errs


# --- records --------------------------------------------------------------------------
def _new_id(base: str, suffix: str, taken: set[str]) -> str:
    i, cand = 1, f"{base}-{suffix}"
    while cand in taken:
        i += 1
        cand = f"{base}-{suffix}{i}"
    return cand


def build_records(section: str, results: list[dict], by: str, today: str) -> tuple[list[dict], list[dict]]:
    evs = {e["id"]: e for e in pending(section)}
    taken = {e["id"] for e in ledger.events(section)}
    log_rows, recs = [], []
    for r in results:
        ev = evs[r["id"]]
        man = {m["n"]: m for m in load_manifest(section, r["id"]) if m.get("n")}
        docs = []
        for q in r.get("evidence") or []:
            if q["doc"] not in docs:
                docs.append(q["doc"])
        caps = [man[n]["url"] for n in docs if "wayback" in man[n]["kind"]]
        fetched = [{"doc": m["n"], "url": m["url"], "status": m.get("status"), "ok": bool(m.get("ok"))}
                   for m in man.values() if not m["url"].startswith("cdx:")]
        note = r["note"].strip()
        if caps and not all(c in note for c in caps):
            note += " Capture: " + ", ".join(caps)
        log_rows.append({"id": r["id"], "result": r["result"], "note": note, "fetched": fetched})
        if r["result"] == "unverifiable":
            continue
        cap_srcs = [{"url": c, "title": "Wayback capture " + re.search(r"/web/(\d+)", c).group(1), "primary": False}
                    for c in caps]
        verification = {"status": "verified" if r["result"] in ("verified", "refuted") else "corrected",
                        "by": by, "at": today, "note": note}
        collector = "reverify:" + ev["collector"]
        if r["result"] == "refuted":
            rid = _new_id(ev["id"], "wd", taken)
            live = [{"url": man[n]["source_url"], "title": s.get("title", ""), "primary": s.get("primary", False)}
                    for n in docs if "wayback" not in man[n]["kind"]
                    for s in [next((x for x in ev["sources"] if x["url"] == man[n]["source_url"]), {})]]
            rec = {"id": rid, "date": ev["date"], "published": today, "published_basis": "seen", "retrieved": today,
                   "kind": "retraction", "topics": ev["topics"], "claim": r["claim"].strip(),
                   "sources": _dedup(live + cap_srcs), "significance": ev["significance"],
                   "supersedes": [ev["id"]], "withdrawn": True, "verification": verification, "collector": collector}
        else:
            date = str(r.get("date") or ev["date"])
            base = ev["id"] if date == ev["date"] else \
                (date + "-01-01"[len(date) - 4:] if len(date) < 10 else date) + ev["id"][10:]
            rid = _new_id(base, "rv", taken)
            titles = {s["url"]: s for s in ev["sources"]}
            srcs = [{"url": s["url"], "title": s.get("title") or titles.get(s["url"], {}).get("title", ""),
                     "primary": bool(s.get("primary", titles.get(s["url"], {}).get("primary", False)))}
                    for s in r["sources"]]
            claim = ev["claim"] if r["result"] == "verified" else r["claim"].strip()
            rec = {k: ev[k] for k in ("id", "date", "published", "published_basis", "retrieved", "kind", "topics")}
            rec |= {"id": rid, "date": date, "claim": claim, "sources": _dedup(srcs + cap_srcs), "significance": ev["significance"]}
            quotes = " | ".join(q["quote"] for q in r.get("evidence") or [])
            pool = {abs(x) for x in kpi.quantities(quotes)}
            # metric links survive only if the judged claim kept every linked value (a value
            # merely recurring in a quote, e.g. another year's, does not back its link)
            mets = ev.get("metrics") or []
            if mets and (r["result"] == "verified" or all(abs(float(m["value"])) in pool for m in mets)):
                rec["metrics"] = mets
            if ev.get("relates"):
                rec["relates"] = ev["relates"]
            rec |= {"verification": verification, "collector": collector, "supersedes": [ev["id"]]}
        taken.add(rid)
        recs.append(rec)
    return log_rows, recs


def _dedup(srcs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for s in srcs:
        if s["url"] not in seen:
            seen.add(s["url"])
            out.append(s)
    return out


def cmd_stage(section: str, results: list[dict], tag: str, by: str, today: str) -> int:
    errs = cmd_audit(section, results)
    if errs:
        print("\n".join("AUDIT " + e for e in errs))
        return 1
    log_rows, recs = build_records(section, results, by, today)
    logp = os.path.join(ledger.DATA, "ledger", "reverify", f"{section}.{today}-{tag}.jsonl")
    with open(logp, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in log_rows)
    stp = os.path.join(CACHE, section, f"staged-{tag}.jsonl")
    with open(stp, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in recs)
    c = {}
    for x in log_rows:
        c[x["result"]] = c.get(x["result"], 0) + 1
    print(f"log: {logp}\nstaged: {stp} ({len(recs)} records)\ncounts: {json.dumps(c)}")
    return 0


def main() -> int:
    resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").add_argument("section", choices=ledger.SECTIONS)
    f = sub.add_parser("fetch")
    f.add_argument("section", choices=ledger.SECTIONS)
    f.add_argument("--ids", nargs="*")
    f.add_argument("--retry-failed", action="store_true")
    fu = sub.add_parser("fetch-url")
    fu.add_argument("section", choices=ledger.SECTIONS)
    fu.add_argument("id")
    fu.add_argument("url")
    sh = sub.add_parser("show")
    sh.add_argument("section", choices=ledger.SECTIONS)
    sh.add_argument("id")
    a = sub.add_parser("audit")
    a.add_argument("section", choices=ledger.SECTIONS)
    a.add_argument("results")
    a.add_argument("--partial", action="store_true", help="a batch: do not require a result for every event")
    st = sub.add_parser("stage")
    st.add_argument("section", choices=ledger.SECTIONS)
    st.add_argument("results")
    st.add_argument("--tag", required=True)
    st.add_argument("--by", required=True)
    st.add_argument("--today", default=dt.date.today().isoformat())
    args = ap.parse_args()
    if args.cmd == "list":
        for e in pending(args.section):
            print(json.dumps(e, ensure_ascii=False))
    elif args.cmd == "fetch":
        cmd_fetch(args.section, args.ids, args.retry_failed)
    elif args.cmd == "fetch-url":
        ev = next((e for e in pending(args.section) if e["id"] == args.id), None)
        if not ev:
            raise SystemExit(f"{args.id}: not a still-unverifiable legacy event of {args.section}")
        if not ledger.URL_RE.match(args.url) or "archive.org" in args.url:
            raise SystemExit("give the source's own http(s) URL (Wayback captures are looked up automatically)")
        fetch_source(Net(), args.section, ev, args.url, alt=args.url not in {s["url"] for s in ev["sources"]})
        for m in load_manifest(args.section, args.id):
            if m["source_url"] == args.url and not m["url"].startswith("cdx:"):
                print(f"doc {m['n']:02d} {m['kind']} ok={m.get('ok')} chars={m.get('chars', 0)} "
                      f"{m['url']} -> {doc_path(args.section, args.id, m['n'])}" if m.get("ok") else
                      f"doc {m['n']:02d} {m['kind']} FAILED {m.get('error')} {m['url']}")
    elif args.cmd == "show":
        ev = next((e for e in pending(args.section) if e["id"] == args.id), None)
        print(json.dumps(ev, ensure_ascii=False, indent=1))
        for m in load_manifest(args.section, args.id):
            if m["url"].startswith("cdx:"):
                print(f"cdx {m['source_url']}: {len(m.get('captures', []))} captures {m.get('error') or ''}")
            else:
                print(f"doc {m['n']:02d} {m['kind']:<12} ok={m.get('ok')} chars={m.get('chars', 0):>7} {m['url']}"
                      + (f"  ({m.get('error')})" if not m.get("ok") else ""))
    elif args.cmd == "audit":
        errs = cmd_audit(args.section, load_results(args.results), args.partial)
        print("\n".join(errs) if errs else "audit OK")
        return 1 if errs else 0
    elif args.cmd == "stage":
        return cmd_stage(args.section, load_results(args.results), args.tag, args.by, args.today)
    return 0


if __name__ == "__main__":
    sys.exit(main())
