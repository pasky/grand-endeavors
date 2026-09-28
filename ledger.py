#!/usr/bin/env python3
"""Grand Endeavors ledger: the canonical, append-only record of what is known
and when it became known. See DESIGN.md (§2 time semantics, §3 schemas).

COMMANDS
  ledger.py check [section ...]                    validate ledger files (all sections by default)
  ledger.py topics <section>                       valid topic tags (from README.md)
  ledger.py recent <section> [--limit N]           compact event list (for intake dedup prompts)
  ledger.py lint <section> [--events F] [--obs F]  validate a staged file (run before merge)
  ledger.py merge <section> [--events F] [--obs F] merge VERIFIED staged records into the ledger
                                                   (rejected ones -> ledger/rejected/)
  ledger.py cutoff <period>                        bulletin cutoff date (+ previous period's cutoff)
  ledger.py snapshot <period-dir> <section>        write <period-dir>/snapshot/<section>.json
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SECTIONS = ["robots-software", "robots-hardware", "rockets", "fusion", "health",
            "climate", "knowledge-beyond", "society-cohesion"]
EVENT_KINDS = {"achievement", "announcement", "projection", "setback", "data",
               "analysis", "policy", "retraction"}
RELS = {"update", "retraction", "confirmation", "delay", "followup"}
EV_VERIF = {"verified", "corrected", "legacy"}
OBS_VERIF = {"verified", "corrected", "collector", "legacy"}
STAGED_VERIF = {"verified", "corrected", "collector", "rejected", "unverified"}
BASES = {"source", "rule", "seen"}
OBS_COLUMNS = ["metric", "obs", "value", "unit", "source", "published",
               "published_basis", "retrieved", "collector", "verification", "note"]
ASSESS_STATUS = {"green", "yellow", "red"}
EVENT_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_RE = re.compile(r"^https?://\S+$")


def path(kind: str, section: str) -> str:
    ext = "csv" if kind == "observations" else ("json" if kind == "state" else "jsonl")
    return os.path.join(ROOT, "ledger", kind, f"{section}.{ext}")


def day(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def date_end(s: str) -> dt.date:
    """Last day covered by a YYYY / YYYY-MM / YYYY-MM-DD date."""
    import kpi
    return kpi.obs_range(s)[1]


# --- README topics ------------------------------------------------------------
_HEADINGS = {"robots-software": "### Software", "robots-hardware": "### Hardware",
             "rockets": "## Rockets and Space", "fusion": "## Fusion and Energy",
             "health": "## Health and Lifespan", "climate": "## Climate and Environment",
             "knowledge-beyond": "### The Knowledge Beyond",
             "society-cohesion": "### Society and Cohesion"}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("$", "")).strip("-")


def readme_topics(section: str) -> dict[str, list[str]]:
    """{'milestones': [(slug, name)...], 'challenges': [...]} parsed from README.md."""
    lines = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == _HEADINGS[section])
    level = len(_HEADINGS[section].split()[0])
    end = next((i for i in range(start + 1, len(lines))
                if re.match(r"^#{1,%d} " % level, lines[i])), len(lines))
    out: dict[str, list] = {"milestones": [], "challenges": []}
    mode = None
    for ln in lines[start:end]:
        if "Milestone Countdown" in ln:
            mode = "milestones"
        elif "Major Open Challenges" in ln or "Tech Tree" in ln:  # fusion: tech-tree branches = challenges
            mode = "challenges"
        elif mode and (m := re.match(r"^\*\s+\*\*(.+?)\*\*", ln)):
            name = m[1].rstrip(":").strip().strip('"“”')
            out[mode].append((slugify(name), name))
        elif mode and ln.strip() and not ln.startswith(" ") and not re.match(r"^\*\s", ln):
            mode = None  # any other paragraph (incl. a bold "**Header:**") ends the list
    return out


def valid_topics(section: str) -> set[str]:
    t = readme_topics(section)
    return ({"kpi", "beyond"} | {f"milestone:{s}" for s, _ in t["milestones"]}
            | {f"challenge:{s}" for s, _ in t["challenges"]})


# --- loading --------------------------------------------------------------------
def load_jsonl(p: str) -> list[dict]:
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for i, ln in enumerate(f, 1):
            if ln.strip():
                try:
                    rec = json.loads(ln)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{os.path.relpath(p, ROOT)}:{i}: bad JSON ({e})")
                rec["_line"] = i
                out.append(rec)
    return out


def load_obs(p: str) -> list[dict]:
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if r.fieldnames != OBS_COLUMNS:
            raise ValueError(f"{os.path.relpath(p, ROOT)}: header must be exactly {','.join(OBS_COLUMNS)}")
        rows = [dict(row, _line=i) for i, row in enumerate(r, 2)]
    for row in rows:
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f"{os.path.relpath(p, ROOT)}:{row['_line']}: wrong number of fields")
    return rows


def events(section: str) -> list[dict]:
    return load_jsonl(path("events", section))


def observations(section: str) -> list[dict]:
    return load_obs(path("observations", section))


def assessments(section: str) -> list[dict]:
    return load_jsonl(path("assessments", section))


def clean(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def rule_published(obs: str, lag_days: str, retrieved: str) -> str:
    """Rule-basis publication date: obs end + registry lag, capped at retrieved."""
    import kpi
    return str(min(kpi.obs_range(obs)[1] + dt.timedelta(days=int(lag_days)), day(retrieved)))


# --- validation -------------------------------------------------------------------
def check_event(e: dict, section: str, topics: set[str], staged: bool = False) -> list[str]:
    at = f"event {e.get('id', '?')}"
    errs = []
    need = ["id", "date", "published", "published_basis", "retrieved", "kind", "topics",
            "claim", "sources", "significance", "verification", "collector"]
    errs += [f"{at}: missing '{k}'" for k in need if k not in e]
    if errs:
        return errs
    extra = set(e) - set(need) - {"metrics", "relates", "note", "_line"}
    if extra:
        errs.append(f"{at}: unknown field(s) {sorted(extra)}")
    if not EVENT_ID_RE.match(str(e["id"])):
        errs.append(f"{at}: id must be YYYY-MM-DD-slug")
    if not DATE_RE.match(str(e["date"])):
        errs.append(f"{at}: bad date '{e['date']}'")
    elif not str(e["id"]).startswith(str(e["date"])[:10] if len(str(e["date"])) == 10 else str(e["date"])):
        errs.append(f"{at}: id must start with the event date")
    for k in ("published", "retrieved"):
        if not DAY_RE.match(str(e[k])):
            errs.append(f"{at}: {k} must be YYYY-MM-DD")
    if e["published_basis"] not in BASES:
        errs.append(f"{at}: published_basis must be one of {sorted(BASES)}")
    if not errs and day(e["published"]) > day(e["retrieved"]):
        errs.append(f"{at}: published after retrieved")
    if e["kind"] not in EVENT_KINDS:
        errs.append(f"{at}: kind '{e['kind']}' not in {sorted(EVENT_KINDS)}")
    if not isinstance(e["topics"], list) or not e["topics"]:
        errs.append(f"{at}: topics must be a non-empty list")
    else:
        errs += [f"{at}: unknown topic '{t}' (valid: ledger.py topics {section})" for t in e["topics"] if t not in topics]
    if len(str(e["claim"]).split()) < 6:
        errs.append(f"{at}: claim too short to be self-contained")
    if not isinstance(e["sources"], list) or not e["sources"]:
        errs.append(f"{at}: needs at least one source")
    else:
        for s in e["sources"]:
            if not isinstance(s, dict) or not URL_RE.match(str(s.get("url", ""))):
                errs.append(f"{at}: source needs a single http(s) url")
    if e["significance"] not in (1, 2, 3):
        errs.append(f"{at}: significance must be 1, 2 or 3")
    v = e["verification"]
    allowed = STAGED_VERIF if staged else EV_VERIF
    if not isinstance(v, dict) or v.get("status") not in allowed:
        errs.append(f"{at}: verification.status must be one of {sorted(allowed)}")
    elif v["status"] != "legacy" and not (v.get("by") and v.get("at")):
        errs.append(f"{at}: verification needs 'by' and 'at'")
    for r in e.get("relates", []) or []:
        if not isinstance(r, dict) or r.get("rel") not in RELS or not r.get("id"):
            errs.append(f"{at}: relates entries need id + rel in {sorted(RELS)}")
    for m in e.get("metrics", []) or []:
        if not isinstance(m, dict) or not {"metric", "obs", "value"} <= set(m):
            errs.append(f"{at}: metrics entries need metric, obs, value")
    return errs


def check_assessment(a: dict, topics: set[str], evs: dict[str, dict]) -> list[str]:
    """made_at = the as-of date of the evidence considered (not wall-clock), so
    every evidence event must be known by then; `by` records the actual run."""
    at = f"assessment {a.get('id')}"
    errs = [f"{at}: missing '{k}'" for k in ("id", "target", "status", "label", "made_at", "rationale", "evidence", "by")
            if k not in a]
    if errs:
        return errs
    if a["status"] not in ASSESS_STATUS:
        errs.append(f"{at}: status must be green/yellow/red")
    if a["target"] not in topics - {"beyond"}:
        errs.append(f"{at}: unknown target '{a['target']}'")
    if not DAY_RE.match(str(a["made_at"])):
        return errs + [f"{at}: made_at must be YYYY-MM-DD"]
    if not a["evidence"]:
        errs.append(f"{at}: needs evidence (event ids)")
    for eid in a["evidence"]:
        if eid not in evs:
            errs.append(f"{at}: evidence '{eid}' is not an event")
        elif known_at(evs[eid]) > day(a["made_at"]):
            errs.append(f"{at}: evidence '{eid}' was published after made_at (hindsight)")
    return errs


def check_obs_row(r: dict, reg: dict | None, staged: bool = False) -> list[str]:
    import kpi
    at = f"obs {r.get('metric')}@{r.get('obs')} (line {r.get('_line')})"
    errs = []
    if reg is not None and r["metric"] not in reg:
        errs.append(f"{at}: metric not in the registry")
    elif reg is not None and reg[r["metric"]]["unit"] != r["unit"]:
        errs.append(f"{at}: unit '{r['unit']}' != registry '{reg[r['metric']]['unit']}'")
    try:
        kpi.obs_range(r["obs"])
    except ValueError:
        errs.append(f"{at}: malformed obs")
    if not kpi.VALUE_RE.match(r["value"] or ""):
        errs.append(f"{at}: value must be a plain decimal")
    if not URL_RE.match(r["source"] or ""):
        errs.append(f"{at}: source must be one http(s) URL")
    for k in ("published", "retrieved"):
        if not DAY_RE.match(r[k] or ""):
            errs.append(f"{at}: {k} must be YYYY-MM-DD")
    if r["published_basis"] not in BASES:
        errs.append(f"{at}: published_basis must be one of {sorted(BASES)}")
    if not errs:
        if day(r["published"]) > day(r["retrieved"]):
            errs.append(f"{at}: published after retrieved")
        if day(r["published"]) < kpi.obs_range(r["obs"])[0]:
            errs.append(f"{at}: published before the observed period began")
        if r["published_basis"] == "rule":
            lag = (reg or {}).get(r["metric"], {}).get("release_lag_days")
            if not lag:
                errs.append(f"{at}: published_basis=rule needs release_lag_days in the registry")
            else:
                want = min(kpi.obs_range(r["obs"])[1] + dt.timedelta(days=int(lag)), day(r["retrieved"]))
                if day(r["published"]) != want:
                    errs.append(f"{at}: rule-basis published must be {want} (obs end + {lag}d, capped at retrieved)")
    allowed = STAGED_VERIF if staged else OBS_VERIF
    if r["verification"] not in allowed:
        errs.append(f"{at}: verification must be one of {sorted(allowed)}")
    if not r["collector"]:
        errs.append(f"{at}: empty collector (provenance)")
    return errs


def check_section(section: str) -> tuple[list[str], list[str]]:
    import kpi
    errs, warns = [], []
    try:
        evs, obs, ass = events(section), observations(section), assessments(section)
    except ValueError as e:
        return [str(e)], []
    topics = valid_topics(section)
    reg, reg_errs = kpi.load_registry(section)
    if obs:
        errs += reg_errs
    ids = {}
    for e in evs:
        errs += check_event(e, section, topics)
        if e.get("id") in ids:
            errs.append(f"event {e['id']}: duplicate id")
        ids[e.get("id")] = e
        for m in e.get("metrics", []) or []:
            if reg is not None and m.get("metric") not in reg:
                errs.append(f"event {e['id']}: linked metric '{m.get('metric')}' not registered")
    seen_claim = {}
    for e in evs:
        for r in e.get("relates", []) or []:
            if r.get("id") not in ids:
                errs.append(f"event {e['id']}: relates to unknown event '{r.get('id')}'")
            elif r["id"] == e["id"]:
                errs.append(f"event {e['id']}: relates to itself")
        c = re.sub(r"\W+", " ", str(e.get("claim", "")).lower()).strip()
        if c in seen_claim:
            errs.append(f"event {e['id']}: same claim as {seen_claim[c]} (duplicate)")
        seen_claim[c] = e.get("id")
    warns += near_duplicates(evs)
    keys = set()
    for r in obs:
        errs += check_obs_row(r, reg)
        k = (r["metric"], r["obs"], r["published"], r["value"])
        if k in keys:
            errs.append(f"obs {r['metric']}@{r['obs']}: exact duplicate row (line {r['_line']})")
        keys.add(k)
    aids = set()
    for a in ass:
        errs += check_assessment(a, topics, ids)
        if a.get("id") in aids:
            errs.append(f"assessment {a.get('id')}: duplicate id")
        aids.add(a.get("id"))
    return errs, warns


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9.]+", text.lower()) if len(w) > 2}


def near_duplicates(evs: list[dict], threshold: float = 0.6, days: int = 7) -> list[str]:
    """Warn on likely duplicate events: claim word-overlap (Jaccard) >= threshold
    and dates within `days`, unless linked via relates."""
    import kpi
    out = []
    items = sorted(((date_end(str(e["date"])), e) for e in evs if DATE_RE.match(str(e.get("date", "")))),
                   key=lambda t: t[0])
    words = {e["id"]: _words(str(e.get("claim", ""))) for _, e in items}
    for i, (d1, a) in enumerate(items):
        for d2, b in items[i + 1:]:
            if (d2 - d1).days > days:
                break
            wa, wb = words[a["id"]], words[b["id"]]
            linked = {r.get("id") for r in (a.get("relates") or []) + (b.get("relates") or [])}
            na, nb = kpi.kpi_numbers(str(a.get("claim", ""))), kpi.kpi_numbers(str(b.get("claim", "")))
            if na and nb and na != nb:
                continue  # parallel claims with different figures (e.g. solar vs wind LCOE)
            if wa and wb and len(wa & wb) / len(wa | wb) >= threshold and not linked & {a["id"], b["id"]}:
                out.append(f"events {a['id']} / {b['id']}: near-identical claims — duplicate? (merge, or link with relates)")
    return out


# --- cutoffs --------------------------------------------------------------------------
def period_kind(period: str) -> str:
    for kind, rx in (("year", r"\d{4}"), ("half", r"\d{2}H[12]"), ("quarter", r"\d{4}-Q[1-4]"),
                     ("month", r"\d{4}-\d{2}"), ("week", r"\d{4}-W\d{2}")):
        if re.fullmatch(rx, period):
            return kind
    raise ValueError(f"unrecognized period '{period}'")


def period_start(period: str) -> dt.date:
    import kpi
    k = period_kind(period)
    end = kpi.period_as_of(period)
    if k == "year":
        return dt.date(end.year, 1, 1)
    if k == "half":
        return dt.date(end.year, end.month - 5, 1)
    if k == "quarter":
        return dt.date(end.year, end.month - 2, 1)
    if k == "month":
        return dt.date(end.year, end.month, 1)
    return end - dt.timedelta(days=6)


LAG = {"week": 2, "month": 7, "quarter": 14, "half": 14, "year": 14}


def cutoff(period: str) -> dt.date:
    import kpi
    return kpi.period_as_of(period) + dt.timedelta(days=LAG[period_kind(period)])


def prev_cutoff(period: str) -> dt.date:
    """Cutoff of the previous period of the same kind (its end is our start - 1 day)."""
    k = period_kind(period)
    prev_end = period_start(period) - dt.timedelta(days=1)
    return prev_end + dt.timedelta(days=LAG[k])


# --- as-of queries ----------------------------------------------------------------------
def known_at(rec: dict) -> dt.date:
    return day(rec["published"]) if "published" in rec else day(rec["made_at"])


def obs_as_of(section: str, when: dt.date) -> dict[tuple[str, str], dict]:
    """{(metric, obs): row} — latest-known row per observation as of `when`."""
    out: dict[tuple[str, str], dict] = {}
    for r in observations(section):
        if known_at(r) <= when:
            k = (r["metric"], r["obs"])
            if k not in out or (known_at(r), r["retrieved"]) >= (known_at(out[k]), out[k]["retrieved"]):
                out[k] = r
    return out


def latest_obs(table: dict, metric: str, when: dt.date | None = None) -> dict | None:
    import kpi
    rows = [r for (m, _), r in table.items() if m == metric
            and (when is None or kpi.obs_range(r["obs"])[1] <= when)]
    return max(rows, key=lambda r: (kpi.obs_range(r["obs"])[1], kpi.obs_range(r["obs"])[0])) if rows else None


def assessment_as_of(section: str, when: dt.date) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for a in assessments(section):
        if day(a["made_at"]) <= when:
            if a["target"] not in out or a["made_at"] >= out[a["target"]]["made_at"]:
                out[a["target"]] = a
    return out


# --- snapshot -----------------------------------------------------------------------------
def snapshot(period_dir: str, section: str, background_years: int = 2) -> dict:
    """Deterministic bulletin input: the ledger as of the period's cutoff."""
    import kpi
    period = os.path.basename(os.path.normpath(period_dir)).removeprefix("pilot-")
    cut, prev = cutoff(period), prev_cutoff(period)
    start = period_start(period)
    reg, _ = kpi.load_registry(section)
    reg = reg or {}
    evs = [e for e in events(section) if known_at(e) <= cut]
    by_id = {e["id"]: e for e in evs}
    new = [e for e in evs if known_at(e) > prev and e["verification"]["status"] != "legacy"]
    new_ids = {e["id"] for e in new}
    bg_from = dt.date(start.year - background_years, start.month, 1)
    background = [e for e in evs if e["id"] not in new_ids and e["significance"] >= 2
                  and date_end(e["date"]) >= bg_from]
    # lifecycle: pull in earlier events that new ones update/retract
    for e in new:
        for r in e.get("relates", []) or []:
            if r["id"] in by_id and r["id"] not in new_ids and by_id[r["id"]] not in background:
                background.append(by_id[r["id"]])
    now_t, prev_t = obs_as_of(section, cut), obs_as_of(section, prev)
    kpis = []
    for m, row in reg.items():
        if not kpi.required_active(row, cut):
            continue
        cur = latest_obs(now_t, m, cut)
        before = latest_obs(prev_t, m, prev)
        kpis.append({"metric": m, "unit": row["unit"], "definition": row["definition"],
                     "current": clean(cur) if cur else None,
                     "previous": clean(before) if before else None})
    other_obs = sorted({m for (m, _) in now_t} - {k["metric"] for k in kpis})
    ass_now, ass_prev = assessment_as_of(section, cut), assessment_as_of(section, prev)
    return {
        "section": section, "period": period, "period_start": str(start),
        "period_end": str(kpi.period_as_of(period)), "cutoff": str(cut), "previous_cutoff": str(prev),
        "rule": "records with known_at (published) <= cutoff; 'new' = known_at in (previous_cutoff, cutoff]",
        "new_events": [clean(e) for e in sorted(new, key=lambda e: (e["date"], e["id"]))],
        "background_events": [clean(e) for e in sorted(background, key=lambda e: (e["date"], e["id"]))],
        "kpi_headlines": kpis,
        "other_metrics": [{"metric": m, "unit": reg.get(m, {}).get("unit", ""),
                           "definition": reg.get(m, {}).get("definition", ""),
                           "latest": clean(latest_obs(now_t, m, cut) or {})} for m in other_obs],
        "assessments": {t: {"current": clean(a), "previous": clean(ass_prev[t]) if t in ass_prev else None}
                        for t, a in sorted(ass_now.items())},
    }


def snapshot_text(snap: dict) -> str:
    """All claim/value text of a snapshot (for number traceability)."""
    return json.dumps(snap, ensure_ascii=False)


def snapshot_urls(snap: dict) -> set[str]:
    urls = set()
    for e in snap["new_events"] + snap["background_events"]:
        urls |= {s["url"] for s in e["sources"]}
    for k in snap["kpi_headlines"]:
        for r in (k["current"], k["previous"]):
            if r:
                urls.add(r["source"])
    for o in snap["other_metrics"]:
        if o["latest"]:
            urls.add(o["latest"]["source"])
    return urls


# --- merge -------------------------------------------------------------------------------
def lint(section: str, ev_file: str | None, obs_file: str | None, allow_legacy: bool = False,
         ass_file: str | None = None) -> list[str]:
    """Validate a STAGED file before merge: schema, topics, ids unique vs file and
    ledger, relates resolvable (file ∪ ledger), no duplicate claims."""
    import kpi
    errs: list[str] = []
    topics = valid_topics(section)
    existing = {e["id"]: e for e in events(section)}
    staged = load_jsonl(ev_file) if ev_file else []
    seen: set[str] = set()
    claims = {re.sub(r"\W+", " ", str(e.get("claim", "")).lower()).strip(): e["id"] for e in existing.values()}
    for e in staged:
        es = check_event(e, section, topics, staged=True)
        st = e.get("verification", {}).get("status") if isinstance(e.get("verification"), dict) else None
        if allow_legacy and st == "legacy":
            es = [x for x in es if "verification.status" not in x]
        errs += es
        if e.get("id") in seen or e.get("id") in existing:
            errs.append(f"event {e.get('id')}: duplicate id (in file or already in ledger)")
        seen.add(e.get("id"))
        c = re.sub(r"\W+", " ", str(e.get("claim", "")).lower()).strip()
        if c in claims:
            errs.append(f"event {e.get('id')}: same claim as {claims[c]}")
        claims[c] = e.get("id")
    for e in staged:
        for r in e.get("relates", []) or []:
            if isinstance(r, dict) and r.get("id") not in seen | set(existing):
                errs.append(f"event {e.get('id')}: relates to unknown event '{r.get('id')}'")
    if obs_file:
        reg, reg_errs = kpi.load_registry(section)
        errs += reg_errs
        for r in load_obs(obs_file):
            errs += check_obs_row(r, reg, staged=True)
    if ass_file:
        all_ev = dict(existing) | {e["id"]: e for e in staged if "id" in e}
        have = {a["id"] for a in assessments(section)}
        for a in load_jsonl(ass_file):
            errs += check_assessment(a, topics, all_ev)
            if a.get("id") in have:
                errs.append(f"assessment {a.get('id')}: duplicate id")
            have.add(a.get("id"))
    return errs


def merge(section: str, ev_file: str | None, obs_file: str | None,
          allow_legacy: bool = False, ass_file: str | None = None) -> tuple[list[str], dict]:
    """Admit verified/corrected/collector staged records; reject the rest to
    ledger/rejected/. All-or-nothing: any schema error aborts without writing."""
    import kpi
    errs: list[str] = []
    stats = {"events_in": 0, "events_rejected": 0, "obs_in": 0, "obs_rejected": 0, "obs_dup": 0}
    topics = valid_topics(section)
    staged_ev = load_jsonl(ev_file) if ev_file else []
    staged_obs = load_obs(obs_file) if obs_file else []
    reg, reg_errs = kpi.load_registry(section)
    existing = {e["id"]: e for e in events(section)}
    admit_ev, reject_ev = [], []
    for e in staged_ev:
        es = check_event(e, section, topics, staged=True)
        if allow_legacy and e.get("verification", {}).get("status") == "legacy":
            es = [x for x in es if "verification.status" not in x]
        if es:
            errs += es
            continue
        st = e["verification"]["status"]
        if st in ("verified", "corrected") or (allow_legacy and st == "legacy"):
            if e["id"] in existing:
                errs.append(f"event {e['id']}: id already in the ledger (to add a source or status change, stage a NEW event with relates)")
            admit_ev.append(e)
        else:
            reject_ev.append(e)
    ids = set(existing) | {e["id"] for e in admit_ev}
    for e in admit_ev:
        for r in e.get("relates", []) or []:
            if r["id"] not in ids:
                errs.append(f"event {e['id']}: relates to unknown event '{r['id']}'")
    admit_obs, reject_obs = [], []
    have = {(r["metric"], r["obs"], r["value"]) for r in observations(section)}
    if staged_obs:
        errs += reg_errs
    for r in staged_obs:
        es = check_obs_row(r, reg, staged=True)
        if es:
            errs += es
            continue
        if r["verification"] in ("verified", "corrected", "collector"):
            if (r["metric"], r["obs"], r["value"]) in have:
                stats["obs_dup"] += 1  # unchanged re-observation: nothing new to record
                continue
            have.add((r["metric"], r["obs"], r["value"]))
            admit_obs.append(r)
        else:
            reject_obs.append(r)
    staged_ass = load_jsonl(ass_file) if ass_file else []
    all_ev = existing | {e["id"]: e for e in admit_ev}
    have_ass = {a["id"] for a in assessments(section)}
    for a in staged_ass:
        errs += check_assessment(a, topics, all_ev)
        if a.get("id") in have_ass:
            errs.append(f"assessment {a.get('id')}: duplicate id")
        have_ass.add(a.get("id"))
    if errs:
        return errs, stats
    os.makedirs(os.path.dirname(path("events", section)), exist_ok=True)
    if staged_ass:
        os.makedirs(os.path.dirname(path("assessments", section)), exist_ok=True)
        with open(path("assessments", section), "a", encoding="utf-8") as f:
            for a in staged_ass:
                f.write(json.dumps(clean(a), ensure_ascii=False) + "\n")
    stats["assessments_in"] = len(staged_ass)
    if admit_ev:
        with open(path("events", section), "a", encoding="utf-8") as f:
            for e in sorted(admit_ev, key=lambda e: e["id"]):
                f.write(json.dumps(clean(e), ensure_ascii=False) + "\n")
    rejected = [clean(e) | {"_kind": "event"} for e in reject_ev] + \
               [clean(r) | {"_kind": "observation"} for r in reject_obs]
    if rejected:
        os.makedirs(os.path.dirname(path("rejected", section)), exist_ok=True)
        with open(path("rejected", section), "a", encoding="utf-8") as f:
            for rec in rejected:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if admit_obs:
        p = path("observations", section)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        new_file = not os.path.exists(p)
        with open(p, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=OBS_COLUMNS, lineterminator="\n", extrasaction="ignore")
            if new_file:
                w.writeheader()
            w.writerows(admit_obs)
    stats.update(events_in=len(admit_ev), events_rejected=len(reject_ev),
                 obs_in=len(admit_obs), obs_rejected=len(reject_obs))
    return [], stats


# --- CLI ---------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("sections", nargs="*")
    t = sub.add_parser("topics"); t.add_argument("section", choices=SECTIONS)
    r = sub.add_parser("recent"); r.add_argument("section", choices=SECTIONS); r.add_argument("--limit", type=int, default=150)
    m = sub.add_parser("merge"); m.add_argument("section", choices=SECTIONS)
    m.add_argument("--events"); m.add_argument("--obs")
    m.add_argument("--legacy", action="store_true", help="admit verification=legacy (one-off report conversions)")
    m.add_argument("--assessments")
    li = sub.add_parser("lint"); li.add_argument("section", choices=SECTIONS)
    li.add_argument("--events"); li.add_argument("--obs"); li.add_argument("--legacy", action="store_true")
    li.add_argument("--assessments")
    cu = sub.add_parser("cutoff"); cu.add_argument("period")
    s = sub.add_parser("snapshot"); s.add_argument("period_dir"); s.add_argument("section", choices=SECTIONS)
    a = ap.parse_args()
    try:
        if a.cmd == "check":
            n_e = 0
            for sec in a.sections or SECTIONS:
                errs, warns = check_section(sec)
                for w in warns:
                    print(f"  WARN  [{sec}] {w}")
                for e in errs:
                    print(f"  ERROR [{sec}] {e}")
                n_e += len(errs)
            print(f"\nledger check: {n_e} error(s)")
            return 1 if n_e else 0
        if a.cmd == "topics":
            print("\n".join(sorted(valid_topics(a.section))))
        elif a.cmd == "recent":
            evs = sorted(events(a.section), key=lambda e: (e["date"], e["id"]))[-a.limit:]
            for e in evs:
                print(f"{e['id']} [{e['kind']}; {','.join(e['topics'])}; {e['verification']['status']}] {e['claim']}")
            if not evs:
                print(f"(no events yet for {a.section})")
        elif a.cmd == "merge":
            errs, stats = merge(a.section, a.events, a.obs, a.legacy, a.assessments)
            for e in errs:
                print(f"  ERROR {e}")
            print(f"merge {a.section}: {'ABORTED' if errs else 'ok'} {stats}")
            return 1 if errs else 0
        elif a.cmd == "lint":
            errs = lint(a.section, a.events, a.obs, a.legacy, a.assessments)
            for e in errs:
                print(f"  ERROR {e}")
            print(f"lint {a.section}: {len(errs)} error(s)")
            return 1 if errs else 0
        elif a.cmd == "cutoff":
            print(f"cutoff {cutoff(a.period)} previous_cutoff {prev_cutoff(a.period)} "
                  f"period {period_start(a.period)}..{__import__('kpi').period_as_of(a.period)}")
        elif a.cmd == "snapshot":
            snap = snapshot(a.period_dir, a.section)
            out = os.path.join(a.period_dir, "snapshot", f"{a.section}.json")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(snap, f, ensure_ascii=False, indent=1)
                f.write("\n")
            print(f"wrote {out}: {len(snap['new_events'])} new, {len(snap['background_events'])} background events, "
                  f"{len(snap['kpi_headlines'])} KPI headlines, cutoff {snap['cutoff']}")
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
