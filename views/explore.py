#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Grand Endeavors explorer: derived, read-only views of the ledger
(DESIGN.md §1 "explorer (SQLite/Datasette)"). Nothing here is canonical: it is all
derived from the ledger. Outputs go to build/ (gitignored; the published site) and
can be rebuilt at any time, except the period pages, which are frozen into the
data repo next to the period's bulletins and snapshots.

COMMANDS
  explore.py build     [--out build/] [--as-of YYYY-MM-DD]
        -> <out>/ledger.sqlite (tables, indexes, views) + <out>/metadata.json (Datasette)
  explore.py dashboard [--out build/index.html] [--as-of YYYY-MM-DD]
        -> one self-contained static HTML page (no JS/CSS/CDN dependencies): the
           framework (framework.yaml: manifesto, definitions) with the ledger's state;
           README-like by default, every item expands to its detail
  explore.py site [--out build/] [--as-of YYYY-MM-DD]
        -> the published directory: index.html (live) + <period>/index.html (frozen
           period pages from the data repo) + ledger.sqlite + metadata.json
  explore.py period <period-dir> [--note TEXT] [--force]
        -> <period-dir>/index.html, frozen: the page as of the period's cutoff, with
           the period's framework (<period-dir>/framework.yaml, copied on first run);
           an existing page is kept unless --force

--as-of applies the ledger time rule (DESIGN.md §2): only records with
known_at <= as-of are included, and "expected by"/"overdue" are judged against
that date. Default: today. The same ledger + as-of gives the same output.

Browse the database (optional, not a dependency):
  uvx datasette build/ledger.sqlite -m build/metadata.json
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import html
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
import kpi  # noqa: E402
import ledger  # noqa: E402

SCHEMA = """
CREATE TABLE build_info (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE sections (section TEXT PRIMARY KEY, ord INTEGER, grp TEXT, title TEXT, kpi TEXT);
CREATE TABLE topics (section TEXT, topic TEXT, kind TEXT, slug TEXT, name TEXT, description TEXT,
    ord INTEGER, PRIMARY KEY (section, topic));
CREATE TABLE events (section TEXT, id TEXT, date TEXT, date_end TEXT, published TEXT,
    published_basis TEXT, retrieved TEXT, known_at TEXT, kind TEXT, significance INTEGER,
    claim TEXT, verification_status TEXT, verified_by TEXT, verified_at TEXT, collector TEXT,
    note TEXT, primary_url TEXT, topics JSON, sources JSON, metrics JSON, relates JSON,
    verification JSON, supersedes JSON, superseded_by TEXT, effective INTEGER, line INTEGER,
    PRIMARY KEY (section, id));
CREATE TABLE event_topics (section TEXT, event_id TEXT, topic TEXT);
CREATE TABLE event_sources (section TEXT, event_id TEXT, ord INTEGER, url TEXT, title TEXT, is_primary INTEGER);
CREATE TABLE event_relates (section TEXT, event_id TEXT, rel TEXT, related_id TEXT);
CREATE TABLE event_supersedes (section TEXT, event_id TEXT, superseded_id TEXT);
CREATE TABLE observations (section TEXT, metric TEXT, obs TEXT, obs_start TEXT, obs_end TEXT,
    obs_kind TEXT, value REAL, value_text TEXT, unit TEXT, source TEXT, published TEXT,
    published_basis TEXT, retrieved TEXT, known_at TEXT, collector TEXT, verification TEXT,
    note TEXT, tier INTEGER, effective INTEGER, line INTEGER);
CREATE TABLE assessments (section TEXT, id TEXT, target TEXT, status TEXT, label TEXT, made_at TEXT,
    known_at TEXT, rationale TEXT, evidence JSON, by TEXT, line INTEGER, basis JSON);
CREATE TABLE metrics (section TEXT, metric TEXT, unit TEXT, cadence TEXT, release_lag_days INTEGER,
    required_from TEXT, retired_after TEXT, definition TEXT, required INTEGER, retired INTEGER,
    n_obs INTEGER, latest_obs TEXT, latest_obs_end TEXT, latest_known_at TEXT, next_expected TEXT,
    overdue INTEGER, status TEXT, PRIMARY KEY (section, metric));
CREATE TABLE latest_kpi (section TEXT, metric TEXT, unit TEXT, required INTEGER, retired INTEGER,
    cadence TEXT, obs TEXT, obs_kind TEXT, value REAL, value_text TEXT, known_at TEXT,
    verification TEXT, source TEXT, prev_obs TEXT, prev_value REAL, prev_value_text TEXT,
    change REAL, change_text TEXT, change_label TEXT, comparable INTEGER, caveat TEXT,
    year_ago_obs TEXT, year_ago_value_text TEXT, year_ago_change_text TEXT,
    next_expected TEXT, overdue INTEGER, status TEXT, definition TEXT,
    PRIMARY KEY (section, metric));

CREATE INDEX ev_known ON events (known_at);
CREATE INDEX ev_date ON events (date_end);
CREATE INDEX evt_topic ON event_topics (topic, section);
CREATE INDEX evt_event ON event_topics (section, event_id);
CREATE INDEX evs_url ON event_sources (url);
CREATE INDEX evr_related ON event_relates (section, related_id);
CREATE INDEX evsup_superseded ON event_supersedes (section, superseded_id);
CREATE INDEX obs_metric ON observations (section, metric, obs_end);
CREATE INDEX obs_known ON observations (known_at);
CREATE INDEX ass_target ON assessments (section, target, made_at);

-- events minus those superseded by a record known by as_of (ledger.effective_events)
CREATE VIEW current_events AS SELECT * FROM events WHERE effective = 1;

-- the effective row per (metric, obs), as chosen by ledger.obs_as_of (precedence
-- (tier, known_at, retrieved): a non-legacy row outranks any legacy one)
CREATE VIEW current_obs AS SELECT * FROM observations WHERE effective = 1;

-- headline candidates: only periods that have ended by as_of (as ledger.latest_obs(..., when))
CREATE VIEW headline_obs AS
SELECT * FROM current_obs WHERE obs_end <= (SELECT value FROM build_info WHERE key = 'as_of');

CREATE VIEW milestone_status AS
WITH ranked AS (SELECT a.*, ROW_NUMBER() OVER (PARTITION BY section, target
                ORDER BY made_at DESC, line DESC) AS k FROM assessments a)
SELECT t.section, t.topic AS target, t.kind, t.name, t.ord,
       COALESCE(a.status, 'not yet assessed') AS status, a.label, a.made_at, a.rationale,
       a.evidence, a.by, a.id AS assessment_id, a.basis,
       -- 1 when every evidence event is legacy (an unverified pilot-2025 judgment)
       (SELECT MIN(e.verification_status = 'legacy') FROM json_each(a.evidence) j
         JOIN events e ON e.section = a.section AND e.id = j.value) AS legacy_evidence,
       p.status AS prev_status, p.made_at AS prev_made_at,
       (SELECT COUNT(*) FROM event_topics et JOIN current_events e ON e.section = et.section
         AND e.id = et.event_id WHERE et.section = t.section AND et.topic = t.topic) AS n_events
FROM topics t LEFT JOIN ranked a ON a.section = t.section AND a.target = t.topic AND a.k = 1
LEFT JOIN ranked p ON p.section = t.section AND p.target = t.topic AND p.k = 2
WHERE t.kind != 'beyond'
ORDER BY t.section, t.ord;

CREATE VIEW recent_events AS
SELECT section, known_at, date, id, kind, significance, verification_status, claim, primary_url, topics,
       supersedes
FROM current_events ORDER BY known_at DESC, date_end DESC, id DESC;

CREATE VIEW gaps AS
SELECT section, metric, unit, required, cadence, latest_obs, next_expected, status,
       CASE WHEN n_obs = 0 THEN 'never observed' ELSE 'overdue since ' || next_expected END AS gap
FROM metrics WHERE NOT retired AND (overdue OR n_obs = 0)
ORDER BY required DESC, section, metric;
"""

TABLE_DOCS = {
    "build_info": "Build parameters (as_of: the known_at cutoff applied to every record).",
    "sections": "Endeavors (sections) in framework.yaml order, with their KPI line.",
    "topics": "Topic tags per section from framework.yaml: kpi, milestone:<slug>, challenge:<slug>, beyond.",
    "events": "News/claims (ledger/events), incl. superseded ones (effective=0, superseded_by = the "
              "correcting record known by as_of). known_at = published. JSON columns keep nested fields.",
    "event_topics": "One row per (event, topic tag).",
    "event_sources": "One row per event source URL (ord 0 = first-listed).",
    "event_relates": "Event lifecycle links: event_id --rel--> related_id (update, retraction, ...).",
    "event_supersedes": "Corrections / added sources: event_id supersedes superseded_id (which then "
                        "drops out of every view once event_id is known).",
    "observations": "KPI datapoints incl. source revisions (ledger/observations); known_at = published. "
                    "tier: 0 legacy, 1 otherwise; effective=1 marks the row ledger.obs_as_of picks per "
                    "(metric, obs): highest (tier, known_at, retrieved).",
    "assessments": "Timestamped milestone/KPI status judgments; known_at = made_at.",
    "metrics": "Metric registry (metrics/*.csv) + derived: latest obs, next_expected "
               "(latest obs end + cadence + release_lag_days), overdue vs as_of.",
    "current_events": "Effective events (ledger.effective_events): superseded ones removed.",
    "current_obs": "Effective row per (metric, obs) (ledger.obs_as_of: non-legacy beats legacy, "
                   "then the latest known revision).",
    "headline_obs": "current_obs restricted to periods that ended by as_of (headline/schedule basis).",
    "latest_kpi": "Latest value per registered metric (ledger.latest_obs), the change vs the previous "
                  "observation with ledger.snapshot's comparability flag/caveat (granularity, calendar "
                  "month, same obs), and the like-for-like change vs the same month a year earlier.",
    "milestone_status": "Latest assessment per milestone/challenge/kpi target ('not yet assessed' if none), "
                        "with the previous status; legacy_evidence=1 if all evidence events are legacy.",
    "recent_events": "Effective events, most recently known first.",
    "gaps": "Registered (non-retired) metrics that are overdue or were never observed.",
}

QUERIES = {
    "kpi_dashboard": ("KPI dashboard", "Latest value, change vs previous observation (with its "
        "comparability flag), year-ago change for monthly series, and schedule per metric.",
        "SELECT section, metric, required, value_text || ' ' || unit AS latest, obs, known_at, "
        "verification, prev_value_text AS previous, change_text AS change, change_label, comparable, "
        "caveat, year_ago_obs, year_ago_change_text AS year_ago_change, "
        "next_expected, status FROM latest_kpi WHERE NOT retired ORDER BY section, required DESC, metric"),
    "events_by_milestone": ("Events by milestone", "Events tagged with a topic, e.g. milestone:the-bend.",
        "SELECT e.section, e.date, e.known_at, e.kind, e.significance, e.verification_status, e.claim, "
        "e.primary_url FROM event_topics t JOIN current_events e ON e.section = t.section AND e.id = t.event_id "
        "WHERE t.topic = :topic ORDER BY e.date_end DESC, e.id DESC"),
    "lifecycle_threads": ("Lifecycle threads", "Event pairs linked via relates or supersedes "
        "(later effective event -> earlier one; earlier_superseded_by if the earlier one was corrected).",
        "SELECT r.section, r.related_id AS earlier_id, b.date AS earlier_date, b.claim AS earlier_claim, "
        "b.superseded_by AS earlier_superseded_by, "
        "r.rel, r.event_id AS later_id, a.date AS later_date, a.claim AS later_claim "
        "FROM (SELECT section, event_id, rel, related_id FROM event_relates UNION ALL "
        "SELECT section, event_id, 'supersedes', superseded_id FROM event_supersedes) r "
        "JOIN current_events a ON a.section = r.section AND a.id = r.event_id "
        "LEFT JOIN events b ON b.section = r.section AND b.id = r.related_id "
        "ORDER BY r.section, r.related_id, a.date_end, r.rel"),
    "legacy_vs_verified": ("Legacy vs verified", "Effective record counts by verification status "
        "(superseded events and overridden observation rows excluded).",
        "SELECT section, 'events' AS records, verification_status AS verification, COUNT(*) AS n "
        "FROM current_events GROUP BY 1, 2, 3 UNION ALL "
        "SELECT section, 'observations', verification, COUNT(*) FROM current_obs GROUP BY 1, 2, 3 "
        "ORDER BY 1, 2, 3"),
    "overdue_metrics": ("Overdue metrics", "Metrics whose next release is past due, or never observed.",
        "SELECT * FROM gaps"),
}

D = dt.date.fromisoformat
MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}
DAYS = {"daily": 1, "weekly": 7}


def warn(msg: str) -> None:
    print(f"WARN {msg}", file=sys.stderr)


# --- derived values ---------------------------------------------------------------
def add_months(d: dt.date, n: int) -> dt.date:
    y, m = divmod(d.month - 1 + n, 12)
    last = calendar.monthrange(d.year + y, m + 1)[1]
    month_end = d.day == calendar.monthrange(d.year, d.month)[1]
    return dt.date(d.year + y, m + 1, last if month_end else min(d.day, last))


def next_expected(cadence: str, lag: str, obs_end: dt.date) -> dt.date | None:
    """When the next obs should be published: end of the next period + release lag.
    None for irregular cadence or empty lag (= no regular release, see kpi.py)."""
    if lag is None or not str(lag).strip():
        return None
    if cadence in DAYS:
        nxt = obs_end + dt.timedelta(days=DAYS[cadence])
    elif cadence in MONTHS:
        nxt = add_months(obs_end, MONTHS[cadence])
    else:
        return None
    return nxt + dt.timedelta(days=int(lag))


# One implementation of change/comparability semantics: ledger.py (shared with snapshots).
_change_text, compare, year_ago = ledger.change_text, ledger.compare, ledger.year_ago


def framework_meta(section: str, fw: dict | None = None) -> tuple[str, str, str, dict[str, str]]:
    """(group title, section title, KPI line, {topic name: description}) from framework.yaml."""
    try:
        sec, grp = ledger.fw_section(section, fw)
    except KeyError:
        return "", section, "", {}
    desc = {t["name"]: ledger.fw_description(t) for k in ("milestones", "challenges") for t in sec.get(k) or []}
    return (grp or {}).get("title", ""), sec["title"], sec.get("kpi", ""), desc


def _known(recs: list[dict], as_of: dt.date, what: str) -> list[tuple[dict, str]]:
    out = []
    for r in recs:
        try:
            k = ledger.known_at(r)
        except (KeyError, ValueError, TypeError):
            warn(f"{what}: skipping record without a valid known_at: {str(ledger.clean(r))[:100]}")
            continue
        if k <= as_of:
            out.append((r, str(k)))
    return out


def _date_end(d: str) -> str | None:
    try:
        return str(ledger.date_end(str(d)))
    except ValueError:
        return None


def _j(v) -> str | None:
    return None if v is None else json.dumps(v, ensure_ascii=False)


# --- build ----------------------------------------------------------------------------
def build_db(db: sqlite3.Connection, as_of: dt.date, fw: dict | None = None) -> None:
    """fw: the framework to use (default: the current framework.yaml; a period page
    passes the framework frozen with that period)."""
    fw = fw or ledger.framework()
    db.executescript(SCHEMA)
    ins = lambda table, row: db.execute(
        f"INSERT INTO {table} VALUES ({','.join('?' * len(row))})", row)
    ins("build_info", ("as_of", str(as_of)))
    for n, sec in enumerate(ledger.SECTIONS):
        group, title, kpi_line, desc = framework_meta(sec, fw)
        ins("sections", (sec, n, group, title, kpi_line))
        try:
            t = ledger.framework_topics(sec, fw)
        except KeyError:  # section not in framework.yaml
            t = {"milestones": [], "challenges": []}
        tops = [("kpi", "kpi", "kpi", "KPI", kpi_line)]
        tops += [(f"milestone:{s}", "milestone", s, name, desc.get(name, "")) for s, name in t["milestones"]]
        tops += [(f"challenge:{s}", "challenge", s, name, desc.get(name, "")) for s, name in t["challenges"]]
        tops.append(("beyond", "beyond", "beyond", "Beyond the framework", ""))
        for i, (topic, kind, slug, name, d) in enumerate(tops):
            ins("topics", (sec, topic, kind, slug, name, d, i))

        known_evs = _known(ledger.events(sec), as_of, f"events/{sec}")
        # ONE supersedes implementation: a superseded event drops out once its successor is known
        live = {id(e) for e in ledger.effective_events([e for e, _ in known_evs], as_of)}
        superseded_by = {s: e.get("id") for e, _ in known_evs for s in e.get("supersedes") or []}
        for e, known in known_evs:
            v = e.get("verification") or {}
            srcs = [s for s in e.get("sources") or [] if isinstance(s, dict)]
            ins("events", (sec, e.get("id"), e.get("date"), _date_end(e.get("date", "")), e.get("published"),
                           e.get("published_basis"), e.get("retrieved"), known, e.get("kind"),
                           e.get("significance"), e.get("claim"), v.get("status"), v.get("by"), v.get("at"),
                           e.get("collector"), e.get("note"), srcs[0].get("url") if srcs else None,
                           _j(e.get("topics")), _j(e.get("sources")), _j(e.get("metrics")),
                           _j(e.get("relates")), _j(v), _j(e.get("supersedes")), superseded_by.get(e.get("id")),
                           int(id(e) in live), e.get("_line")))
            for sid in e.get("supersedes") or []:
                ins("event_supersedes", (sec, e.get("id"), sid))
            for tp in e.get("topics") or []:
                ins("event_topics", (sec, e.get("id"), tp))
            for i, s in enumerate(srcs):
                ins("event_sources", (sec, e.get("id"), i, s.get("url"), s.get("title"), int(bool(s.get("primary")))))
            for r in e.get("relates") or []:
                ins("event_relates", (sec, e.get("id"), r.get("rel"), r.get("id")))

        obs_rows = []
        for r, known in _known(ledger.observations(sec), as_of, f"observations/{sec}"):
            try:
                kpi.obs_range(r["obs"]), float(r["value"])
            except ValueError:
                warn(f"observations/{sec}:{r['_line']}: skipping malformed obs/value")
                continue
            obs_rows.append(r)
        # ONE precedence implementation: the ledger's (tier, known_at, retrieved) rank
        eff = ledger.obs_as_of(sec, as_of, rows=obs_rows)
        eff_lines = {r["_line"] for r in eff.values()}
        for r in obs_rows:
            start, end = kpi.obs_range(r["obs"])
            ins("observations", (sec, r["metric"], r["obs"], str(start), str(end), kpi.obs_kind(r["obs"]),
                                 float(r["value"]), r["value"], r["unit"], r["source"], r["published"],
                                 r["published_basis"], r["retrieved"], str(ledger.known_at(r)), r["collector"],
                                 r["verification"], r["note"], ledger.tier(r), int(r["_line"] in eff_lines),
                                 r["_line"]))

        for a, known in _known(ledger.assessments(sec), as_of, f"assessments/{sec}"):
            ins("assessments", (sec, a.get("id"), a.get("target"), a.get("status"), a.get("label"),
                                a.get("made_at"), known, a.get("rationale"), _j(a.get("evidence")),
                                a.get("by"), a.get("_line"), _j(a.get("basis"))))

        reg, _ = kpi.load_registry(sec)
        for m, row in (reg or {}).items():
            # headline = ledger.latest_obs: effective rows whose period ended by as_of
            n_obs = sum(1 for (mm, _), r in eff.items() if mm == m and kpi.obs_range(r["obs"])[1] <= as_of)
            cur = ledger.latest_obs(eff, m, as_of)
            prev = ledger.latest_obs({k: r for k, r in eff.items() if k != (m, cur["obs"])}, m, as_of) \
                if cur else None
            end = kpi.obs_range(cur["obs"])[1] if cur else None
            retired = bool(row["_ret"] and as_of > row["_ret"])
            nxt = next_expected(row["cadence"], row["release_lag_days"], end) if cur else None
            overdue = bool(nxt and nxt < as_of and not retired)
            status = ("retired" if retired else "no data" if not cur else "overdue" if overdue else "ok")
            required = int(kpi.required_active(row, as_of))
            ins("metrics", (sec, m, row["unit"], row["cadence"],
                            int(row["release_lag_days"]) if row["release_lag_days"].isdigit() else None,
                            row["required_from"], row["retired_after"], row["definition"],
                            required, int(retired), n_obs,
                            cur and cur["obs"], end and str(end), cur and str(ledger.known_at(cur)),
                            nxt and str(nxt), int(overdue), status))
            ch = compare(cur, prev) if cur and prev else None
            ya = year_ago(eff, cur) if cur else None
            ins("latest_kpi", (sec, m, row["unit"], required, int(retired), row["cadence"],
                               *((cur["obs"], kpi.obs_kind(cur["obs"]), float(cur["value"]), cur["value"],
                                  str(ledger.known_at(cur)), cur["verification"], cur["source"])
                                 if cur else (None,) * 7),
                               *((prev["obs"], float(prev["value"]), prev["value"]) if prev else (None,) * 3),
                               *((float(ch["value"]), ch["value"], f"vs previous observation ({prev['obs']})",
                                  int(ch["comparable"]), ch["caveat"]) if ch else (None,) * 5),
                               *((ya["obs"], ya["value"], ya["change"]) if ya else (None,) * 3),
                               nxt and str(nxt), int(overdue), status, row["definition"]))
    db.commit()


def metadata(as_of: dt.date) -> dict:
    return {
        "title": "Grand Endeavors ledger",
        "description": f"Everything known about humanity's grand endeavors, as of {as_of} "
                       "(records with known_at <= as_of). Derived from the git ledger by explore.py; "
                       "'legacy' records are unverified pilot-2025 conversions.",
        "databases": {"ledger": {
            "tables": {t: {"description": d} for t, d in TABLE_DOCS.items()},
            "queries": {k: {"title": t, "description": d, "sql": s} for k, (t, d, s) in QUERIES.items()},
        }},
    }


def build(out_dir: str, as_of: dt.date) -> str:
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, "ledger.sqlite")
    tmp = p + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    try:
        build_db(db, as_of)
    finally:
        db.close()
    os.replace(tmp, p)  # a failed build leaves the previous artifact intact
    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata(as_of), f, ensure_ascii=False, indent=1)
        f.write("\n")
    return p


# --- dashboard ------------------------------------------------------------------------
CSS = """
:root{color-scheme:light dark;--bg:#f6f7f9;--card:#fff;--ink:#1d2330;--mute:#6b7385;--line:#e2e5ea;--green:#1f9d55;
--yellow:#d69e2e;--red:#d64545;--gap:#b83280;--acc:#2b6cb0;--tile:#fbfcfd;--gapbg:#fff5fa;--chip:#edf2f7;
--unk:#9aa1ad;--legacy:#975a16;--notebg:#fffaf0;--noteln:#f6e05e}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--card:#1b1f27;--ink:#e3e7ee;--mute:#949cad;--line:#2e3440;
--green:#38b26a;--yellow:#e0ac45;--red:#e36363;--gap:#e06aaa;--acc:#6aa8ec;--tile:#20252e;--gapbg:#2a1b24;
--chip:#2c333f;--unk:#6b7280;--legacy:#e0a960;--notebg:#2a2416;--noteln:#8a7424}}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;
background:var(--bg);color:var(--ink)}header,main{max-width:1180px;margin:0 auto;padding:16px}
header h1{margin:0 0 4px;font-size:22px}.mute{color:var(--mute)}a{color:var(--acc)}
nav a{margin-right:10px;white-space:nowrap}section{background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:14px 18px;margin:16px 0}section h2{margin:0;font-size:19px}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);margin:16px 0 6px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
.tile{border:1px solid var(--line);border-radius:8px;padding:10px;background:var(--tile)}
.tile .m{font-weight:600;font-size:12px;word-break:break-word}.tile .v{font-size:24px;font-weight:700}
.tile .v small{font-size:13px;color:var(--mute);font-weight:400}.tile .d,.tile .c{font-size:12px;color:var(--mute)}
.up,.down{color:var(--ink)}.spark{display:block;margin:4px 0;color:var(--acc)}
.gap{color:var(--gap);font-weight:700}.tile.nodata,.tile.overdue{border:2px dashed var(--gap);background:var(--gapbg)}
.badge{display:inline-block;font-size:11px;border-radius:4px;padding:0 5px;margin-left:4px;
border:1px solid currentColor;vertical-align:1px}.b-legacy{color:var(--legacy);background:var(--notebg)}
.b-verified,.b-corrected,.b-collector{color:var(--green)}.b-req{color:var(--acc)}
.nc{opacity:.75}.b-nc{color:var(--mute);font-size:10px}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:0}
.s-green{background:var(--green)}.s-yellow{background:var(--yellow)}.s-red{background:var(--red)}.s-achieved{background:var(--green) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'%3E%3Cpath d='M2.5 5.2l1.8 1.8 3.3-3.6' fill='none' stroke='white' stroke-width='1.6'/%3E%3C/svg%3E") center/100% no-repeat}.s-unknown{background:var(--unk)}
.s-none{border:2px dashed var(--mute)}ul{padding-left:0;list-style:none;margin:0}
li.ms,li.ev{padding:5px 0;border-bottom:1px solid var(--line)}li.ev .meta{font-size:12px;color:var(--mute)}
.chip{font-size:11px;background:var(--chip);border-radius:3px;padding:0 4px;margin-right:3px}
.sig3{font-weight:600}.rel{font-size:12px;color:var(--mute);margin-left:12px}
details summary{cursor:pointer;color:var(--acc);margin:6px 0}
header,main{max-width:980px}.tagline{font-size:16px;margin:2px 0 6px}.asof{margin:4px 0}
.small{font-size:12px}.note{background:var(--notebg);border:1px solid var(--noteln);border-radius:6px;padding:6px 10px;margin:8px 0}
.manifesto p{font-size:15px;margin:8px 0}.legend{margin:8px 0 4px}.more{padding:4px 0 8px 18px}
.group>h2.gh{margin:28px 0 4px;font-size:21px}.group>p{margin:4px 0 8px}.group section h2{font-size:17px}
section p{margin:6px 0}.kpi{margin:10px 0 2px}
details summary{list-style:none}details summary::-webkit-details-marker{display:none}
details>summary::before{content:"▸ ";color:var(--mute)}details[open]>summary::before{content:"▾ "}
li.topic summary,.kpid summary{color:var(--ink);margin:0;padding:5px 0}
li.topic{border-bottom:1px solid var(--line)}ul.topics{margin:0 0 4px}
.st{display:block;font-size:13px;margin-left:16px}ul.md{list-style:disc;padding-left:22px;margin:4px 0}
h4{font-size:12px;color:var(--mute);margin:10px 0 4px}.ass{margin:6px 0}
dl.basis{display:grid;grid-template-columns:max-content 1fr;gap:2px 10px;font-size:13px;margin:6px 0}
dl.basis dt{color:var(--mute)}dl.basis dd{margin:0}.b-cited{color:var(--acc)}
footer{margin:24px 0}.news{margin-top:10px}
"""


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def link(url, text) -> str:
    if url and ledger.URL_RE.match(str(url)):
        return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(text)}</a>'
    return esc(text)


def badge(status) -> str:
    return f'<span class="badge b-{esc(status)}">{esc(status or "unverified")}</span>'


def sparkline(points: list[tuple[dt.date, float]], kind: str = "", w: int = 200, h: int = 34, pad: int = 3) -> str:
    if len(points) < 2:
        return ""
    x0, x1 = points[0][0].toordinal(), points[-1][0].toordinal()
    lo, hi = min(v for _, v in points), max(v for _, v in points)
    sx = lambda d: pad + (w - 2 * pad) * ((d.toordinal() - x0) / (x1 - x0) if x1 > x0 else 0.5)
    sy = lambda v: h - pad - (h - 2 * pad) * ((v - lo) / (hi - lo) if hi > lo else 0.5)
    pts = " ".join(f"{sx(d):.1f},{sy(v):.1f}" for d, v in points)
    d, v = points[-1]
    return (f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">'
            f'<title>{len(points)} {esc(kind + " " if kind else "")}obs {points[0][0]}..{d}; '
            f'range {lo:g}..{hi:g}</title>'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="1.5"/>'
            f'<circle cx="{sx(d):.1f}" cy="{sy(v):.1f}" r="2.5" fill="currentColor"/></svg>')


def kpi_tile(db: sqlite3.Connection, k: sqlite3.Row) -> str:
    req = '<span class="badge b-req">required</span>' if k["required"] else ""
    head = f'<div class="m" title="{esc(k["definition"])}">{esc(k["metric"])}{req}</div>'
    if k["obs"] is None:
        return (f'<div class="tile nodata">{head}<div class="v gap">—</div>'
                f'<div class="gap">no data yet</div><div class="d">{esc(k["unit"])} · {esc(k["cadence"])}</div></div>')
    body = (f'<div class="v">{esc(k["value_text"])} <small>{esc(k["unit"])}</small></div>'
            f'<div class="d">obs {esc(k["obs"])} · known {esc(k["known_at"])} · '
            f'{link(k["source"], "source")}{badge(k["verification"])}</div>')
    if k["year_ago_obs"] is not None:  # like-for-like first: the comparable change
        body += (f'<div class="c">{_arrow(k["year_ago_change_text"])} vs same month a year earlier '
                 f'({esc(k["year_ago_obs"])}: {esc(k["year_ago_value_text"])})</div>')
    if k["prev_obs"] is not None:
        if k["comparable"]:
            body += (f'<div class="c">{_arrow(k["change_text"])} {esc(k["change_label"])}: '
                     f'{esc(k["prev_value_text"])}</div>')
        else:
            body += (f'<div class="c nc" title="not comparable: {esc(k["caveat"])}">'
                     f'{esc(k["change_text"])} {esc(k["change_label"])}: {esc(k["prev_value_text"])} '
                     f'<span class="badge b-nc">not comparable: {esc(k["caveat"])}</span></div>')
    body += sparkline(*spark_points(db, k))
    if k["overdue"]:
        body += f'<div class="gap">OVERDUE — next obs expected by {esc(k["next_expected"])}</div>'
    elif k["next_expected"]:
        body += f'<div class="d">next expected by {esc(k["next_expected"])}</div>'
    elif k["cadence"] == "irregular":
        body += '<div class="d">irregular releases (no schedule)</div>'
    else:
        body += f'<div class="d">{esc(k["cadence"])} data, no fixed release date</div>'
    return f'<div class="tile{" overdue" if k["overdue"] else ""}">{head}{body}</div>'


def _arrow(change_text: str) -> str:
    v = float(change_text)
    cls, arrow = ("up", "▲") if v > 0 else ("down", "▼") if v < 0 else ("", "=")
    return f'<span class="{cls}">{arrow} {esc(change_text)}</span>'


KIND_NAMES = {"9999": "annual", "9999-99": "monthly", "9999-99-99": "daily",
              "9999-Q9": "quarterly", "9999-H9": "half-yearly"}


def spark_points(db: sqlite3.Connection, k: sqlite3.Row) -> tuple[list[tuple[dt.date, float]], str]:
    """Headline series of ONE granularity (never e.g. daily mixed with monthly):
    the headline obs's own, unless it has < 2 points, then the dominant one."""
    kinds = db.execute("SELECT obs_kind, COUNT(*) FROM headline_obs WHERE section=? AND metric=? "
                       "GROUP BY obs_kind ORDER BY COUNT(*) DESC, obs_kind", (k["section"], k["metric"])).fetchall()
    if not kinds:
        return [], ""
    kind = k["obs_kind"] if dict(kinds).get(k["obs_kind"], 0) >= 2 else kinds[0][0]
    pts = [(dt.date.fromisoformat(r[0]), r[1]) for r in db.execute(
        "SELECT obs_end, value FROM headline_obs WHERE section=? AND metric=? AND obs_kind=? "
        "ORDER BY obs_end, obs_start", (k["section"], k["metric"], kind))]
    return pts, KIND_NAMES.get(kind, kind)


CITED = '<span class="badge b-cited">cited as evidence</span>'


def event_li(e: sqlite3.Row, names: dict[str, str], succ: dict[str, str] | None = None,
             anchor: bool = True, cited: bool = False, note: str = "") -> str:
    """anchor: carry the #ev-<section>-<id> target (the event's first occurrence on the page);
    cited: the event is evidence of the assessment it is listed under; note: an extra badge."""
    sig = int(e["significance"] or 0)
    chips = "".join(f'<span class="chip">{esc(names.get(t, t))}</span>' for t in json.loads(e["topics"] or "[]"))
    srcs = json.loads(e["sources"] or "[]")
    links = " ".join(link(s.get("url"), f"[{i}] {s.get('title') or 'source'}")
                     for i, s in enumerate(srcs, 1) if isinstance(s, dict))
    succ = succ or {}

    def target(eid) -> str:  # a superseded event is not shown: link to its effective successor
        seen, t = set(), eid
        while succ.get(t) and t not in seen:
            seen.add(t); t = succ[t]
        if t in succ:  # not effective and no successor: withdrawn (a tombstone is never shown)
            return f"{esc(eid)} (withdrawn)"
        label = esc(eid) + (f" (superseded by {esc(t)})" if t != eid else "")
        return f'<a href="#ev-{esc(e["section"])}-{esc(t)}">{label}</a>'
    rels = "".join(f'<div class="rel">↳ {esc(r.get("rel"))} of {target(r.get("id"))}</div>'
                   for r in json.loads(e["relates"] or "[]") if isinstance(r, dict))
    rels += "".join(f'<div class="rel">↳ supersedes (corrects / adds sources to) {esc(s)}</div>'
                    for s in json.loads(e["supersedes"] or "[]"))
    aid = f' id="ev-{esc(e["section"])}-{esc(e["id"])}"' if anchor else ""
    return (f'<li class="ev sig{sig}"{aid}>'
            f'<div class="meta">{esc(e["date"])} · {esc(e["kind"])} · '
            f'<span title="significance {sig}/3">{"●" * sig}{"○" * (3 - sig)}</span> · '
            f'known {esc(e["known_at"])}{badge(e["verification_status"])}'
            f'{CITED if cited else ""}{f" <span class=badge>{esc(note)}</span>" if note else ""}</div>'
            f'<div>{esc(e["claim"])}</div><div>{chips} {links}</div>{rels}</li>')


# --- Markdown (the framework's prose: inline emphasis/links, paragraphs, bullet lists) ---------
def md_inline(text) -> str:
    t = esc(text)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               lambda m: f'<a href="{m[2]}" target="_blank" rel="noopener noreferrer">{m[1]}</a>', t)
    t = re.sub(r"\*\*(\S.*?\S|\S)\*\*", r"<b>\1</b>", t)
    return re.sub(r"(?<![\w*])\*(\S.*?\S|\S)\*(?![\w*])", r"<i>\1</i>", t)


def md_block(text) -> str:
    out = []
    for blk in re.split(r"\n\s*\n", str(text or "").strip()):
        lines = [ln.strip() for ln in blk.splitlines() if ln.strip()]
        if lines and all(re.match(r"^[*-]\s", ln) for ln in lines):
            out.append('<ul class="md">' + "".join(f"<li>{md_inline(ln[1:].strip())}</li>" for ln in lines) + "</ul>")
        elif lines:
            out.append(f"<p>{md_inline(' '.join(lines))}</p>")
    return "".join(out)


STATUS_WORDS = {"green": "on track or ahead", "yellow": "progressing, behind pace", "red": "off track, stalled or distant",
                "achieved": "achieved (milestones)", "unknown": "unassessed: the rubric cannot judge it yet"}
BASIS_LABELS = {"eta": "ETA", "path": "Path", "blockers": "Blockers", "assessed_quantity": "Assessed quantity",
                "window": "Window", "benchmark": "Benchmark", "benchmark_source": "Benchmark source",
                "transients_discounted": "Transients discounted", "data_as_of": "Data as of",
                "reason": "Reason", "change_note": "Change", "rule": "Rubric rule"}


def _plain(v) -> str:
    if isinstance(v, dict):
        return "; ".join(f"{k}: {_plain(x)}" for k, x in v.items() if x not in (None, "", [], {}))
    if isinstance(v, list):
        return "; ".join(_plain(x) for x in v)
    return str(v)


def dot(status) -> str:
    st = status if status in STATUS_WORDS else "none"
    return f'<span class="dot s-{esc(st)}" title="{esc(STATUS_WORDS.get(st, "not yet assessed"))}"></span>'


def assessment_html(m: sqlite3.Row) -> str:
    """The judgment behind a status: label, rationale and the structured basis."""
    if not m["assessment_id"]:
        return '<div class="gap">not yet assessed</div>'
    prev = (f"; previously {esc(m['prev_status'])} on {esc(m['prev_made_at'])}"
            if m["prev_status"] and m["prev_status"] != m["status"] else "")
    out = [f'<div class="ass"><div>{dot(m["status"])}<b>{esc(m["label"])}</b> '
           f'<span class="mute">({esc(m["status"])}, assessed {esc(m["made_at"])}{prev})</span>'
           f'{badge("legacy") if m["legacy_evidence"] else ""}</div>',
           f'<div>{esc(m["rationale"])}</div>']
    basis = json.loads(m["basis"] or "null") or {}
    rows = [(BASIS_LABELS[k], _plain(basis[k])) for k in BASIS_LABELS if basis.get(k) not in (None, "", [], {})]
    if rows:
        out.append('<dl class="basis">' + "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in rows) + "</dl>")
    out.append(f'<div class="mute small">by {esc(m["by"])} · {len(json.loads(m["evidence"] or "[]"))} evidence event(s)</div></div>')
    return "".join(out)


def topic_events(db: sqlite3.Connection, sec: str, topic: str) -> list[sqlite3.Row]:
    return db.execute("SELECT e.* FROM event_topics t JOIN current_events e ON e.section = t.section "
                      "AND e.id = t.event_id WHERE t.section=? AND t.topic=? "
                      "ORDER BY e.date_end DESC, e.known_at DESC, e.id DESC", (sec, topic)).fetchall()


def events_ul(evs, names, succ, shown: set, cited: set | None = None) -> str:
    """An event list. Each event appears under every topic it is tagged with; the
    #ev-<section>-<id> anchor (lifecycle links) goes on its first occurrence."""
    out = []
    for e in evs:
        out.append(event_li(e, names, succ, anchor=e["id"] not in shown, cited=bool(cited and e["id"] in cited)))
        shown.add(e["id"])
    return "<ul>" + "".join(out) + "</ul>"


def evidence_and_events(db, sec: str, topic: str, m: sqlite3.Row | None, names, succ, shown: set) -> str:
    """The assessment's cited evidence (whatever its topic tags; a since-superseded
    record is shown as cited, flagged), then the topic's other events."""
    out = []
    cited = json.loads(m["evidence"] or "[]") if m and m["assessment_id"] else []
    if cited:
        rows = {r["id"]: r for r in db.execute(
            f"SELECT * FROM events WHERE section=? AND id IN ({','.join('?' * len(cited))})", (sec, *cited))}
        lis = []
        for eid in cited:
            e = rows.get(eid)
            if e is None:
                lis.append(f'<li class="ev"><span class="gap">{esc(eid)}: not in the ledger as of this date</span></li>')
            elif e["effective"]:
                lis.append(event_li(e, names, succ, anchor=eid not in shown, cited=True))
                shown.add(eid)
            else:
                lis.append(event_li(e, names, succ, anchor=False, cited=True,
                                    note=f"since superseded by {e['superseded_by']}" if e["superseded_by"]
                                    else "since withdrawn"))
        out.append(f"<h4>Cited evidence ({len(cited)})</h4><ul>{''.join(lis)}</ul>")
    evs = [e for e in topic_events(db, sec, topic) if e["id"] not in set(cited)]
    if evs:
        out.append(f"<h4>{'Other events' if cited else 'Events'} ({len(evs)})</h4>" + events_ul(evs, names, succ, shown))
    elif not cited:
        out.append('<div class="mute">no events tagged yet</div>')
    return "".join(out)


def topic_li(db, sec: str, item: dict, m: sqlite3.Row | None, kind: str, names, succ, shown: set) -> str:
    """One milestone/challenge, README-style (dot, name, definition, status line); the
    detail (criteria, assessment, evidence) expands."""
    topic = f"{kind}:{item['slug']}"
    # events = tagged with the topic, or cited by its assessment
    evs = {e["id"] for e in topic_events(db, sec, topic)}
    evs |= set(json.loads(m["evidence"] or "[]")) if m and m["assessment_id"] else set()
    head = (f'{dot(m["status"]) if (m and m["assessment_id"]) else (dot(None) if kind == "milestone" else "")}'
            f'<b>{md_inline(item["name"])}:</b> {md_inline(item["description"])}')
    if kind == "milestone":
        st = (f'{esc(m["label"])} <span class="mute">· assessed {esc(m["made_at"])}</span>'
              if m and m["assessment_id"] else '<span class="gap">not yet assessed</span>')
        head += f'<span class="st">{st} <span class="mute">· {len(evs)} event(s)</span></span>'
    else:
        head += f'<span class="st mute">{len(evs)} event(s)</span>'
    body = ""
    if item.get("details"):
        body += '<ul class="md">' + "".join(f"<li>{md_inline(d)}</li>" for d in item["details"]) + "</ul>"
    if kind == "milestone":
        body += assessment_html(m) if m else '<div class="gap">not yet assessed</div>'
    body += evidence_and_events(db, sec, topic, m, names, succ, shown)
    return f'<li class="topic"><details><summary>{head}</summary><div class="more">{body}</div></details></li>'


def kpi_block(db, sec: str, s: sqlite3.Row, ms: list, names, succ, shown: set) -> str:
    tiles = db.execute("SELECT * FROM latest_kpi WHERE section=? AND NOT retired "
                       "ORDER BY required DESC, metric", (sec,)).fetchall()
    km = next((m for m in ms if m["kind"] == "kpi"), None)
    out = [f'<div class="kpi"><b>KPI:</b> {md_inline(s["kpi"])}</div>']
    # headline (default view): required metrics' latest values + the KPI status
    heads = [t for t in tiles if t["required"]]
    vals = " · ".join(
        f'<b>{esc(t["value_text"])}</b> {esc(t["unit"])} <span class="mute">({esc(t["metric"])}, {esc(t["obs"])})</span>'
        if t["obs"] is not None else f'<span class="gap">{esc(t["metric"])}: no data yet</span>' for t in heads)
    status = (f'{dot(km["status"])}{esc(km["label"])} <span class="mute">· assessed {esc(km["made_at"])}</span>'
              if km and km["assessment_id"] else f'{dot(None)}<span class="gap">not yet assessed</span>')
    # details: every required/gap tile, the rest of the registry, the assessment, KPI-tagged events
    main = [t for t in tiles if t["required"] or t["status"] in ("overdue", "no data")]
    if not heads:
        main = tiles
    rest = [t for t in tiles if t not in main]
    body = []
    if not tiles:
        body.append(f'<div class="gap">no metrics registered yet (metrics/{esc(sec)}.csv)</div>')
    elif not heads:
        body.append('<div class="gap">no required KPI metric in the registry yet</div>')
    body.append('<div class="tiles">' + "".join(kpi_tile(db, t) for t in main) + "</div>")
    if rest:
        body.append(f"<details><summary>{len(rest)} more registered metric(s)</summary>"
                    '<div class="tiles">' + "".join(kpi_tile(db, t) for t in rest) + "</div></details>")
    body.append("<h4>Assessment</h4>" + (assessment_html(km) if km else '<div class="gap">not yet assessed</div>'))
    body.append(evidence_and_events(db, sec, "kpi", km, names, succ, shown))
    out.append(f'<details class="kpid"><summary>{"Now: " + vals if vals else "Now: —"}<span class="st">{status}</span>'
               f'</summary><div class="more">{"".join(body)}</div></details>')
    return "".join(out)


def section_html(db: sqlite3.Connection, s: sqlite3.Row, fsec: dict | None = None, n_recent: int = 8,
                 covered: bool = True) -> str:
    sec = s["section"]
    fsec = fsec or {}
    ms = db.execute("SELECT * FROM milestone_status WHERE section=? ORDER BY ord", (sec,)).fetchall()
    by_topic = {m["target"]: m for m in ms}
    names = {r["topic"]: r["name"] for r in db.execute("SELECT topic, name FROM topics WHERE section=?", (sec,))}
    # superseded id -> its effective successor (follow chains), so links always land on a shown event
    succ = dict(db.execute("SELECT id, superseded_by FROM events WHERE section=? AND NOT effective", (sec,)).fetchall())
    framework = bool(s["kpi"] or fsec.get("milestones") or fsec.get("challenges"))
    shown: set[str] = set()
    out = [f'<section id="{esc(sec)}"><h2>{esc(s["title"])}</h2>']
    if not covered:
        out.append('<div class="note">Not covered by this period\'s bulletins: shown is the ledger '
                   'as of the cutoff, for reference.</div>')
    out.append(md_block(fsec.get("intro")))
    if s["kpi"]:
        out.append(kpi_block(db, sec, s, ms, names, succ, shown))
    elif not framework:
        out.append('<div class="mute">Supplemental section: no KPI, milestones or challenges in the framework.</div>')
    for kind, title in (("milestone", "Milestone Countdown"),
                        ("challenge", fsec.get("challenges_heading") or "Major Open Challenges")):
        items = fsec.get(kind + "s") or []
        if not items:
            if framework:
                out.append(f'<h3>{esc(title)}</h3><div class="gap">none listed in the framework</div>')
            continue
        out.append(f'<h3>{md_inline(title)}</h3><ul class="topics">')
        out += [topic_li(db, sec, it, by_topic.get(f"{kind}:{it['slug']}"), kind, names, succ, shown) for it in items]
        out.append("</ul>")

    evs = db.execute("SELECT * FROM current_events WHERE section=? "
                     "ORDER BY known_at DESC, date_end DESC, significance DESC, id DESC", (sec,)).fetchall()
    if not evs:
        out.append('<div class="gap">no events in the ledger yet</div>')
        return "".join(out) + "</section>"
    beyond = topic_events(db, sec, "beyond")
    if beyond:
        out.append(f'<details class="news"><summary>Beyond the framework: {len(beyond)} event(s)</summary>'
                   f'<div class="more">{events_ul(beyond, names, succ, shown)}</div></details>')
    # events no framework topic lists (e.g. tags of a since-changed framework): never silently dropped
    other = [e for e in evs if e["id"] not in shown]
    if other:
        out.append(f'<details class="news"><summary>Events under no current topic: {len(other)}</summary>'
                   f'<div class="more">{events_ul(other, names, succ, shown)}</div></details>')
    out.append(f'<details class="news"><summary>Latest events (the {min(n_recent, len(evs))} most recently '
               f'known of {len(evs)})</summary><div class="more">{events_ul(evs[:n_recent], names, succ, shown)}'
               "</div></details>")
    return "".join(out) + "</section>"


def dashboard(as_of: dt.date, fw: dict | None = None, period: str | None = None,
              covered: set[str] | None = None, note: str = "", periods: list[str] = ()) -> str:
    """The published page: the framework (what we track and why) with the ledger's
    state as of `as_of`. period: a period page (frozen at its cutoff, `covered` =
    sections with a bulletin); periods: period pages to link from the live page."""
    fw = fw or ledger.framework()
    db = sqlite3.connect(":memory:")
    try:
        build_db(db, as_of, fw)
        db.row_factory = sqlite3.Row
        return _dashboard_html(db, as_of, fw, period, covered, note, periods)
    finally:
        db.close()


def legend_html() -> str:
    dots = "".join(f"<li>{dot(st)}<b>{esc(st)}</b>: {esc(w)}</li>" for st, w in STATUS_WORDS.items())
    return (
        '<details class="legend"><summary>How to read this page</summary><div class="more">'
        "<p>Each endeavor has a <b>KPI</b> (the needle we watch), a <b>milestone countdown</b> "
        "(concrete, checkable events) and <b>open challenges</b> (the problems standing in the way). "
        "Click any line to expand its detail: the precise criteria, the current assessment and "
        "its reasoning, and the evidence.</p>"
        f'<p>Status (KPIs and milestones), per the status rubric:</p><ul class="md">{dots}'
        f"<li>{dot(None)}<b>not yet assessed</b></li></ul>"
        "<p>A KPI's status is its <i>pace</i> toward the goal versus the pace the goal needs, not its level. "
        "A milestone's status is its evidence-based ETA. A status changes only on newer evidence.</p>"
        "<p>Everything shown comes from an append-only <b>ledger</b> of verified facts, each with its "
        "sources and the date it became public. "
        f'{badge("verified")} / {badge("corrected")}: checked against the source at intake. '
        f'{badge("legacy")}: converted from the first (2025) pilot report, not verified at ingest. '
        "“As of” means only what was public by that date is included.</p></div></details>")


def _dashboard_html(db: sqlite3.Connection, as_of: dt.date, fw: dict, period: str | None,
                    covered: set[str] | None, note: str, periods: list[str]) -> str:
    secs = {r["section"]: r for r in db.execute("SELECT * FROM sections ORDER BY ord")}
    one = lambda q: db.execute(q).fetchone()[0]
    n_ev, n_leg = one("SELECT COUNT(*) FROM current_events"), \
        one("SELECT COUNT(*) FROM current_events WHERE verification_status='legacy'")
    n_sup = one("SELECT COUNT(*) FROM events WHERE NOT effective")
    n_obs = one("SELECT COUNT(*) FROM observations")
    gaps = db.execute("SELECT * FROM gaps").fetchall()
    gap_li = "".join(f'<li><a href="#{esc(g["section"])}">{esc(g["section"])}</a>: {esc(g["metric"])}'
                     f'{" (required)" if g["required"] else ""} — <span class="gap">{esc(g["gap"])}</span></li>'
                     for g in gaps)
    body, nav = [], []
    for e in fw["endeavors"]:
        group = "sections" in e
        sub = e["sections"] if group else [e]
        anchor = sub[0]["id"]
        nav.append(f'<a href="#{esc(anchor)}">{esc(e["title"])}</a>')
        if group:
            body.append(f'<div class="group{" supp" if e.get("supplemental") else ""}">'
                        f'<h2 class="gh">{esc(e["title"])}</h2>{md_block(e.get("intro"))}')
        for fs in sub:
            if fs["id"] in secs:
                body.append(section_html(db, secs[fs["id"]], fs, covered=covered is None or fs["id"] in covered))
        if group:
            body.append("</div>")
    title = fw["title"] + (f" — {period}" if period else "")
    if period:
        when = (f'<div class="asof">Period page <b>{esc(period)}</b>: the ledger as of the period\'s cutoff '
                f'<b>{esc(as_of)}</b>, frozen. <a href="../">→ live dashboard</a></div>')
    else:
        when = f'<div class="asof">Live ledger state as of <b>{esc(as_of)}</b>.</div>'
    stats = (f'<div class="mute small">{n_ev} events ({n_ev - n_leg} verified, {n_leg} legacy'
             f"{f'; {n_sup} superseded not shown' if n_sup else ''}) · {n_obs} observations · "
             f"{len(gaps)} metric gap(s)</div>")
    per = ("<p>Earlier periods: " + " · ".join(f'<a href="{esc(p)}/">{esc(p)}</a>' for p in periods) + "</p>"
           if periods else "")
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{esc(title)} (as of {esc(as_of)})</title><style>{CSS}</style></head><body>"
            f'<header><h1>{esc(title)}</h1><div class="tagline">{md_inline(fw["tagline"])}</div>{when}'
            f'{f"<div class=note>{md_inline(note)}</div>" if note else ""}'
            f"<nav>{''.join(nav)}</nav></header><main>"
            f'<div class="manifesto">{md_block(fw["manifesto"])}</div>{legend_html()}'
            + "".join(body)
            + '<footer>' + stats
            + (f"<details><summary>Data gaps ({len(gaps)})</summary><ul>{gap_li}</ul></details>" if gaps else "")
            + per
            + '<p class="mute small">Generated by views/explore.py from the Grand Endeavors ledger '
              '(<a href="https://github.com/pasky/grand-endeavors-data">data</a>, '
              '<a href="https://github.com/pasky/grand-endeavors">code and definitions</a>'
            + ('' if period else ', <a href="ledger.sqlite">ledger.sqlite</a> for Datasette')
            + ").</p></footer></main></body></html>\n")


# --- pages: live, period, site ------------------------------------------------------------
PAGE = "index.html"


def period_dirs() -> list[str]:
    """Period dirs in the data repo that have a frozen page (newest first by cutoff)."""
    out = []
    for d in sorted(os.listdir(ledger.DATA)) if os.path.isdir(ledger.DATA) else []:
        if os.path.isfile(os.path.join(ledger.DATA, d, PAGE)):
            try:
                out.append((ledger.cutoff(d.removeprefix("pilot-")), d))
            except ValueError:
                warn(f"{d}/{PAGE}: not a period dir name, not linked")
    return [d for _, d in sorted(out, reverse=True)]


def period_page(period_dir: str, note: str = "", force: bool = False) -> str:
    """Freeze <period-dir>/index.html: the dashboard as of the period's cutoff, with
    the framework of that period (<period-dir>/framework.yaml; copied from the
    mechanism repo on the first run, then kept). An existing page is frozen: it is
    replaced only with force (a regenerated one may differ, see views/EXPLORER.md;
    give it a note saying so). Returns the page path."""
    import shutil
    name = os.path.basename(os.path.normpath(period_dir))
    out = os.path.join(period_dir, PAGE)
    if os.path.exists(out) and not force:
        raise ValueError(f"{out} exists and is frozen (regenerate with --force, and a --note saying why)")
    cut = ledger.cutoff(name.removeprefix("pilot-"))
    fw_path = os.path.join(period_dir, "framework.yaml")
    if not os.path.exists(fw_path):
        shutil.copy(os.path.join(ledger.ROOT, "framework.yaml"), fw_path)
    fw = ledger.framework(period_dir)
    covered = {s for s in ledger.SECTIONS
               if os.path.isfile(p := os.path.join(period_dir, f"{s}.md")) and os.path.getsize(p) > 0}
    page = dashboard(cut, fw, period=name, covered=covered, note=note)  # render first, then replace atomically
    with open(out + ".tmp", "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(out + ".tmp", out)
    return out


def site(out_dir: str, as_of: dt.date) -> list[str]:
    """The published directory: index.html (live), the frozen period pages
    (<period>/index.html, copied from the data repo), ledger.sqlite + metadata.json,
    and dashboard.html redirecting to the old URL's successor."""
    import shutil
    os.makedirs(out_dir, exist_ok=True)
    periods = period_dirs()
    written = []
    for d in periods:
        os.makedirs(os.path.join(out_dir, d), exist_ok=True)
        shutil.copy(os.path.join(ledger.DATA, d, PAGE), os.path.join(out_dir, d, PAGE))
        written.append(os.path.join(out_dir, d, PAGE))
    page = dashboard(as_of, periods=periods)
    tmp = os.path.join(out_dir, PAGE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(page)
    os.replace(tmp, os.path.join(out_dir, PAGE))
    with open(os.path.join(out_dir, "dashboard.html"), "w", encoding="utf-8") as f:
        f.write('<!DOCTYPE html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=./">'
                '<title>Moved</title><a href="./">Grand Endeavors dashboard</a>\n')
    written += [os.path.join(out_dir, PAGE), build(out_dir, as_of)]
    return written


# --- CLI ----------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--out", default=os.path.join(ledger.ROOT, "build"))
    d = sub.add_parser("dashboard"); d.add_argument("--out", default=os.path.join(ledger.ROOT, "build", PAGE))
    st = sub.add_parser("site"); st.add_argument("--out", default=os.path.join(ledger.ROOT, "build"))
    for p in (b, d, st):
        p.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date.today(), help="YYYY-MM-DD (default: today)")
    pp = sub.add_parser("period"); pp.add_argument("period_dir")
    pp.add_argument("--note", default="", help="a remark shown under the page header (Markdown)")
    pp.add_argument("--force", action="store_true", help="replace an existing (frozen) page")
    a = ap.parse_args()
    try:
        if a.cmd == "build":
            p = build(a.out, a.as_of)
            db = sqlite3.connect(p)
            counts = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("current_events", "observations", "current_obs", "assessments", "metrics", "gaps")}
            counts["superseded_events"] = db.execute("SELECT COUNT(*) FROM events WHERE NOT effective").fetchone()[0]
            db.close()
            print(f"wrote {p} (+ metadata.json) as of {a.as_of}: {counts}")
        elif a.cmd == "dashboard":
            os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(dashboard(a.as_of, periods=period_dirs()))
            print(f"wrote {a.out} as of {a.as_of}")
        elif a.cmd == "site":
            for p in site(a.out, a.as_of):
                print(f"wrote {p}")
        else:
            print(f"wrote {period_page(a.period_dir, a.note, a.force)}")
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
