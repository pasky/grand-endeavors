#!/usr/bin/env python3
"""Grand Endeavors ledger: the canonical, append-only record of what is known
and when it became known. See DESIGN.md (§2 time semantics, §3 schemas).

COMMANDS
  ledger.py check [section ...]                    validate ledger files (all sections by default)
  ledger.py topics <section>                       valid topic tags (from README.md)
  ledger.py recent <section> [--limit N]           compact event list (for intake dedup prompts)
  ledger.py lint <section> [--events F..] [--obs F..] [--assessments F..] [--final]
                                                   validate staged files as if merged
  ledger.py merge <section> [--events F..] [--obs F..] [--assessments F..]
                                                   validate the whole proposed state, then merge
                                                   admitted records atomically (idempotent on replay;
                                                   rejected ones -> ledger/rejected/)
  ledger.py stale <section> --until D              assessment targets with newer evidence (+ next ids)
  ledger.py items <section>                        gather watch list from README
  ledger.py state <section> [--get-item T | --record JSON]  per-item gather watermarks
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

ROOT = os.path.dirname(os.path.abspath(__file__))   # the mechanism (code, README, STATUS)
# The data (ledger, registry, period bulletins) is a SEPARATE git repository:
# $GE_DATA, default <mechanism>/data (gitignored here). See DESIGN.md §7.
DATA = os.environ.get("GE_DATA") or os.path.join(ROOT, "data")
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
ASSESS_STATUS = {"green", "yellow", "red", "achieved", "unknown"}
# STATUS.md (rubric v1): verdict words bound to each status
VERDICTS = {"green": ("Ahead", "On track"), "yellow": ("Behind pace", "Progressing"),
            "red": ("Off track", "Stalled", "Regressing", "Distant", "Blocked"), "achieved": ("Achieved",),
            "unknown": ("Unassessed",)}
BASIS_UNKNOWN = {"rule", "reason", "prev", "change_note"}
BASIS_KPI = {"rule", "assessed_quantity", "window", "benchmark", "benchmark_source",
             "transients_discounted", "data_as_of", "prev", "change_note"}
BASIS_MILESTONE = {"rule", "eta", "path", "blockers", "prev", "change_note"}


def kpi_assessment_spec(section: str) -> dict | None:
    """metrics/kpi-assessment.csv row for a section (STATUS.md: fixed per KPI)."""
    p = os.path.join(DATA, "metrics", "kpi-assessment.csv")
    if not os.path.exists(p):
        return None
    with open(p, newline="", encoding="utf-8") as f:
        return next((r for r in csv.DictReader(f) if r["section"] == section), None)
EVENT_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_RE = re.compile(r"^https?://\S+$")


def path(kind: str, section: str) -> str:
    ext = "csv" if kind == "observations" else ("json" if kind == "state" else "jsonl")
    return os.path.join(DATA, "ledger", kind, f"{section}.{ext}")


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


def readme_items(section: str) -> list[tuple[str, str, str]]:
    """Gather watch list: (topic, name, description) for the KPI, every milestone
    and challenge in README, plus the open-ended 'beyond' sweep."""
    text = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == _HEADINGS[section])
    level = len(_HEADINGS[section].split()[0])
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^#{1,%d} " % level, lines[i])), len(lines))
    block = lines[start:end]
    kpi_line = next((ln for ln in block if ln.startswith("**KPI:**")), "")
    intro = " ".join(ln for ln in block[1:] if ln.strip() and not ln.startswith(("*", "#")))[:600]
    items = [("kpi", "KPI", kpi_line.replace("**KPI:**", "").strip() or f"The section's key indicators. {intro}")]
    for kind, topic in (("milestones", "milestone"), ("challenges", "challenge")):
        for slug, name in readme_topics(section)[kind]:
            desc = next((re.sub(r"^\*\s+\*\*.+?\*\*:?\s*", "", ln).strip()
                         for ln in block if re.match(r"^\*\s+\*\*", ln) and slugify(
                             re.match(r"^\*\s+\*\*(.+?)\*\*", ln)[1].rstrip(":").strip().strip('"“”')) == slug), "")
            items.append((f"{topic}:{slug}", name, desc))
    items.append(("beyond", "Beyond the Framework",
                  "Significant developments for this endeavor that fit no milestone or challenge: "
                  "surprising breakthroughs, setbacks, policy shifts, new players, important data releases."))
    return items


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
                    raise ValueError(f"{os.path.relpath(p, DATA)}:{i}: bad JSON ({e})")
                rec["_line"] = i
                out.append(rec)
    return out


def load_obs(p: str) -> list[dict]:
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if r.fieldnames != OBS_COLUMNS:
            raise ValueError(f"{os.path.relpath(p, DATA)}: header must be exactly {','.join(OBS_COLUMNS)}")
        rows = [dict(row, _line=i) for i, row in enumerate(r, 2)]
    for row in rows:
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f"{os.path.relpath(p, DATA)}:{row['_line']}: wrong number of fields")
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
def _valid_day(s) -> bool:
    try:
        return bool(DAY_RE.match(str(s))) and bool(day(str(s)))
    except ValueError:
        return False


def _valid_date(s) -> bool:
    try:
        return bool(DATE_RE.match(str(s))) and bool(date_end(str(s)))
    except ValueError:
        return False


def check_event(e: dict, section: str, topics: set[str], staged: bool = False) -> list[str]:
    at = f"event {e.get('id', '?')}"
    errs = []
    need = ["id", "date", "published", "published_basis", "retrieved", "kind", "topics",
            "claim", "sources", "significance", "verification", "collector"]
    errs += [f"{at}: missing '{k}'" for k in need if k not in e]
    if errs:
        return errs
    extra = set(e) - set(need) - {"metrics", "relates", "supersedes", "withdrawn", "note", "_line"}
    if extra:
        errs.append(f"{at}: unknown field(s) {sorted(extra)}")
    if not EVENT_ID_RE.match(str(e["id"])):
        errs.append(f"{at}: id must be YYYY-MM-DD-slug")
    if not _valid_date(e["date"]):
        errs.append(f"{at}: bad date '{e['date']}' (YYYY, YYYY-MM or YYYY-MM-DD, a real date)")
    elif not str(e["id"]).startswith(str(e["date"])):
        errs.append(f"{at}: id must start with the event date")
    elif not _valid_day(str(e["id"])[:10]):
        errs.append(f"{at}: id date prefix is not a real date")
    for k in ("published", "retrieved"):
        if not _valid_day(e[k]):
            errs.append(f"{at}: {k} must be a real YYYY-MM-DD date")
    if e["published_basis"] not in BASES:  # 'rule' = scheduled data release, estimated date
        errs.append(f"{at}: published_basis must be one of {sorted(BASES)}")
    if not errs:
        if day(e["published"]) > day(e["retrieved"]):
            errs.append(f"{at}: published after retrieved")
        if e["published_basis"] == "seen" and e["published"] != e["retrieved"]:
            errs.append(f"{at}: published_basis=seen means published = retrieved (first seen)")
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
    # staged mode also accepts ledger statuses (lint validates staged + existing
    # records together); admission is decided separately in prepare()
    allowed = (STAGED_VERIF | EV_VERIF) if staged else EV_VERIF
    if not isinstance(v, dict) or v.get("status") not in allowed:
        errs.append(f"{at}: verification.status must be one of {sorted(allowed)}")
    elif v["status"] != "legacy" and not (v.get("by") and v.get("at")):
        errs.append(f"{at}: verification needs 'by' and 'at'")
    for r in e.get("relates", []) or []:
        if not isinstance(r, dict) or r.get("rel") not in RELS or not r.get("id"):
            errs.append(f"{at}: relates entries need id + rel in {sorted(RELS)}")
    sup = e.get("supersedes", [])
    if not isinstance(sup, list) or not all(isinstance(x, str) for x in sup):
        errs.append(f"{at}: supersedes must be a list of event ids")
    if "withdrawn" in e and (e["withdrawn"] is not True or e["kind"] != "retraction" or not sup):
        errs.append(f"{at}: a withdrawal tombstone needs withdrawn=true, kind 'retraction' and supersedes")
    for m in e.get("metrics", []) or []:
        if not isinstance(m, dict) or not {"metric", "obs", "value"} <= set(m):
            errs.append(f"{at}: metrics entries need metric, obs, value")
    return errs


def check_assessment(a: dict, topics: set[str], evs: dict[str, dict]) -> list[str]:
    """made_at = the as-of date of the evidence considered (not wall-clock), so
    every evidence event must be known by then; `by` records the actual run."""
    at = f"assessment {a.get('id')}"
    need = ("id", "target", "status", "label", "made_at", "rationale", "evidence", "by")
    errs = [f"{at}: missing '{k}'" for k in need if k not in a]
    if errs:
        return errs
    extra = set(a) - set(need) - {"evidence_digest", "rubric", "basis", "rubric_correction", "_line"}
    if extra:
        errs.append(f"{at}: unknown field(s) {sorted(extra)}")
    if a["status"] not in ASSESS_STATUS:
        errs.append(f"{at}: status must be one of {sorted(ASSESS_STATUS)}")
    if a["status"] == "achieved":
        if not str(a["target"]).startswith("milestone:"):
            errs.append(f"{at}: 'achieved' is for milestones only")
        elif not any(evs.get(e, {}).get("kind") == "achievement"
                     and evs.get(e, {}).get("verification", {}).get("status") in ("verified", "corrected")
                     for e in a.get("evidence") or []):
            errs.append(f"{at}: 'achieved' needs a verified evidence event of kind 'achievement'")
    if "rubric" in a:  # STATUS.md rubric v1 (older records have no rubric field)
        if a["rubric"] != "v1":
            errs.append(f"{at}: unknown rubric '{a['rubric']}'")
        else:
            words = VERDICTS.get(a["status"], ())
            if not any(str(a["label"]).startswith(w + ":") for w in words):
                errs.append(f"{at}: label must start with a verdict bound to '{a['status']}': "
                            + ", ".join(f"'{w}:'" for w in words))
            if len(str(a["label"])) > 100:
                errs.append(f"{at}: label longer than 100 chars")
            want = BASIS_UNKNOWN if a["status"] == "unknown" else BASIS_KPI if a["target"] == "kpi" else BASIS_MILESTONE
            basis = a.get("basis")
            if not isinstance(basis, dict) or want - set(basis):
                errs.append(f"{at}: basis must be an object with {sorted(want)}"
                            + (f" (missing {sorted(want - set(basis))})" if isinstance(basis, dict) else ""))
            if a.get("rubric_correction") not in (None, "v1"):
                errs.append(f"{at}: rubric_correction must be 'v1'")
    if a["target"] not in topics - {"beyond"}:
        errs.append(f"{at}: unknown target '{a['target']}'")
    if not _valid_day(a["made_at"]):
        return errs + [f"{at}: made_at must be a real YYYY-MM-DD date"]
    if not a["evidence"] and a["status"] != "unknown":
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
        if not _valid_day(r[k]):
            errs.append(f"{at}: {k} must be a real YYYY-MM-DD date")
    if r["published_basis"] not in BASES:
        errs.append(f"{at}: published_basis must be one of {sorted(BASES)}")
    if not errs:
        if day(r["published"]) > day(r["retrieved"]):
            errs.append(f"{at}: published after retrieved")
        if day(r["published"]) < kpi.obs_range(r["obs"])[0]:
            errs.append(f"{at}: published before the observed period began")
        if r["published_basis"] == "seen" and r["published"] != r["retrieved"]:
            errs.append(f"{at}: published_basis=seen means published = retrieved (first seen)")
        if r["published_basis"] == "rule":
            lag = (reg or {}).get(r["metric"], {}).get("release_lag_days")
            if not lag:
                errs.append(f"{at}: published_basis=rule needs release_lag_days in the registry")
            else:
                want = min(kpi.obs_range(r["obs"])[1] + dt.timedelta(days=int(lag)), day(r["retrieved"]))
                if day(r["published"]) != want:
                    errs.append(f"{at}: rule-basis published must be {want} (obs end + {lag}d, capped at retrieved)")
    allowed = (STAGED_VERIF | OBS_VERIF) if staged else OBS_VERIF
    if r["verification"] not in allowed:
        errs.append(f"{at}: verification must be one of {sorted(allowed)}")
    if not r["collector"]:
        errs.append(f"{at}: empty collector (provenance)")
    return errs


def _claim_key(e: dict) -> str:
    return re.sub(r"\W+", " ", str(e.get("claim", "")).lower()).strip()


def validate_state(section: str, evs: list[dict], obs: list[dict], ass: list[dict],
                   staged_statuses: bool = False) -> tuple[list[str], list[str]]:
    """THE validation path for a (proposed) ledger state; used by check, lint and merge."""
    import kpi
    errs, warns = [], []
    topics = valid_topics(section)
    reg, reg_errs = kpi.load_registry(section)
    if obs or any(e.get("metrics") for e in evs):
        errs += reg_errs
    ids: dict[str, dict] = {}
    for e in evs:
        es = check_event(e, section, topics, staged=staged_statuses)
        errs += es
        if e.get("id") in ids:
            errs.append(f"event {e.get('id')}: duplicate id")
        ids[e.get("id")] = e
        if es:
            continue
        for m in e.get("metrics", []) or []:
            if reg is not None and m.get("metric") not in reg:
                errs.append(f"event {e['id']}: linked metric '{m.get('metric')}' not registered")
    superseded_by: dict[str, str] = {}
    parent = {i: i for i in ids}  # union-find over supersedes edges = replacement lineages

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for e in evs:
        eid = e.get("id")
        for r in e.get("relates", []) or []:
            if isinstance(r, dict) and r.get("id") not in ids:
                errs.append(f"event {eid}: relates to unknown event '{r.get('id')}'")
            elif isinstance(r, dict) and r.get("id") == eid:
                errs.append(f"event {eid}: relates to itself")
        for s in e.get("supersedes", []) or []:
            if s not in ids:
                errs.append(f"event {eid}: supersedes unknown event '{s}'")
            elif s == eid:
                errs.append(f"event {eid}: supersedes itself")
            elif s in superseded_by:
                errs.append(f"event {eid}: '{s}' is already superseded by {superseded_by[s]}")
            else:
                superseded_by[s] = eid
                if eid in parent:
                    parent[root(s)] = root(eid)
    # cycles: following superseded_by from any record must terminate
    for start in superseded_by:
        seen, x = set(), start
        while x in superseded_by:
            if x in seen:
                errs.append(f"event {start}: supersedes cycle")
                break
            seen.add(x)
            x = superseded_by[x]
    seen_claim: dict[str, str] = {}
    for e in sorted(evs, key=lambda e: str(e.get("id"))):  # order-independent
        eid, c = e.get("id"), _claim_key(e)
        other = seen_claim.get(c)
        if other and eid in parent and other in parent and root(other) != root(eid):
            errs.append(f"event {eid}: same claim as {other} (duplicate; to correct or add a source, use supersedes)")
        seen_claim.setdefault(c, eid)
    warns += near_duplicates([e for e in evs if e.get("id") not in superseded_by])
    keys = set()
    for r in obs:
        errs += check_obs_row(r, reg, staged=staged_statuses)
        k = (r.get("metric"), r.get("obs"), r.get("published"), r.get("value"), r.get("verification"))
        if k in keys:
            errs.append(f"obs {r.get('metric')}@{r.get('obs')}: exact duplicate row (line {r.get('_line')})")
        keys.add(k)
    aids = set()
    for a in ass:
        errs += check_assessment(a, topics, ids)
        if a.get("id") in aids:
            errs.append(f"assessment {a.get('id')}: duplicate id")
        aids.add(a.get("id"))
    errs += check_hysteresis(section, ass, ids, obs)
    return errs, warns


def check_hysteresis(section: str, ass: list[dict], evs: dict[str, dict], obs: list[dict] | None = None) -> list[str]:
    """STATUS.md rules 1 and 4 for rubric-v1 records: a status change needs evidence
    published after the previous assessment, or a once-per-target rubric correction.
    KPI assessments need the section's fixed spec in metrics/kpi-assessment.csv."""
    errs = []
    by_target: dict[str, list[dict]] = {}
    for a in sorted((a for a in ass if _valid_day(a.get("made_at", ""))), key=lambda a: a["made_at"]):  # stable: file order on ties
        by_target.setdefault(a.get("target"), []).append(a)
    for target, recs in by_target.items():
        for prev, a in zip(recs, recs[1:]):
            if a.get("rubric") != "v1":
                continue
            if a.get("rubric_correction") == "v1":
                # a correction re-judges a PRE-rubric record; a v1 record is never "corrected"
                if prev.get("rubric") == "v1":
                    errs.append(f"assessment {a['id']}: rubric_correction of a record already under rubric v1 "
                                "(needs newer evidence instead; STATUS.md rule 4)")
                continue
            if "unknown" in (a["status"], prev["status"]):
                continue  # 'unknown' is the absence of a judgment, not a status flip
            newer_obs = False
            if target == "kpi" and obs:  # a KPI moves on observations of its assessed metric
                spec = kpi_assessment_spec(section) or {}
                newer_obs = any(r["metric"] == spec.get("assessed_metric") and tier(r)
                                and day(prev["made_at"]) < known_at(r) <= day(a["made_at"]) for r in obs)
            if a["status"] != prev["status"] and not newer_obs and not any(
                    e in evs and known_at(evs[e]) > day(prev["made_at"]) for e in a.get("evidence") or []):
                errs.append(f"assessment {a['id']}: status change {prev['status']}->{a['status']} without evidence "
                            f"published after {prev['made_at']} (STATUS.md hysteresis rule 1; a pre-rubric prev "
                            "may be re-judged with rubric_correction v1)")
        if target == "kpi" and any(a.get("rubric") == "v1" for a in recs) and not kpi_assessment_spec(section):
            errs.append(f"assessment of {section} kpi under rubric v1, but metrics/kpi-assessment.csv has no row for it")
    return errs


def check_section(section: str) -> tuple[list[str], list[str]]:
    try:
        return validate_state(section, events(section), observations(section), assessments(section))
    except ValueError as e:
        return [str(e)], []


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9.]+", text.lower()) if len(w) > 2}


def near_duplicates(evs: list[dict], threshold: float = 0.6, days: int = 7) -> list[str]:
    """Warn on likely duplicate events: claim word-overlap (Jaccard) >= threshold
    and dates within `days`, unless linked via relates/supersedes or stating
    different figures."""
    import kpi
    out = []
    items = sorted(((date_end(str(e["date"])), e) for e in evs if _valid_date(e.get("date", ""))),
                   key=lambda t: t[0])
    words = {e["id"]: _words(str(e.get("claim", ""))) for _, e in items}
    for i, (d1, a) in enumerate(items):
        for d2, b in items[i + 1:]:
            if (d2 - d1).days > days:
                break
            wa, wb = words[a["id"]], words[b["id"]]
            linked = {r.get("id") for r in (a.get("relates") or []) + (b.get("relates") or [])} \
                | set(a.get("supersedes") or []) | set(b.get("supersedes") or [])
            na, nb = kpi.kpi_numbers(str(a.get("claim", ""))), kpi.kpi_numbers(str(b.get("claim", "")))
            if na and nb and na != nb:
                continue  # parallel claims with different figures (e.g. solar vs wind LCOE)
            if wa and wb and len(wa & wb) / len(wa | wb) >= threshold and not linked & {a["id"], b["id"]}:
                out.append(f"events {a['id']} / {b['id']}: near-identical claims — duplicate? (supersede, or link with relates)")
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


def tier(r: dict) -> int:
    """Observation precedence: any non-legacy row outranks a legacy (report-
    extracted) one, whatever their publication dates (legacy migration dates are
    not source revisions)."""
    return 0 if r.get("verification") == "legacy" else 1


def _rank(r: dict) -> tuple:
    return (tier(r), known_at(r), r["retrieved"])


def obs_as_of(section: str, when: dt.date | None = None, rows: list[dict] | None = None) -> dict[tuple[str, str], dict]:
    """{(metric, obs): effective row} as of `when` (None = everything): among rows
    known by then, the highest-ranked (non-legacy first, then latest known)."""
    out: dict[tuple[str, str], dict] = {}
    for r in observations(section) if rows is None else rows:
        if when is None or known_at(r) <= when:
            k = (r["metric"], r["obs"])
            if k not in out or _rank(r) >= _rank(out[k]):
                out[k] = r
    return out


def latest_obs(table: dict, metric: str, when: dt.date | None = None) -> dict | None:
    import kpi
    rows = [r for (m, _), r in table.items() if m == metric
            and (when is None or kpi.obs_range(r["obs"])[1] <= when)]
    return max(rows, key=lambda r: (kpi.obs_range(r["obs"])[1], kpi.obs_range(r["obs"])[0])) if rows else None


def effective_events(evs: list[dict], when: dt.date | None = None) -> list[dict]:
    """Events known by `when`, minus those superseded by a record also known by then,
    minus withdrawal tombstones (withdrawn=true: the superseded record is simply gone)."""
    known = [e for e in evs if when is None or known_at(e) <= when]
    gone = {s for e in known for s in (e.get("supersedes") or [])}
    return [e for e in known if e["id"] not in gone and not e.get("withdrawn")]


def assessment_as_of(section: str, when: dt.date) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for a in assessments(section):
        if day(a["made_at"]) <= when:
            if a["target"] not in out or a["made_at"] >= out[a["target"]]["made_at"]:  # ties: later appended wins
                out[a["target"]] = a
    return out


def evidence_digest(section: str, target: str, when: dt.date) -> str:
    """Fingerprint of the verified evidence available for `target` as of `when`:
    effective non-legacy events tagged with it (ids, so replacements count), and
    for the KPI the effective non-legacy values of the required metrics. Stored on
    assessments at merge time; a different current digest means new or late-
    discovered evidence, whatever its publication date."""
    import hashlib
    import kpi
    items = sorted(e["id"] for e in effective_events(events(section), when)
                   if target in e["topics"] and e["verification"]["status"] != "legacy")
    if target == "kpi":
        reg = kpi.load_registry(section)[0] or {}
        req = {m for m, row in reg.items() if kpi.required_active(row, when)}
        items += sorted(f"{m}@{o}={r['value']}" for (m, o), r in obs_as_of(section, when).items()
                        if m in req and tier(r))
    return hashlib.sha1("\n".join(items).encode()).hexdigest()[:16]


def stale_targets(section: str, until: dt.date, force: bool = False) -> list[tuple[str, str]]:
    """Assessment targets (kpi + milestones) needing a (re)assessment as of `until`:
    never assessed, or their evidence digest changed since the latest assessment
    (assessments without a digest: evidence published after made_at). Returns
    [(target, next free assessment id)]."""
    valid = sorted(t for t in valid_topics(section) if t == "kpi" or t.startswith("milestone:"))
    current = assessment_as_of(section, until)
    ids = {a["id"] for a in assessments(section)}
    out = []
    for t in valid:
        a = current.get(t)
        if a is None:
            newer = True
        elif a.get("evidence_digest"):
            newer = a["evidence_digest"] != evidence_digest(section, t, until)
        else:  # older records: publication-date rule
            since = day(a["made_at"])
            newer = any(t in e["topics"] and known_at(e) > since
                        for e in effective_events(events(section), until) if e["verification"]["status"] != "legacy")
            if t == "kpi" and not newer:
                import kpi
                reg = kpi.load_registry(section)[0] or {}
                req = {m for m, row in reg.items() if kpi.required_active(row, until)}
                newer = any(r["metric"] in req and tier(r) and since < known_at(r) <= until for r in observations(section))
        if newer or force:
            base = f"{until}-{t.replace(':', '-')}"
            aid, n = base, 1
            while aid in ids:
                n += 1
                aid = f"{base}-{n}"
            out.append((t, aid))
    return out


def change_text(cur: str, before: str) -> str:
    nd = max(len(v.split(".")[1]) if "." in v else 0 for v in (cur, before))
    return f"{float(cur) - float(before):+.{nd}f}"


def compare(cur: dict, before: dict) -> dict:
    """Change cur vs before, with comparability safeguards (used by snapshots and the explorer):
    not comparable across observation granularities (kpi.obs_kind), across
    different calendar months (seasonal cycle not removed), or for the same obs
    (a source revision is not a change over time)."""
    same_obs = cur["obs"] == before["obs"]
    seasonal = len(cur["obs"]) == 7 and len(before["obs"]) == 7 and cur["obs"][5:] != before["obs"][5:]
    import kpi
    other_kind = kpi.obs_kind(cur["obs"]) != kpi.obs_kind(before["obs"])
    return {"value": change_text(cur["value"], before["value"]), "from_obs": before["obs"], "to_obs": cur["obs"],
            "comparable": not (same_obs or seasonal or other_kind),
            "caveat": ("same observation, unchanged: no new data" if same_obs
                       and float(cur["value"]) == float(before["value"]) else
                       "same observation revised by the source" if same_obs else
                       "different calendar month: seasonal cycle not removed" if seasonal else
                       "different observation granularity" if other_kind else "")}


def year_ago(table: dict, cur: dict) -> dict | None:
    """Like-for-like change for a monthly obs: the same month a year earlier."""
    if len(cur["obs"]) != 7:
        return None
    ya = table.get((cur["metric"], f"{int(cur['obs'][:4]) - 1}{cur['obs'][4:]}"))
    return ya and {"obs": ya["obs"], "value": ya["value"], "change": change_text(cur["value"], ya["value"])}


# --- snapshot -----------------------------------------------------------------------------
SERIES_YEARS = 15  # frozen chart history per snapshot (bounds weekly snapshot size in git)

# background context per bulletin kind: (years back, minimum significance); lifecycle
# predecessors and assessment evidence are always included on top
BACKGROUND = {"week": (1, 3), "month": (1, 2), "quarter": (2, 2), "half": (2, 2), "year": (2, 2)}


def snapshot(period_dir: str, section: str) -> dict:
    """Deterministic, SELF-CONTAINED bulletin input: the ledger as of the period's
    cutoff, including chart series and the README framework, so drafting and
    validation need no live state."""
    import kpi
    period = os.path.basename(os.path.normpath(period_dir)).removeprefix("pilot-")
    cut, prev = cutoff(period), prev_cutoff(period)
    start, end = period_start(period), kpi.period_as_of(period)
    prev_end = start - dt.timedelta(days=1)
    reg, _ = kpi.load_registry(section)
    reg = reg or {}
    all_known = [e for e in events(section) if known_at(e) <= cut]
    evs = effective_events(all_known)
    by_id = {e["id"]: e for e in evs}
    succ = {s: e["id"] for e in all_known for s in (e.get("supersedes") or [])}
    audit_by_id = {e["id"]: (e | {"superseded_by": succ[e["id"]]} if e["id"] in succ else e) for e in all_known}
    new = [e for e in evs if known_at(e) > prev and e["verification"]["status"] != "legacy"]
    new_ids = {e["id"] for e in new}
    years, min_sig = BACKGROUND[period_kind(period)]
    bg_from = dt.date(start.year - years, start.month, 1)
    background = [e for e in evs if e["id"] not in new_ids and e["significance"] >= min_sig
                  and date_end(e["date"]) >= bg_from]
    have = new_ids | {e["id"] for e in background}
    # lifecycle: earlier events that new ones update/retract
    for e in new:
        for r in e.get("relates", []) or []:
            if r["id"] in by_id and r["id"] not in have:
                background.append(by_id[r["id"]]); have.add(r["id"])
    # evidence cited by the current/previous assessments must be visible too
    ass_now, ass_prev = assessment_as_of(section, cut), assessment_as_of(section, prev)
    for a in list(ass_now.values()) + list(ass_prev.values()):
        for eid in a.get("evidence", []):  # even if superseded since: flagged superseded_by
            if eid in audit_by_id and eid not in have:
                background.append(audit_by_id[eid]); have.add(eid)
    now_t, prev_t = obs_as_of(section, cut), obs_as_of(section, prev)
    kpis = []
    for m, row in reg.items():
        if not kpi.required_active(row, end):   # requirement judged at the PERIOD END
            continue
        cur = latest_obs(now_t, m, end)        # obs within the period, known by the cutoff
        before = latest_obs(prev_t, m, prev_end)
        change = compare(cur, before) if cur and before else None
        year_ago_ = year_ago(now_t, cur) if cur else None
        kpis.append({"metric": m, "unit": row["unit"], "definition": row["definition"],
                     "current": clean(cur) if cur else None,
                     "previous": clean(before) if before else None, "change": change,
                     "year_ago": year_ago_})
    series, chartable = {}, []
    for m in sorted({m for (m, _) in now_t}):
        pts = sorted(([o, r["value"]] for (mm, o), r in now_t.items()
                      if mm == m and kpi.obs_range(o)[1] <= end
                      and kpi.obs_range(o)[0].year >= end.year - SERIES_YEARS),
                     key=lambda p: kpi.obs_range(p[0])[0])
        if pts:
            series[m] = pts           # everything is frozen; the index below is guidance
        if len(pts) >= 5:
            chartable.append({"metric": m, "n": len(pts), "first": pts[0][0], "last": pts[-1][0],
                              "granularities": sorted({kpi.obs_kind(o) for o, _ in pts})})
    other_obs = sorted({m for (m, _) in now_t} - {k["metric"] for k in kpis})
    return {
        "section": section, "period": period, "period_start": str(start),
        "period_end": str(end), "cutoff": str(cut), "previous_cutoff": str(prev),
        "rule": "records with known_at (published) <= cutoff; 'new' = known_at in (previous_cutoff, cutoff]",
        "framework": [{"topic": t, "name": n, "description": d} for t, n, d in readme_items(section)],
        "new_events": [clean(e) for e in sorted(new, key=lambda e: (e["date"], e["id"]))],
        "background_events": [clean(e) for e in sorted(background, key=lambda e: (e["date"], e["id"]))],
        "kpi_headlines": kpis,
        "other_metrics": [{"metric": m, "unit": reg.get(m, {}).get("unit", ""),
                           "definition": reg.get(m, {}).get("definition", ""),
                           "latest": clean(latest_obs(now_t, m, end) or {})} for m in other_obs],
        "chartable_metrics": chartable,
        "series": series,
        "assessments": {t: {"current": clean(a), "previous": clean(ass_prev[t]) if t in ass_prev else None}
                        for t, a in sorted(ass_now.items())},
    }


def dump_snapshot(snap: dict) -> str:
    """Readable JSON (indent=1), but each frozen series on one line (size)."""
    body = json.dumps({k: v for k, v in snap.items() if k != "series"}, ensure_ascii=False, indent=1)
    series = ",\n".join(f"  {json.dumps(m)}: {json.dumps(pts, ensure_ascii=False)}" for m, pts in snap["series"].items())
    return body[:-2] + ',\n "series": {\n' + series + "\n }\n}\n"


def snapshot_evidence_text(snap: dict) -> str:
    """The typed, citable text of a snapshot (for number traceability): claims,
    notes and dates of events; KPI values/changes; latest other-metric values;
    assessment labels/rationales; framework descriptions; period dates. NOT ids,
    significance, chart series or other metadata."""
    parts = [snap.get("period", ""), snap.get("period_start", ""), snap.get("period_end", ""),
             snap.get("cutoff", ""), snap.get("previous_cutoff", "")]
    for f in snap.get("framework", []):
        parts += [f["name"], f["description"]]
    for e in snap["new_events"] + snap["background_events"]:
        parts += [e["claim"], e.get("note", ""), str(e["date"]), e["published"]]
        parts += [f"{m['obs']} {m['value']}" for m in e.get("metrics", []) or []]
    for k in snap["kpi_headlines"]:
        for r in (k["current"], k["previous"]):
            if r:
                parts += [r["obs"], r["value"], r["published"], r.get("note", "")]
        if k["change"]:
            parts += [k["change"]["value"], k["change"]["from_obs"], k["change"]["to_obs"]]
        if k["year_ago"]:
            parts += [k["year_ago"]["obs"], k["year_ago"]["value"], k["year_ago"]["change"]]
        parts.append(k["definition"])
    for o in snap["other_metrics"]:
        if o["latest"]:
            parts += [o["latest"]["obs"], o["latest"]["value"], o["latest"]["published"], o["latest"].get("note", "")]
        parts.append(o.get("definition", ""))
    for a in snap["assessments"].values():
        for x in (a["current"], a["previous"]):
            if x:
                parts += [x["label"], x["rationale"], x["made_at"]]
    return "\n".join(p for p in parts if p)


def snapshot_text(snap: dict) -> str:  # backwards-compatible name
    return snapshot_evidence_text(snap)


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


# --- merge (prepare -> validate the whole proposed state -> write) ------------------------
def _same(a: dict, b: dict) -> bool:
    return clean(a) == clean(b)


def prepare(section: str, ev_files=(), obs_files=(), ass_files=(), allow_legacy: bool = False,
            lint_mode: bool = False, seal: bool = False) -> tuple[list[str], list[str], dict]:
    """Plan a merge of staged files. Replays are idempotent: a staged record that
    is identical to one already in the ledger (or rejected/) is a no-op; a
    conflicting one is an error. In lint_mode, 'unverified' records are validated
    as if admitted (nothing is written)."""
    errs: list[str] = []
    topics = valid_topics(section)
    cur_ev, cur_obs, cur_ass = events(section), observations(section), assessments(section)
    rejected_now = load_jsonl(path("rejected", section))
    by_id = {e["id"]: e for e in cur_ev}
    ass_by_id = {a["id"]: a for a in cur_ass}
    admit_statuses = {"verified", "corrected"} | ({"legacy"} if allow_legacy else set()) \
        | ({"unverified"} if lint_mode else set())
    plan = {"events": [], "obs": [], "ass": [], "rejected": [], "stats": dict.fromkeys(
        ["events_in", "events_rejected", "events_replayed", "obs_in", "obs_rejected", "obs_dup",
         "assessments_in", "assessments_replayed"], 0)}
    st = plan["stats"]
    staged_ids: dict[str, dict] = {}
    for f in ev_files:
        for e in load_jsonl(f):
            es = check_event(e, section, topics, staged=True)
            if allow_legacy and isinstance(e.get("verification"), dict) and e["verification"].get("status") == "legacy":
                es = [x for x in es if "verification.status" not in x]
            if es:
                errs += [f"{os.path.basename(f)}: {x}" for x in es]
                continue
            eid, status = e["id"], e["verification"]["status"]
            if eid in staged_ids:
                if not _same(e, staged_ids[eid]):
                    errs.append(f"event {eid}: staged twice with different content")
                continue
            staged_ids[eid] = e
            if status in admit_statuses:
                if eid in by_id:
                    if _same(e, by_id[eid]):
                        st["events_replayed"] += 1
                    else:
                        errs.append(f"event {eid}: id already in the ledger with different content "
                                    f"(to correct it or add a source, stage a NEW record with \"supersedes\": [\"{eid}\"])")
                    continue
                plan["events"].append(e)
                st["events_in"] += 1
            elif status == "rejected" or (status == "unverified" and not lint_mode):
                if not any(_same(e | {"_kind": "event"}, x) for x in rejected_now):
                    plan["rejected"].append(clean(e) | {"_kind": "event"})
                st["events_rejected"] += 1
            else:
                errs.append(f"event {eid}: status '{status}' cannot be merged")
    effective = obs_as_of(section)  # current effective row per (metric, obs)
    have_rows = {tuple(r[c] for c in OBS_COLUMNS) for r in cur_obs}
    for f in obs_files:
        for r in load_obs(f):
            ident = tuple(r[c] for c in OBS_COLUMNS)
            if ident in have_rows:        # exact replay (incl. of an admitted revision)
                st["obs_dup"] += 1
                continue
            have_rows.add(ident)
            es = check_obs_row(r, __import__("kpi").load_registry(section)[0], staged=True)
            if es:
                errs += [f"{os.path.basename(f)}: {x}" for x in es]
                continue
            if r["verification"] in {"verified", "corrected", "collector"} | ({"legacy"} if allow_legacy else set()) \
                    | ({"unverified"} if lint_mode else set()):
                k = (r["metric"], r["obs"])
                eff = effective.get(k)
                # no-op iff the EFFECTIVE value is numerically equal and not outranked
                if eff and float(eff["value"]) == float(r["value"]) and tier(eff) >= tier(r):
                    st["obs_dup"] += 1
                    continue
                plan["obs"].append(r)
                effective[k] = r if not eff or _rank(r) >= _rank(eff) else eff
                st["obs_in"] += 1
            else:
                rec = clean(r) | {"_kind": "observation"}
                if not any(_same(rec, x) for x in rejected_now):
                    plan["rejected"].append(rec)
                st["obs_rejected"] += 1
    for f in ass_files:
        for a in load_jsonl(f):
            if seal and "evidence_digest" not in a and a.get("target") and _valid_day(a.get("made_at")):
                a = a | {"evidence_digest": evidence_digest(section, a["target"], day(a["made_at"]))}
            aid = a.get("id")
            if aid in ass_by_id:
                if _same(a, ass_by_id[aid]):
                    st["assessments_replayed"] += 1
                else:
                    errs.append(f"assessment {aid}: id already in the ledger with different content")
                continue
            plan["ass"].append(a)
            st["assessments_in"] += 1
    # the whole proposed state must validate (the same checks as `ledger.py check`)
    se, warns = validate_state(section, cur_ev + plan["events"], cur_obs + plan["obs"],
                               cur_ass + plan["ass"], staged_statuses=lint_mode)
    errs += se
    return errs, warns, plan


class _Lock:
    """Exclusive per-section merge lock: an OS-held flock on ledger/.lock-<section>
    (released by the kernel if the process dies; no stale PID files)."""
    def __init__(self, section: str):
        self.p = os.path.join(DATA, "ledger", f".lock-{section}")

    def __enter__(self):
        import fcntl
        os.makedirs(os.path.dirname(self.p), exist_ok=True)
        self.f = open(self.p, "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)   # waits for a concurrent merge
        return self

    def __exit__(self, *a):
        import fcntl
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()


def _append_atomic(p: str, text: str) -> None:
    """Append by rewrite: old bytes + new text -> temp file -> os.replace."""
    if not text:
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    old = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    if old and not old.endswith("\n"):
        old += "\n"
    tmp = f"{p}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(old + text)
    os.replace(tmp, p)


def merge(section: str, ev_files=(), obs_files=(), ass_files=(),
          allow_legacy: bool = False) -> tuple[list[str], dict]:
    """Validate everything first; write nothing on any error. Files are written
    rejected -> observations -> events -> assessments, each atomically; since
    replays are no-ops, re-running after a crash completes the merge."""
    with _Lock(section):
        errs, _, plan = prepare(section, ev_files, obs_files, ass_files, allow_legacy, seal=True)
        if errs:
            return errs, plan["stats"]
        jl = lambda recs: "".join(json.dumps(clean(r) if not r.get("_kind") else r, ensure_ascii=False) + "\n"
                                  for r in recs)
        _append_atomic(path("rejected", section), jl(plan["rejected"]))
        if plan["obs"]:
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=OBS_COLUMNS, lineterminator="\n", extrasaction="ignore")
            if not os.path.exists(path("observations", section)):
                w.writeheader()
            w.writerows(plan["obs"])
            _append_atomic(path("observations", section), buf.getvalue())
        _append_atomic(path("events", section), jl(sorted(plan["events"], key=lambda e: e["id"])))
        _append_atomic(path("assessments", section), jl(plan["ass"]))
        return [], plan["stats"]


def lint(section: str, ev_files=(), obs_files=(), ass_files=(), allow_legacy: bool = False,
         final: bool = False) -> list[str]:
    """Validate staged files as if merged (nothing written). final=True: no
    'unverified' record may remain (run after the verifier)."""
    errs, _, _ = prepare(section, ev_files, obs_files, ass_files, allow_legacy, lint_mode=not final)
    if final:
        for f in ev_files:
            errs += [f"event {e.get('id')}: still unverified" for e in load_jsonl(f)
                     if isinstance(e.get("verification"), dict) and e["verification"].get("status") == "unverified"]
        for f in obs_files:
            errs += [f"obs {r['metric']}@{r['obs']}: still unverified" for r in load_obs(f) if r["verification"] == "unverified"]
    return errs


# --- CLI ---------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("sections", nargs="*")
    t = sub.add_parser("topics"); t.add_argument("section", choices=SECTIONS)
    r = sub.add_parser("recent"); r.add_argument("section", choices=SECTIONS); r.add_argument("--limit", type=int, default=150)
    for name in ("merge", "lint"):
        m = sub.add_parser(name); m.add_argument("section", choices=SECTIONS)
        m.add_argument("--events", nargs="*", default=[]); m.add_argument("--obs", nargs="*", default=[])
        m.add_argument("--assessments", nargs="*", default=[])
        m.add_argument("--legacy", action="store_true", help="admit verification=legacy (one-off report conversions)")
        if name == "lint":
            m.add_argument("--final", action="store_true", help="after verify: no 'unverified' record may remain")
    cu = sub.add_parser("cutoff"); cu.add_argument("period")
    it = sub.add_parser("items"); it.add_argument("section", choices=SECTIONS)
    sta = sub.add_parser("stale"); sta.add_argument("section", choices=SECTIONS); sta.add_argument("--until", required=True)
    sta.add_argument("--force", action="store_true", help="all targets (e.g. after a rubric change)")
    se = sub.add_parser("series"); se.add_argument("section", choices=SECTIONS); se.add_argument("metric")
    se.add_argument("--as-of", required=True)
    stt = sub.add_parser("state"); stt.add_argument("section", choices=SECTIONS)
    stt.add_argument("--get-item", help="last_until of one watch item"); stt.add_argument("--record", help="JSON object of a finished run")
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
            evs = sorted(effective_events(events(a.section)), key=lambda e: (e["date"], e["id"]))[-a.limit:]
            for e in evs:
                print(f"{e['id']} [{e['kind']}; {','.join(e['topics'])}; {e['verification']['status']}] {e['claim']}")
            if not evs:
                print(f"(no events yet for {a.section})")
        elif a.cmd == "merge":
            errs, stats = merge(a.section, a.events, a.obs, a.assessments, a.legacy)
            for e in errs:
                print(f"  ERROR {e}")
            print(f"merge {a.section}: {'ABORTED (nothing written)' if errs else 'ok'} {stats}")
            return 1 if errs else 0
        elif a.cmd == "lint":
            errs = lint(a.section, a.events, a.obs, a.assessments, a.legacy, a.final)
            for e in errs:
                print(f"  ERROR {e}")
            print(f"lint {a.section}: {len(errs)} error(s)")
            return 1 if errs else 0
        elif a.cmd == "items":
            for topic, name, desc in readme_items(a.section):
                print(f"{topic}|{name}|{desc}")
        elif a.cmd == "stale":
            for target, aid in stale_targets(a.section, day(a.until), a.force):
                print(f"{target}|{aid}")
        elif a.cmd == "series":
            import kpi
            t = obs_as_of(a.section, day(a.as_of))
            for (m, o), r in sorted(t.items(), key=lambda kv: kpi.obs_range(kv[0][1])[0]):
                if m == a.metric:
                    print(f"{o},{r['value']},{r['verification']},{r['published']}")
        elif a.cmd == "state":
            p = path("state", a.section)
            st = json.load(open(p)) if os.path.exists(p) else {"section": a.section, "items": {}, "runs": []}
            st.setdefault("items", {})
            if a.get_item:
                print(st["items"].get(a.get_item) or "")
            elif a.record:
                run = json.loads(a.record)
                st["runs"].append(run)
                for item in run["items"]:
                    st["items"][item] = max(filter(None, [st["items"].get(item), run["until"]]))
                st.pop("last_until", None)  # superseded by per-item watermarks
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w") as f:
                    json.dump(st, f, indent=1, ensure_ascii=False)
                    f.write("\n")
                print(f"state {a.section}: items={st['items']} runs={len(st['runs'])}")
        elif a.cmd == "cutoff":
            print(f"cutoff {cutoff(a.period)} previous_cutoff {prev_cutoff(a.period)} "
                  f"period {period_start(a.period)}..{__import__('kpi').period_as_of(a.period)}")
        elif a.cmd == "snapshot":
            snap = snapshot(a.period_dir, a.section)
            out = os.path.join(a.period_dir, "snapshot", f"{a.section}.json")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(dump_snapshot(snap))
            print(f"wrote {out}: {len(snap['new_events'])} new, {len(snap['background_events'])} background events, "
                  f"{len(snap['kpi_headlines'])} KPI headlines, cutoff {snap['cutoff']}")
    except (ValueError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
