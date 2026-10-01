#!/usr/bin/env python3
"""Deterministic, no-LLM validation gate for a generated newsletter section.

Run AFTER the review stage. Catches mechanical defects the LLM review can miss
(and can't be talked out of): footnote/reference integrity, mermaid chart
axis/series length mismatches, dead citation URLs, and (optional) coverage of
the run's PLAN slugs.

Usage:
    uv run validate.py <bulletin.md> --snapshot <period-dir>/snapshot/<section>.json
    uv run validate.py <period-dir>/README.md --roundup

Exit status: 0 if no ERRORs (WARNs allowed), 1 otherwise.
Env:
    NO_NET=1   skip the network link check entirely.

Link liveness is a heuristic, not proof: a URL is "dead" (error) only if two
GETs 3 s apart both return 404/410; HEAD-404 alone never is. Known limits: a
cached/bot-served 404 can still false-positive (use STRICT=0 in bulletin.sh /
roundup.sh to proceed report-only), and HEAD-200 is trusted without a GET.
Regression tests: uv run test_harness.py
"""
import argparse
import os
import re
import sys
import time
import urllib.request
import urllib.error

ERRORS: list[str] = []
WARNS: list[str] = []


def strip_code(text: str) -> str:
    """Remove fenced code blocks so footnote/ref scanning ignores code/mermaid."""
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def strip_code_spans(text: str) -> str:
    """Blank inline code spans (CommonMark: a backtick run closed by an equal-length
    run, within one paragraph). Newlines are kept so line starts stay put."""
    out, pos = [], 0
    runs = list(re.finditer(r"`+", text))
    i = 0
    while i < len(runs):
        m = runs[i]
        if m.start() < pos:
            i += 1
            continue
        close = next((r for r in runs[i + 1:] if len(r.group()) == len(m.group())), None)
        if close is None or "\n\n" in text[m.end():close.start()]:
            i += 1  # unmatched run is literal text
            continue
        out.append(text[pos:m.start()])
        out.append(re.sub(r"[^\n]", " ", text[m.start():close.end()]))
        pos = close.end()
        i += 1
    out.append(text[pos:])
    return "".join(out)


def norm_label(label: str) -> str:
    """CommonMark label matching: case-insensitive, internal whitespace collapsed."""
    return " ".join(label.split()).casefold()


def err(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNS.append(msg)


# --- footnote + reference-link integrity ------------------------------------
# Definitions start a line, indented at most 3 spaces (4+ is an indented code block).
FN_DEF_RE = re.compile(r"(?m)^ {0,3}(\[\^([^\[\]]*\S[^\[\]]*)\]):")
FN_USE_RE = re.compile(r"\[\^([^\[\]]*\S[^\[\]]*)\]")
REF_DEF_RE = re.compile(r"(?m)^ {0,3}(\[([^\[\]^][^\[\]]*)\]):[ \t]*\n?[ \t]*\S")
REF_LABEL = r"[^\[\]^][^\[\]]*"


def _defs(regex: re.Pattern, text: str, kind: str, fmt: str) -> tuple[dict, set]:
    """-> ({normalized label: display label}, {start offsets of the definitions' brackets})."""
    seen: dict[str, str] = {}
    count: dict[str, int] = {}
    starts = set()
    for m in regex.finditer(text):
        if not m.group(2).strip():
            continue
        key = norm_label(m.group(2))
        seen.setdefault(key, m.group(2))
        count[key] = count.get(key, 0) + 1
        starts.add(m.start(1))
    for key, n in count.items():
        if n > 1:
            err(f"{kind} {fmt.format(seen[key])} defined {n} times")
    return seen, starts


def check_footnotes(text: str) -> None:
    text = strip_code_spans(text)
    defs, starts = _defs(FN_DEF_RE, text, "footnote", "[^{}]")
    used = {norm_label(m.group(1)): m.group(1) for m in FN_USE_RE.finditer(text)
            if m.start() not in starts}
    for key in sorted(used.keys() - defs.keys()):
        err(f"footnote [^{used[key]}] used but never defined")
    for key in sorted(defs.keys() - used.keys()):
        warn(f"footnote [^{defs[key]}] defined but never used")


def check_reference_links(text: str) -> None:
    text = strip_code_spans(text)
    defs, starts = _defs(REF_DEF_RE, text, "reference link", "[{}]")
    used: dict[str, str] = {}
    # Full [text][label] and collapsed [label][] must resolve. Neither bracket may
    # start with '^', so adjacent footnotes like [^a][^b] are not a reference link.
    for m in re.finditer(rf"\[({REF_LABEL})\]\[({REF_LABEL})?\]", text):
        label = m.group(2) if m.group(2) is not None else m.group(1)
        if label.strip():
            used.setdefault(norm_label(label), label)
    for key in sorted(used.keys() - defs.keys()):
        err(f"reference link [{used[key]}] used but never defined")
    # Shortcut [label]: only a link when such a definition exists (else plain text).
    for m in re.finditer(rf"(?<!\])\[({REF_LABEL})\](?![\[(])", text):
        key = norm_label(m.group(1))
        if m.start() not in starts and key in defs:
            used.setdefault(key, m.group(1))
    for key in sorted(defs.keys() - used.keys()):
        warn(f"reference link definition [{defs[key]}] never used")


# --- mermaid xychart axis/series consistency --------------------------------
def check_mermaid(text: str) -> None:
    blocks = re.findall(r"```mermaid\n(.*?)```", text, re.DOTALL)
    for i, block in enumerate(blocks, 1):
        if "xychart" not in block:
            continue
        xs = re.findall(r"x-axis\s+\[([^\]]*)\]", block)
        if not xs:
            warn(f"mermaid xychart #{i}: no x-axis array found")
            continue
        xn = len([c for c in xs[0].split(",") if c.strip()])
        for kind, arr in re.findall(r"^\s*(line|bar)\s+\[([^\]]*)\]", block, re.M):
            n = len([c for c in arr.split(",") if c.strip()])
            if n != xn:
                err(f"mermaid xychart #{i}: {kind} has {n} points but x-axis has {xn}")


# --- citation URL liveness --------------------------------------------------
def extract_urls(text: str) -> list[str]:
    raw = re.findall(r"https?://[^\s\]<>\"']+", text)
    seen, out = set(), []
    for u in raw:
        u = u.rstrip(".,;:")
        while u.endswith(")") and u.count(")") > u.count("("):  # markdown link close, keep "(25)"
            u = u[:-1].rstrip(".,;:")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def check_links(text: str) -> None:
    if os.environ.get("NO_NET"):
        warn("link check skipped (NO_NET=1)")
        return
    for url in extract_urls(text):
        status = probe(url)
        if status in ("404", "410"):
            err(f"citation URL appears dead ({status}): {url}")
        elif status != "ok":
            # 403/5xx/redirect-loops/network errors are NOT hard failures: many
            # valid sources block bots or HEAD, or time out transiently.
            warn(f"citation URL uncertain ({status}, not a hard 404): {url}")


def probe(url: str) -> str:
    # HEAD first (cheap); then GET, and a second GET after a pause. A URL is
    # "dead" only if BOTH GETs say 404/410: some servers 404 on HEAD but serve
    # GET (EDGAR), and some 404 transiently (seen with the Met Office). Other
    # HTTP errors (403/405/5xx) and network failures ("neterr") are warn-level.
    last = "neterr"
    gets_dead = 0
    for i, method in enumerate(("HEAD", "GET", "GET")):
        if i == 2:
            if gets_dead == 0 and last not in ("404", "410"):
                break  # first GET failed non-fatally; no need to retry
            time.sleep(3)
        try:
            req = urllib.request.Request(
                url, method=method, headers={"User-Agent": "Mozilla/5.0 (validate.py)"}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                return "ok" if r.status < 400 else str(r.status)
        except urllib.error.HTTPError as e:
            last = str(e.code)
            if method == "GET" and e.code in (404, 410):
                gets_dead += 1
        except Exception:
            last = "neterr"  # timeout / DNS / TLS / connection — transient, warn
    if gets_dead == 2:
        return last
    return "neterr" if last in ("404", "410") else last


# --- round-up (period README.md) checks --------------------------------------
# A number token: not preceded by a letter/digit/dot (so "CO2", "v2.1" and the
# "1" of "26H1" are skipped), never a partial decimal, and unit suffixes
# ("9%", "12.5GW", "$8.99B", "100K") are allowed. Thousands separators (comma/
# space/thin space) are normalized away.
NUM_RE = re.compile(
    r"(?<![\w.])(?:\d{1,3}(?:[,\u2009\u202f ]\d{3})+|\d+)(?:\.\d+)?(?![\d]|[.,]\d)"
)
MDLINK_RE = re.compile(r"\]\(([^)\s]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s")


def numbers(text: str) -> set[str]:
    text = re.sub(r"https?://\S+", " ", text)  # URLs are not claims
    text = re.sub(r"\]\([^)]*\)", "]", text)   # nor link targets
    out = set()
    for m in NUM_RE.finditer(text):
        n = re.sub(r"[,\u2009\u202f ]", "", m.group())
        # bare calendar years are labels, not claims (a "%"/unit right after
        # makes it a quantity again)
        if "." not in n and 1900 <= int(n) <= 2100 and not re.match(r"\s?%|[A-Za-z]", text[m.end():m.end() + 2]):
            continue
        out.add(n)
    return out


def traceable(n: str, pool: set[str]) -> bool:
    if n in pool:
        return True
    f = float(n)  # tolerate trailing-zero differences (2.50 vs 2.5)
    return any(float(p) == f for p in pool)


def check_roundup(doc_path: str, text: str) -> None:
    """Round-up README: every local .md link resolves, every section file in the
    period dir is linked, and every number traces to its linked section (the
    round-up must summarize, never add facts)."""
    base = os.path.dirname(os.path.abspath(doc_path))
    me = os.path.basename(doc_path)
    sections = sorted(
        f for f in os.listdir(base)
        if f.endswith(".md") and f != me and f[0].islower()
    )
    local = [
        t for t in MDLINK_RE.findall(text)
        if not re.match(r"[a-z]+:", t) and t.split("#")[0].endswith(".md")
    ]
    linked = {t.split("#")[0] for t in local}
    for t in sorted(linked):
        if not os.path.exists(os.path.join(base, t)):
            err(f"roundup: link to missing section file '{t}'")
    for s in sections:
        if s not in linked:
            err(f"roundup: section file '{s}' exists but is not linked from {me}")

    # Evidence = ONLY the canonical section files of this period dir (other
    # linked files, e.g. research notes or older periods, are not evidence).
    # An endeavor block runs from the nearest heading after the previous section
    # link up to the line holding its own section link; everything else (intro,
    # shared group intros, quick-reference table) is checked against the union
    # of this period's sections.
    sec_text = {
        s: open(os.path.join(base, s), encoding="utf-8").read() for s in sections
    }
    union = set().union(*(numbers(t) for t in sec_text.values())) if sec_text else set()
    pending: list[str] = []   # lines since the previous section link
    unattributed: list[str] = []
    for line in text.splitlines():
        links = [t.split("#")[0] for t in MDLINK_RE.findall(line) if t.split("#")[0] in sec_text]
        if not links:
            pending.append(line)
            continue
        heads = [i for i, ln in enumerate(pending) if HEADING_RE.match(ln)]
        start = heads[-1] if heads else len(pending)
        unattributed += pending[:start]
        pool = numbers(sec_text[links[0]])
        for n in sorted(numbers("\n".join(pending[start:] + [line]))):
            if not traceable(n, pool):
                err(f"roundup: number '{n}' in the {links[0]} block not found in {links[0]}")
        pending = []
    unattributed += pending
    for n in sorted(numbers("\n".join(unattributed))):
        if not traceable(n, union):
            err(f"roundup: number '{n}' (outside any section block) not found in any section of this period")


# --- bulletin vs ledger snapshot -------------------------------------------------
DEF_LINE_RE = re.compile(r"^ {0,3}\[\^?[^\]]+\]:.*$", re.M)  # footnote / reference definitions


def check_snapshot(doc_path: str, text: str, snap_path: str) -> None:
    """A bulletin may only state what its ledger snapshot contains (DESIGN.md §5)."""
    import json
    import kpi
    import ledger
    snap = json.load(open(snap_path, encoding="utf-8"))
    prose = strip_code(text)
    # 1. citations: every URL must be a source of a snapshot record
    allowed = ledger.snapshot_urls(snap)
    for url in extract_urls(prose):
        if url not in allowed:
            err(f"snapshot: cited URL is not a source of any snapshot record: {url}")
    # 2. numbers in prose (not footnote/reference definitions: titles, page numbers)
    body = re.sub(r"https?://\S+", " ", DEF_LINE_RE.sub(" ", prose))
    pool = kpi.kpi_numbers(ledger.snapshot_evidence_text(snap))  # typed evidence only
    missing = sorted(n for n in kpi.kpi_numbers(body) if not (n in pool or (n < 0 and -n in pool)))
    for n in missing:
        err(f"snapshot: number {n:g} in the prose does not occur in the snapshot (use snapshot values verbatim)")
    # 3. KPI headlines reported (or explicitly unavailable)
    nums = kpi.kpi_numbers(body)
    for k in snap["kpi_headlines"]:
        cur = k["current"]
        if cur and not kpi.kpi_traceable(cur["value"], nums):
            err(f"snapshot: KPI headline {k['metric']} = {cur['value']} {k['unit']} ({cur['obs']}) not reported")
        if not cur and not re.search(r"\b(no (new |current )?(reading|data|value)|not (yet )?available|unavailable)\b", body, re.I):
            err(f"snapshot: KPI {k['metric']} has no reading as of the cutoff, and the bulletin never says so")
    # 4. charts match the ledger as of the cutoff; KPI charts required when chartable
    for e in kpi.verify_charts(text, os.path.dirname(os.path.abspath(doc_path))):
        err(f"snapshot: {e}")
    req = {k["metric"] for k in snap["kpi_headlines"]}
    if any(c["metric"] in req for c in snap["chartable_metrics"]) and not kpi.MARKER_RE.search(text):
        err("snapshot: a required KPI has a chartable series but the bulletin has no ledger-rendered ('%% kpi:') chart")
    # 5. coverage (structural): every milestone/challenge of the snapshot's frozen
    #    framework has its own heading (older snapshots: README at validation time)
    heads = "\n".join(ln.lower() for ln in prose.splitlines() if ln.lstrip().startswith("#"))
    frame = snap.get("framework")
    if frame is None:
        err("snapshot: predates the frozen README framework (regenerate the bulletin)")
        frame = []
    for f in frame:
        if f["topic"].startswith(("milestone:", "challenge:")) and f["name"].lower() not in heads:
            err(f"snapshot: {f['topic'].split(':')[0]} '{f['name']}' has no heading of its own "
                "(say 'no significant developments' under it if none)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc")
    ap.add_argument("--snapshot", help="bulletin gate: the ledger snapshot JSON the bulletin was written from")
    ap.add_argument("--roundup", action="store_true",
                    help="doc is a period round-up README: check section links + number traceability")
    args = ap.parse_args()

    text = open(args.doc, encoding="utf-8").read()
    prose = strip_code(text)  # footnote/ref checks ignore fenced code/mermaid
    check_footnotes(prose)
    check_reference_links(prose)
    check_mermaid(text)
    if args.roundup:
        check_roundup(args.doc, prose)
    if args.snapshot:
        check_snapshot(args.doc, text, args.snapshot)
    check_links(text)  # network last (slowest)

    for w in WARNS:
        print(f"  WARN  {w}")
    for e in ERRORS:
        print(f"  ERROR {e}")
    n_e, n_w = len(ERRORS), len(WARNS)
    print(f"\nvalidation: {n_e} error(s), {n_w} warning(s) — {args.doc}")
    return 1 if n_e else 0


if __name__ == "__main__":
    sys.exit(main())
