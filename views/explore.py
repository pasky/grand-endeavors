#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
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
        -> self-contained static HTML (no JS, no external CSS/CDN): the front page, i.e.
           the framework (framework.yaml: manifesto, definitions) with the ledger's
           state: endeavor navigation | the overview or one endeavor (pure-CSS :target
           switching) | the news stream; every item expands to its detail (cited
           evidence + the latest TOPIC_EVENTS other events per topic); plus, next to
           it, one event log per section (events-<section>.html: every event once)
  explore.py site [--out build/] [--as-of YYYY-MM-DD]
        -> the published directory: index.html + event logs (live) + <period>/ (frozen
           period pages from the data repo) + ledger.sqlite + metadata.json
  explore.py period <period-dir> [--note TEXT] [--force]
        -> <period-dir>/index.html + event logs, frozen: the pages as of the period's cutoff, with
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
import math
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
import kpi  # noqa: E402
import kpi_charts  # noqa: E402
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
    deployment JSON, PRIMARY KEY (section, id));
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
                    "(metric, obs): highest (tier, known_at, retrieved). verification='withdrawn' rows are "
                    "withdrawal records: their value (for that metric, obs) is never effective once known.",
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
                           int(id(e) in live), e.get("_line"), _j(e.get("deployment"))))
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
--unk:#9aa1ad;--legacy:#975a16;--notebg:#fffaf0;--noteln:#f6e05e;--side:#eef0f4;--sel:#dde7f5;--hov:#e4e8ee}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--card:#1b1f27;--ink:#e3e7ee;--mute:#949cad;--line:#2e3440;
--green:#38b26a;--yellow:#e0ac45;--red:#e36363;--gap:#e06aaa;--acc:#6aa8ec;--tile:#20252e;--gapbg:#2a1b24;
--chip:#2c333f;--unk:#6b7280;--legacy:#e0a960;--notebg:#2a2416;--noteln:#8a7424;--side:#161a21;--sel:#22324a;
--hov:#1f2530}}
*{box-sizing:border-box}html{scroll-padding-top:12px}
body{margin:0;font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink);
display:grid;grid-template-columns:288px minmax(0,1fr) 340px;align-items:start}
.mute{color:var(--mute)}a{color:var(--acc)}
/* left: endeavor navigation */
.side{position:sticky;top:0;height:100vh;overflow-y:auto;background:var(--side);border-right:1px solid var(--line);
padding:12px 10px 16px}
.brand{display:block;text-decoration:none;color:var(--ink);padding:4px 8px 10px;font-size:16px}
.brand span{display:block;font-weight:400}
.ng{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:12px 8px 3px}
.ng.sp{margin:6px 0 0}
.nv{display:block;text-decoration:none;color:var(--ink);padding:6px 8px;border-radius:8px;
border:1px solid transparent;margin:1px 0}.nv:hover{background:var(--hov)}
.nt{display:flex;align-items:center;gap:6px;font-weight:600}.nn{flex:1}
.nk,.nd{display:flex;align-items:center;font-size:12px;margin:2px 0 0 26px;color:var(--mute)}
.nk .hv b{color:var(--ink)}.nk .hv{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nk .spark,.cv .spark{display:inline-block;margin:0 0 0 auto;vertical-align:middle;flex:none}
.nd .dot{width:9px;height:9px;margin-right:3px}.ncov{opacity:.55}
.ic{display:inline-block;min-width:1.35em;text-align:center}
.rc{flex:none;font-size:11px;font-weight:600;border-radius:9px;padding:0 6px;white-space:nowrap}
.r-hot{background:var(--acc);color:var(--card)}.r-warm{background:var(--sel);color:var(--acc)}
.r-cold{color:var(--mute);font-weight:400;border:1px solid var(--line)}
.nvg{margin:1px 0}.nv.sub{margin-left:18px;padding:4px 8px;border-left:2px solid var(--line);border-radius:0 8px 8px 0}
.nv.sub .nt{font-weight:500;font-size:13px}.nv.sub .nk,.nv.sub .nd{margin-left:26px}
.ax{font-size:9px;fill:var(--mute)}
.sp rect{fill:transparent}.sp circle,.sp text{pointer-events:none}.sp circle{fill:var(--card);stroke:currentColor;stroke-width:1.5;opacity:0}.sp text{font-size:9.5px;font-weight:600;fill:var(--ink);opacity:0}
.sp:hover circle,.sp:hover text{opacity:1}.spark:has(.sp:hover) .ax{opacity:0}
.nleg{margin:18px 8px 0;display:grid;grid-template-columns:1fr 1fr;gap:2px 8px}.nleg .dot{width:9px;height:9px;margin-right:5px}
.nleg p{grid-column:1/-1;margin:4px 0 0}
/* center */
main{min-width:0;max-width:1060px;width:100%;margin:0 auto;padding:18px 28px}
.pane{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 22px;margin:0 0 18px}
#intro{background:none;border:0;padding:0}
.hero h1{margin:0 0 4px;font-size:28px}.tagline{font-size:17px;margin:2px 0 6px}.asof{margin:4px 0;color:var(--mute)}
.banner{background:var(--notebg);border:1px solid var(--noteln);border-radius:8px;padding:8px 12px;margin:0 0 14px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px}
.card.wide{grid-column:1/-1}@media (min-width:900px){.card.wide{grid-column:span 2}}.trks{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:4px 24px}
.trk{display:flex;flex-direction:column;gap:4px}.tt{font-weight:700;font-size:14px;margin-top:4px}
.ct{display:flex;align-items:center;gap:6px}.actw{display:inline-flex;align-items:flex-end;gap:6px;font-size:11px;color:var(--mute);white-space:nowrap}
.card{display:flex;flex-direction:column;gap:4px;text-decoration:none;color:var(--ink);background:var(--card);
border:1px solid var(--line);border-radius:12px;padding:12px 14px;transition:border-color .15s,transform .15s}
.card:hover{border-color:var(--acc);transform:translateY(-1px)}
.ct{font-size:17px;font-weight:700}.ck{font-size:12px;color:var(--mute)}
.cv{display:flex;align-items:center;gap:8px}.cv .hv b{font-size:22px}
.cs{font-size:12.5px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.cm{font-size:13px;margin:4px 0 0}.cm li{padding:1px 0}
.ci,.cn{font-size:13px;margin:0 0 4px;padding-left:16px}.ci li,.cn li{padding:1px 0}.ci .hv b{font-size:15px}
.cn li{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.cf{margin-top:auto;padding-top:6px;font-size:12px;color:var(--mute);
display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:4px 8px}.act{flex:none;fill:var(--acc);opacity:.8}.act .z{fill:var(--line)}
.crumb{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute)}
.pane h2{margin:0;font-size:22px}.track{border-top:1px solid var(--line);margin-top:22px;padding-top:16px}
.track h2{font-size:19px}.jump{margin:10px 0 0;font-size:13px}.jump a{text-decoration:none;margin-right:6px}.strip{display:flex;align-items:flex-end;gap:10px;color:var(--mute);font-size:12.5px;margin:2px 0 8px}
.gintro{color:var(--mute);border-left:3px solid var(--line);padding-left:10px;margin:8px 0}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);margin:20px 0 6px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px;margin:8px 0}
.tile{border:1px solid var(--line);border-radius:8px;padding:10px;background:var(--tile)}
.tile .m{font-weight:600;font-size:12px;word-break:break-word}.tile .v{font-size:24px;font-weight:700}
.tile .v small{font-size:13px;color:var(--mute);font-weight:400}.tile .d,.tile .c{font-size:12px;color:var(--mute)}
.up,.down{color:var(--ink)}.spark{display:block;margin:4px 0;color:var(--acc)}
.gap{color:var(--gap);font-weight:700}.tile.nodata,.tile.overdue{border:2px dashed var(--gap);background:var(--gapbg)}
.badge{display:inline-block;font-size:11px;border-radius:4px;padding:0 5px;margin-left:4px;
border:1px solid currentColor;vertical-align:1px}.b-legacy{color:var(--legacy);background:var(--notebg)}
.b-verified,.b-corrected,.b-collector{color:var(--green)}.b-req{color:var(--acc)}
.nc{opacity:.75}.b-nc{color:var(--mute);font-size:10px}
.dot{display:inline-block;flex:none;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:0}
.mo{display:inline-flex;flex:none;align-items:center;justify-content:center;width:20px;height:20px;border-radius:50%;
margin-right:6px;font-size:12px;line-height:1;vertical-align:-4px}.m-green{background:color-mix(in srgb,var(--green) 28%,transparent)}
.m-yellow{background:color-mix(in srgb,var(--yellow) 32%,transparent)}.m-red{background:color-mix(in srgb,var(--red) 28%,transparent)}
.m-unknown{background:color-mix(in srgb,var(--unk) 40%,transparent)}
.s-green{background:var(--green)}.s-yellow{background:var(--yellow)}.s-red{background:var(--red)}.s-achieved{background:var(--green) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'%3E%3Cpath d='M2.5 5.2l1.8 1.8 3.3-3.6' fill='none' stroke='white' stroke-width='1.6'/%3E%3C/svg%3E") center/100% no-repeat}.s-unknown{background:var(--unk)}
.s-none{border:2px dashed var(--mute)}ul{padding-left:0;list-style:none;margin:0}
li.ms,li.ev{padding:5px 0;border-bottom:1px solid var(--line)}li.ev .meta{font-size:12px;color:var(--mute)}
li.ev:target{background:var(--sel);outline:2px solid var(--acc);border-radius:6px;padding:5px 8px}
.chip{font-size:11px;background:var(--chip);border-radius:3px;padding:0 4px;margin-right:3px}
.sig3{font-weight:600}.rel{font-size:12px;color:var(--mute);margin-left:12px}
details summary{cursor:pointer;color:var(--acc);margin:6px 0}
details>summary{position:relative;padding:5px 8px 5px 38px;margin:2px 0 2px -8px;border-radius:8px}
details>summary:hover{background:var(--hov)}
.small{font-size:12px}.note{background:var(--notebg);border:1px solid var(--noteln);border-radius:6px;padding:6px 10px;margin:8px 0}
.manifesto p{font-size:15px;margin:8px 0}.legend{margin:8px 0 4px}.more{padding:4px 0 8px 26px}
section p{margin:6px 0}.kpi{margin:10px 0 2px}
table.cases{border-collapse:collapse;width:100%;margin:4px 0 8px;font-size:13px}
table.cases th,table.cases td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
details summary{list-style:none}details summary::-webkit-details-marker{display:none}
/* the expander: a chevron (an SVG mask, so it takes the theme colour) in a round button; turns down when open */
details>summary::before,details>summary::after{content:"";position:absolute;left:6px;top:4px;width:24px;height:24px}
details>summary::before{border-radius:50%;background:var(--sel);transition:background .15s}
details>summary::after{background:var(--acc);transition:transform .15s;
-webkit-mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M10 7.5l4.5 4.5-4.5 4.5' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center/24px no-repeat;
mask:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M10 7.5l4.5 4.5-4.5 4.5' fill='none' stroke='black' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E") center/24px no-repeat}
details>summary:hover::before{background:var(--acc)}details>summary:hover::after{background:var(--card)}
details[open]>summary::after{transform:rotate(90deg)}
li.topic summary,.kpid summary{color:var(--ink)}
li.topic{border-bottom:1px solid var(--line)}ul.topics{margin:0 0 4px}
/* milestones: a sequence = a numbered rail; parallel = cards in columns of >=280px (an open one
   takes a row of its own; the cards before it fill their row, the trailing ones keep the column width) */
ol.topics{list-style:none;padding:0;margin:4px 0;counter-reset:step}
ol.seq>li.topic{position:relative;padding-left:32px;counter-increment:step;border:0}
ol.seq>li.topic::before{content:counter(step);position:absolute;left:0;top:7px;width:22px;height:22px;
border:2px solid var(--mute);border-radius:50%;color:var(--mute);font:700 12px/18px system-ui,sans-serif;text-align:center}
ol.seq>li.topic:not(:last-child)::after{content:"";position:absolute;left:10px;top:31px;bottom:-5px;width:2px;background:var(--line)}
ul.par{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0;container-type:inline-size}
ul.par>li.topic{flex:0 0 100%;min-width:0;border:1px solid var(--line);border-radius:10px;padding:0 10px 0 8px;background:var(--tile)}
@container (min-width:568px){ul.par>li.topic{flex-basis:calc((100% - 8px)/2 - .1px)}}
@container (min-width:856px){ul.par>li.topic{flex-basis:calc((100% - 16px)/3 - .1px)}}
@container (min-width:1144px){ul.par>li.topic{flex-basis:calc((100% - 24px)/4 - .1px)}}
ul.par>li.topic:has(~li.topic details[open]){flex-grow:1}
ul.par>li.topic:has(details[open]){flex-basis:100%}
/* the milestone timeline */
.ec{position:relative;--lw:12em;margin:8px 0 6px;font-size:13px}
.eg{position:absolute;top:0;bottom:18px;left:calc(var(--lw) + 8px);right:8px;pointer-events:none}
.eg i{position:absolute;top:0;bottom:0;width:1px;background:var(--line)}
.eg .lz{position:absolute;top:0;bottom:0;right:0;background:repeating-linear-gradient(135deg,transparent 0 4px,var(--line) 4px 5px);opacity:.6}
.er{display:grid;grid-template-columns:var(--lw) 1fr;align-items:center;height:26px}
.en{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:right;padding-right:10px;
font-weight:600;color:var(--ink);text-decoration:none}.en:hover{color:var(--acc)}
.et{position:relative;height:100%;margin:0 8px}
.e-green{--c:var(--green)}.e-yellow{--c:var(--yellow)}.e-red{--c:var(--red)}.e-achieved{--c:var(--green)}
.e-unknown,.e-none{--c:var(--unk)}
.eb{position:absolute;top:50%;height:6px;margin-top:-3px;border-radius:3px;background:var(--c);opacity:.35}
.ed{position:absolute;top:50%;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;background:var(--c);
border:2px solid var(--c);box-sizing:border-box}.ed.ho{background:var(--card)}
.ena{position:absolute;top:50%;transform:translateY(-50%);color:var(--mute);font-size:12px}
.dep{position:absolute;top:-7px;height:7.75px;margin-left:-.75px;border:0 solid var(--mute);border-width:0 0 1.5px 1.5px}
.dep.bk{border-width:0 1.5px 1.5px 0}
.dpa{position:absolute;top:0;margin-left:-4px;border:4px solid transparent;border-top:6.5px solid var(--mute);border-bottom:0}
.ea{height:18px}.ea .et span{position:absolute;top:2px;transform:translateX(-50%);font-size:11px;color:var(--mute);white-space:nowrap}
.nd.seq .dot{margin-right:0}.nd .lk{display:inline-block;width:6px;height:2px;background:var(--mute);margin:0 1px}
.cm.seq li{position:relative}.cm.seq li:not(:last-child)::after{content:"";position:absolute;left:4px;top:16px;height:8px;width:2px;background:var(--mute)}
.st{display:block;font-size:13px}ul.md{list-style:disc;padding-left:22px;margin:4px 0}
h4{font-size:12px;color:var(--mute);margin:10px 0 4px}.ass{margin:6px 0}
dl.basis{display:grid;grid-template-columns:max-content 1fr;gap:2px 10px;font-size:13px;margin:6px 0}
dl.basis dt{color:var(--mute)}dl.basis dd{margin:0;min-width:0}.b-cited{color:var(--acc)}
dl.basis.sub{margin:0 0 4px;padding-left:8px;border-left:2px solid var(--line);grid-template-columns:fit-content(13em) minmax(0,1fr)}
dl.basis dt{overflow-wrap:anywhere}
.ser{display:flex;flex-wrap:wrap;gap:2px;margin:2px 0}.ser>span{border:1px solid var(--line);border-radius:4px;
padding:0 5px;font-size:12px;text-align:right;line-height:1.35}.ser i{display:block;font-style:normal;font-size:10.5px;color:var(--mute)}
.kst{margin:8px 0 2px;font-size:15px}p.why{margin:4px 0 8px}
.about .md p{margin:6px 0}.about .md li{margin:3px 0}h4.ab{font-size:14px;color:var(--ink);margin:16px 0 4px}
.khead{display:grid;grid-template-columns:minmax(200px,260px) 1fr;gap:14px;align-items:start;margin:6px 0}.khead .tiles{margin:0;grid-template-columns:1fr}.khead .kst{margin-top:0}
@media (max-width:780px){.khead{grid-template-columns:1fr}}
footer{margin:24px 0}.news{margin-top:10px}li.ev.ref,li.ev.more-ev{font-size:13px;padding:3px 0}
/* event log pages: one plain column */
body.log{display:block}body.log header,body.log main{max-width:980px;margin:0 auto;padding:16px}
body.log header h1{margin:0 0 4px;font-size:22px}body.log nav a{margin-right:10px;white-space:nowrap}
/* right: news stream */
.stream{position:sticky;top:0;height:100vh;overflow-y:auto;border-left:1px solid var(--line);background:var(--side);
padding:12px 12px 16px}
.stream h3{margin:4px 0 0;color:var(--ink)}.sh{margin-bottom:6px}
.sf{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:12px;color:var(--mute);margin:0 0 6px}.sf input{margin:0 3px 0 0;vertical-align:-2px}
.dh{position:sticky;top:-12px;background:var(--side);font-size:12px;font-weight:600;padding:8px 2px 3px;z-index:1}
.si a{display:block;text-decoration:none;color:var(--ink);padding:6px 8px;margin:2px 0;border-radius:8px;
background:var(--card);border:1px solid var(--line);transition:opacity .15s}.si a:hover{border-color:var(--acc)}
.si .sm{display:block;font-size:11px;color:var(--mute);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.si .cl{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;font-size:12.5px}
.si.sig3 .cl{font-weight:600}.si.chg a{border-left:3px solid var(--acc)}.si.chg .dot{width:9px;height:9px;margin:0 3px}
.si.sig1 .cl{color:var(--mute)}
/* pure-CSS pane switching: one endeavor at a time (browsers without :has() show them all) */
@supports selector(:has(a)){
.pane{display:none}.pane:target,.pane:has(:target){display:block}
body:not(:has(.pane:target,.pane :target)) #intro{display:block}
body:not(:has(.pane:target,.pane :target)) .nv.ov,body:has(#intro:target) .nv.ov{background:var(--sel);border-color:var(--acc)}
.here{display:none}body:has(.pane:not(#intro):target,.pane:not(#intro) :target) .here{display:inline}
.stream:has(#f-major:checked) .si:is(.sig0,.sig1,.sig2),
.stream:has(#f-major:checked) .dg:not(:has(.sig3,.chg)){display:none}}
@media (max-width:1280px){body{grid-template-columns:248px minmax(0,1fr)}
.stream{grid-column:2;position:static;height:auto;border-left:0;background:none;padding:0 28px 24px}
.dh{position:static;background:none}}
@media (max-width:780px){html{scroll-padding-top:64px}.ec{--lw:8.5em}.ea .mn{display:none}body{display:block}main{padding:12px}
.side{position:sticky;top:0;z-index:5;height:auto;display:flex;overflow-x:auto;gap:4px;padding:6px;
border-right:0;border-bottom:1px solid var(--line)}
.brand,.ng,.nleg,.nk{display:none}.nv{flex:none;padding:4px 8px}.nd{margin-left:26px}
.nvg{display:contents}.nv.sub{margin:1px 0;border-left:0;border-radius:8px}.nv.sub .nd{margin-left:26px}
.stream{padding:0 12px 24px}.pane{padding:12px 14px}}
""" + kpi_charts.CSS


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def link(url, text) -> str:
    if url and ledger.URL_RE.match(str(url)):
        return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(text)}</a>'
    return esc(text)


def badge(status) -> str:
    return f'<span class="badge b-{esc(status)}">{esc(status or "unverified")}</span>'


def _metric_labels() -> dict[str, dict[str, str]]:
    import yaml
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "metric-labels.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


METRIC_LABELS = _metric_labels()
METRIC_INPUTS: dict[str, list[str]] = METRIC_LABELS.pop("_inputs", None) or {}  # section -> fine-print metrics
METRIC_LEVELS: dict[str, list[str]] = METRIC_LABELS.pop("_levels", None) or {}  # metric -> name of level 1, 2, ...


def label_order(sec: str, rows: list) -> list:
    """Metric rows in the section's metric-labels.yaml order (the reading order), unlabelled
    ones last in their given order."""
    pos = {m: i for i, m in enumerate(METRIC_LABELS.get(sec) or {})}
    return sorted(rows, key=lambda t: pos.get(t["metric"], len(pos)))

_UNLABELLED: set[tuple[str, str]] = set()


def metric_label(sec: str, metric: str, definition: str | None = None) -> str:
    """The display name of a metric (views/metric-labels.yaml); without one, the first
    clause of its registry definition (else its id), with a warning."""
    lab = (METRIC_LABELS.get(sec) or {}).get(metric)
    if lab:
        return lab
    if (sec, metric) not in _UNLABELLED:
        _UNLABELLED.add((sec, metric))
        warn(f"views/metric-labels.yaml: no label for {sec}/{metric} (shown by its definition or id)")
    first = re.split(r";|:\s| \(|, ", str(definition or ""), maxsplit=1)[0].strip()
    if len(first) > 70:
        first = first[:68].rsplit(" ", 1)[0] + "…"
    return first or metric


MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_date(d) -> str:
    """2026-09-07 -> 7 Sep 2026."""
    d = D(str(d)) if not isinstance(d, dt.date) else d
    return f"{d.day} {MON[d.month - 1]} {d.year}"


def fmt_period(obs) -> str:
    """An observation period for humans: 2026-08 -> Aug 2026, 2025-Q4 -> Q4 2025, 2026 -> 2026."""
    s = str(obs)
    if m := re.fullmatch(r"(\d{4})-(\d{2})", s):
        return f"{MON[int(m[2]) - 1]} {m[1]}"
    if m := re.fullmatch(r"(\d{4})-([QH]\d)", s):
        return f"{m[2]} {m[1]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return fmt_date(s)
    return s


SPARK_HOVER = 60  # most hover targets per sparkline (a long series is thinned evenly: page weight)


def spark_label(d: dt.date, kind: str) -> str:
    """A point's date as its series counts it: 2026, Mar 2026, 22 Sep 2026."""
    return str(d.year) if kind == "annual" else f"{MON[d.month - 1]} {d.year}" if kind == "monthly" else fmt_date(d)


def sparkline(points: list[tuple[dt.date, float]], kind: str = "", w: int = 200, h: int = 34, pad: int = 3,
              axis: str = "below", fmt=None) -> str:
    """A line of the series; axis: "below" = its first and last date under the line,
    "left" = the first year left of it (tiny ones), "" = none. Hovering shows a point: a
    vertical strip per point (at most SPARK_HOVER) marks the point and writes its value and date
    in place of the axis labels (axis "below"), or carries them as a tooltip (the tiny ones);
    pure CSS, no script.
    fmt: value -> display text (with its unit)."""
    if len(points) < 2:
        return ""
    (a, _), (b, _) = points[0], points[-1]
    short = (lambda d: str(d.year)) if (b - a).days >= 700 else (lambda d: f"{MON[d.month - 1]} {d.year % 100:02d}")
    lw = 24 if axis == "left" else 0
    th = h + (11 if axis == "below" else 0)
    x0, x1 = a.toordinal(), b.toordinal()
    lo, hi = min(v for _, v in points), max(v for _, v in points)
    sx = lambda d: lw + pad + (w - lw - 2 * pad) * ((d.toordinal() - x0) / (x1 - x0) if x1 > x0 else 0.5)
    sy = lambda v: h - pad - (h - 2 * pad) * ((v - lo) / (hi - lo) if hi > lo else 0.5)
    pts = " ".join(f"{sx(d):.1f},{sy(v):.1f}" for d, v in points)
    d, v = points[-1]
    labels = ""
    if axis == "below":
        labels = (f'<text x="{pad}" y="{th - 1}" class="ax">{short(a)}</text>'
                  f'<text x="{w - pad}" y="{th - 1}" class="ax" text-anchor="end">{short(b)}</text>')
    elif axis == "left":
        labels = f'<text x="0" y="{h / 2 + 3:.1f}" class="ax">{a.year}</text>'
    fmt = fmt or (lambda x: f"{x:.4g}")
    n = len(points)
    idx = sorted({round(i * (n - 1) / (SPARK_HOVER - 1)) for i in range(SPARK_HOVER)}) if n > SPARK_HOVER else range(n)
    hov = []
    xs = [sx(points[i][0]) for i in idx]
    for j, i in enumerate(idx):
        pd_, pv = points[i]
        left = lw if j == 0 else (xs[j - 1] + xs[j]) / 2
        right = w if j == len(xs) - 1 else (xs[j] + xs[j + 1]) / 2
        txt = f"{fmt(pv)} · {spark_label(pd_, kind)}"
        mark = ""
        if axis == "below":
            anchor = "start" if xs[j] < w * .34 else "end" if xs[j] > w * .66 else "middle"  # labels fit
            mark = (f'<circle cx="{xs[j]:.1f}" cy="{sy(pv):.1f}" r="3"/>'
                    f'<text x="{xs[j]:.1f}" y="{th - 1}" text-anchor="{anchor}">{esc(txt)}</text>')
        tip = "" if mark else f"<title>{esc(txt)}</title>"  # a visible label needs no tooltip too
        hov.append(f'<g class="sp">{tip}<rect x="{left:.1f}" width="{max(right - left, .5):.1f}" height="{th}"/>{mark}</g>')
    return (f'<svg class="spark" width="{w}" height="{th}" viewBox="0 0 {w} {th}" role="img">'
            f'<title>{n} {esc(kind + " " if kind else "")}values, {a} to {d}; '
            f'range {lo:g} to {hi:g}</title>{labels}'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="1.5"/>'
            f'<circle cx="{sx(d):.1f}" cy="{sy(v):.1f}" r="2.5" fill="currentColor"/>{"".join(hov)}</svg>')


def ladder_rung(value_text, metric: str | None) -> int | None:
    """The rung (1 = lowest) a ladder metric's value stands for (metric-labels.yaml _levels),
    None for any other metric or a value off the ladder."""
    levels = METRIC_LEVELS.get(metric or "")
    try:
        n = int(float(value_text)) if levels else 0
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= len(levels or []) else None


def ladder_html(value_text, metric: str) -> str:
    """A ladder metric's rungs, lowest first, the ones reached in bold (empty for any other
    metric)."""
    if (n := ladder_rung(value_text, metric)) is None:
        return ""
    steps = [f'<b>{esc(x)}</b>' if i < n else f'<span class="mute">{esc(x)}</span>'
             for i, x in enumerate(METRIC_LEVELS[metric])]
    return (f'<div class="d" title="the ladder, lowest rung first; reached so far in bold">'
            f'rung {n} of {len(steps)}: {" → ".join(steps)}</div>')


def human_value(value_text, unit, metric: str | None = None) -> tuple[str, str]:
    """A value in a readable unit: minutes from 2 hours on as hours (METR task horizons:
    1044.78 min -> 17.4 hours); hours (task horizons: 9.567 h) as hours, under 1 hour as minutes
    (1.79 h stays 1.8 hours, as the assessment label quotes it); a level of a ladder
    (metric-labels.yaml _levels) as its rung's name."""
    if (n := ladder_rung(value_text, metric)) is not None:
        return METRIC_LEVELS[metric][n - 1], ""
    if unit in ("min", "minutes", "h"):
        try:
            v = float(value_text) * (60 if unit == "h" else 1)
        except (TypeError, ValueError):
            return str(value_text), unit
        if v >= (60 if unit == "h" else 120):
            return f"{v / 60:.1f}" if v < 6000 else f"{v / 60:.0f}", "hours"
        if unit == "h":
            return f"{v:.0f}", "min"
    return str(value_text), unit


def kpi_tile(db: sqlite3.Connection, k: sqlite3.Row) -> str:
    """A metric: its name (id + definition as the tooltip), the latest value, the period
    it is for, its source, the like-for-like change of a monthly series, the series,
    and when the next value is due."""
    head = (f'<div class="m" title="{esc(k["metric"])}: {esc(k["definition"])}">'
            f'{esc(metric_label(k["section"], k["metric"], k["definition"]))}</div>')
    if k["obs"] is None:
        return (f'<div class="tile nodata">{head}<div class="v gap">—</div>'
                f'<div class="gap">no data yet</div><div class="d">{esc(k["unit"])}, {esc(k["cadence"])}</div></div>')
    v, u = human_value(k["value_text"], k["unit"], k["metric"])
    body = (f'<div class="v" title="{esc(k["value_text"])} {esc(k["unit"])}">{esc(v)} <small>{esc(u)}</small></div>'
            + ladder_html(k["value_text"], k["metric"]) +
            f'<div class="d"><span title="published {esc(k["known_at"])}">{esc(fmt_period(k["obs"]))}</span> · '
            f'{link(k["source"], "source")}{badge("legacy") if k["verification"] == "legacy" else ""}</div>')
    if k["year_ago_obs"] is not None and k["unit"] != "doublings":  # monthly: the like-for-like change (the
        # seasonal cycle cancels); not for a gap series (a cross-check's residual has no year-on-year meaning)
        body += (f'<div class="c" title="{esc(fmt_period(k["year_ago_obs"]))}: {esc(k["year_ago_value_text"])}">'
                 f'{_arrow(k["year_ago_change_text"])} vs {esc(fmt_period(k["year_ago_obs"]))}</div>')
    body += sparkline(*spark_points(db, k), fmt=lambda x: " ".join(human_value(f"{x:.6g}", k["unit"], k["metric"])))
    if k["overdue"]:
        body += f'<div class="gap">update overdue since {esc(fmt_date(k["next_expected"]))}</div>'
    elif k["next_expected"]:
        body += f'<div class="d">next update due by {esc(fmt_date(k["next_expected"]))}</div>'
    elif k["cadence"] == "irregular":
        body += '<div class="d">updated irregularly</div>'
    return f'<div class="tile{" overdue" if k["overdue"] else ""}">{head}{body}</div>'


def _arrow(change_text: str) -> str:
    v = float(change_text)
    cls, arrow = ("up", "▲") if v > 0 else ("down", "▼") if v < 0 else ("", "=")
    return f'<span class="{cls}">{arrow} {esc(change_text)}</span>'


KIND_NAMES = {"9999": "annual", "9999-99": "monthly", "9999-99-99": "daily",
              "9999-Q9": "quarterly", "9999-H9": "half-yearly"}


def spark_points(db: sqlite3.Connection, k: sqlite3.Row) -> tuple[list[tuple[dt.date, float]], str]:
    """Headline series of ONE granularity (never e.g. daily mixed with monthly): among those
    with >= 2 points, the one spanning the longest period (ties: more points, then the
    headline's own), so a few recent day points never hide years of monthly history; with
    none, the dominant one."""
    kinds = db.execute("SELECT obs_kind, COUNT(*), julianday(MAX(obs_end)) - julianday(MIN(obs_start)) "
                       "FROM headline_obs WHERE section=? AND metric=? GROUP BY obs_kind "
                       "ORDER BY COUNT(*) DESC, obs_kind", (k["section"], k["metric"])).fetchall()
    if not kinds:
        return [], ""
    multi = [x for x in kinds if x[1] >= 2]
    kind = (max(multi, key=lambda x: (x[2], x[1], x[0] == k["obs_kind"]))[0] if multi else kinds[0][0])
    pts = [(dt.date.fromisoformat(r[0]), r[1]) for r in db.execute(
        "SELECT obs_end, value FROM headline_obs WHERE section=? AND metric=? AND obs_kind=? "
        "ORDER BY obs_end, obs_start", (k["section"], k["metric"], kind))]
    return pts, KIND_NAMES.get(kind, kind)


CITED = '<span class="badge b-cited">cited as evidence</span>'
TOPIC_EVENTS = 5   # front page: latest non-evidence events per topic; the rest are in the event log


def log_page(sec: str) -> str:
    """The section's event log (next to index.html): every effective event once, with its
    #ev-<section>-<id> anchor, grouped by topic (#t-<topic>)."""
    return f"events-{sec}.html"


def topic_anchor(topic: str) -> str:
    return "t-" + re.sub(r"[^a-z0-9-]+", "-", topic.lower())


def ev_href(sec: str, eid: str) -> str:
    return f"{log_page(sec)}#ev-{sec}-{eid}"
REL_WORDS = {"update": "updates", "followup": "follows up on", "retraction": "retracts", "delay": "delays",
             "confirmation": "confirms"}


def event_li(e: sqlite3.Row, names: dict[str, str], succ: dict[str, str] | None = None,
             anchor: bool = True, cited: bool = False, note: str = "", replaced: bool = False) -> str:
    """anchor: carry the #ev-<section>-<id> target (the event log: its first occurrence);
    cited: the event is evidence of the assessment it is listed under; note: an extra badge;
    replaced: the event is superseded or withdrawn (shown as cited evidence): link its successor.
    names: topic -> name, and ("ev", event id) -> (date, claim) of the section's events
    (lifecycle links show the linked event's date and claim, not its id)."""
    sig = int(e["significance"] or 0)
    chips = "".join(f'<span class="chip">{esc(names.get(t, t))}</span>' for t in json.loads(e["topics"] or "[]"))
    srcs = json.loads(e["sources"] or "[]")
    links = " ".join(link(s.get("url"), f"[{i}] {s.get('title') or 'source'}")
                     for i, s in enumerate(srcs, 1) if isinstance(s, dict))
    succ = succ or {}

    def about(eid) -> str:  # "<date>: <claim snippet>" of a linked event (its id if unknown)
        date, claim = names.get(("ev", eid)) or (None, None)
        if claim is None:
            return esc(eid)
        return f"{esc(date)}: {esc(claim if len(claim) <= 90 else claim[:88].rsplit(' ', 1)[0] + '…')}"

    def target(eid) -> str:  # a superseded event is not shown: link to its effective successor
        seen, t = set(), eid
        while succ.get(t) and t not in seen:
            seen.add(t); t = succ[t]
        if t in succ:  # not effective and no successor: withdrawn (a tombstone is never shown)
            return f'{about(eid)} <span class="mute">(since withdrawn)</span>'
        return (f'<a href="{esc(ev_href(e["section"], t))}" title="{esc(t)}">{about(t)}</a>'
                + (' <span class="mute">(corrected version)</span>' if t != eid else ""))
    rels = "".join(f'<div class="rel">↳ {esc(REL_WORDS.get(r.get("rel"), r.get("rel")))} {target(r.get("id"))}</div>'
                   for r in json.loads(e["relates"] or "[]") if isinstance(r, dict))
    if replaced and succ.get(e["id"]):
        rels += f'<div class="rel">↳ since corrected: {target(e["id"])}</div>'
    rels += "".join(f'<div class="rel" title="{esc(s)}">↳ corrects (or adds sources to) an earlier record: '
                    f'<s class="mute">{about(s)}</s></div>' for s in json.loads(e["supersedes"] or "[]"))
    aid = f' id="ev-{esc(e["section"])}-{esc(e["id"])}"' if anchor else ""
    return (f'<li class="ev sig{sig}"{aid}>'
            f'<div class="meta">{esc(e["date"])} · {esc(e["kind"])} · '
            f'<span title="significance {sig}/3">{"●" * sig}{"○" * (3 - sig)}</span> · '
            f'published {esc(e["known_at"])}{badge(e["verification_status"])}'
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
        raw = [ln for ln in blk.splitlines() if ln.strip()]
        if raw and re.match(r"^[*-]\s", raw[0]) and all(re.match(r"^([*-]|\s)\s", ln) for ln in raw):
            # a bullet list whose items may wrap onto indented continuation lines
            items: list[str] = []
            for ln in raw:
                if re.match(r"^[*-]\s", ln):
                    items.append(ln[1:].strip())
                else:
                    items[-1] += " " + ln.strip()
            lines = ["- " + it for it in items]
        else:
            lines = [ln.strip() for ln in raw]
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
                "advances": "Advances in the window", "setbacks": "Setbacks in the window", "prospects": "Prospects",
                "reason": "Reason", "change_note": "Change", "rule": "Rubric rule"}
# an open challenge's momentum (gather/RUBRIC.md §7): its status as an animal on the status colour
MOMENTUM = {"green": ("🐇", "advancing: a real step forward in the last 12 months"),
            "yellow": ("🐢", "inching: only small steps in the last 12 months"),
            "red": ("🧱", "stalled or set back: no real headway, or setbacks outweighed advances, in the last 12 months"),
            "unknown": ("❔", "unassessed: too little evidence to judge yet")}


ETA_LABELS = {"method": "ETA method", "calc": "ETA calculation", "cruxes": "ETA cruxes"}
OUTLOOK_KEYS = ("eta", "eta_cruxes", "path", "blockers", "reason")


# basis keys as an assessor writes them (snake_case, stats shorthand) -> words for a reader
KEY_WORDS = {"ols": "OLS", "95ci": "95% CI", "ci": "CI", "sd": "SD", "se": "SE", "r2": "R²", "n": "n",
             "h": "(h)", "eci": "ECI", "rli": "RLI", "metr": "METR", "yoy": "year on year",
             "pct": "%", "yr": "yr", "usd2025": "2025 $", "kg": "kg", "mo": "months"}
_PERIOD_RE = re.compile(r"\d{4}(-\d{2}(-\d{2})?|-[QH]\d)?")


def _key(k) -> str:
    s = str(k)
    if " " in s or "(" in s or not re.fullmatch(r"[a-z0-9_]+", s):
        return s  # already prose ("horizon-80-software-eci (2025-06-10..2026-09-22, n=13)")
    words = [KEY_WORDS.get(w, w) for w in s.split("_")]
    out = " ".join(words)
    return out[:1].upper() + out[1:]


def _num(v) -> str:
    """A number as an assessor's script printed it (0.5431226585424532) at 4 significant digits."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return str(v)
    if not math.isfinite(v):
        return str(v)
    if isinstance(v, int) or v == int(v) and abs(v) >= 1000:
        return f"{int(v):,}" if abs(v) >= 10000 else str(int(v))
    return f"{v:.4g}"


def basis_html(v, depth: int = 0) -> str:
    """A basis value as structure, not one run-on string: a dict as a nested definition list
    (a dict of period -> number, i.e. a data series, as a row of date/value cells), a list of numbers
    comma-separated, any other list as bullets, numbers rounded."""
    if isinstance(v, dict):
        items = [(k, x) for k, x in v.items() if x not in (None, "", [], {})]
        if items and all(_PERIOD_RE.fullmatch(str(k)) for k, _ in items) \
                and all(isinstance(x, (int, float)) and not isinstance(x, bool) for _, x in items):
            return ('<span class="ser">' + "".join(f"<span><i>{esc(k)}</i>{esc(_num(x))}</span>" for k, x in items)
                    + "</span>")
        return ('<dl class="basis sub">' + "".join(f"<dt>{esc(_key(k))}</dt><dd>{basis_html(x, depth + 1)}</dd>"
                                                    for k, x in items) + "</dl>")
    if isinstance(v, list):
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):  # numbers: one line
            return esc(", ".join(_num(x) for x in v))
        if len(v) == 1:
            return basis_html(v[0], depth + 1)
        return "<ul class=\"md\">" + "".join(f"<li>{basis_html(x, depth + 1)}</li>" for x in v) + "</ul>"
    return esc(_num(v))


def dot(status, title: str | None = None) -> str:
    st = status if status in STATUS_WORDS else "none"
    return f'<span class="dot s-{esc(st)}" title="{esc(title or STATUS_WORDS.get(st, "not yet assessed"))}"></span>'


CHALLENGE_KEY = (("green", "a real step forward"), ("yellow", "only small steps"), ("red", "stalled or set back"))


def momentum(status, title: str | None = None) -> str:
    """An open challenge's status marker (MOMENTUM); empty when not yet assessed."""
    if status not in MOMENTUM:
        return ""
    sym, words = MOMENTUM[status]
    return f'<span class="mo m-{esc(status)}" role="img" title="{esc(title or words)}" aria-label="{esc(words)}">{sym}</span>'


def marker(status, kind: str | None, title: str | None = None) -> str:
    """A target's status marker: an open challenge's momentum, else the status dot."""
    return momentum(status, title) if kind == "challenge" else dot(status, title)


def assessment_note(m) -> str:
    """The previous status if it changed, and a legacy-only flag (a small line, or "")."""
    prev = (f'Previously {marker(m["prev_status"], m["kind"])}{esc(m["prev_status"])} (assessed {esc(m["prev_made_at"])}).'
            if m["prev_status"] and m["prev_status"] != m["status"] else "")
    note = " ".join(x for x in (prev, badge("legacy") + " rests on unverified evidence only"
                                if m["legacy_evidence"] else "") if x)
    return f'<div class="mute small">{note}</div>' if note else ""


def assessment_html(m: sqlite3.Row, rationale: bool = True,
                    tech_title: str = "How this was assessed: the data, the benchmark and the rubric rule") -> str:
    """The judgment behind a status (shown under its status line): the previous status,
    rationale (unless the caller shows it) and the structured basis."""
    if not m["assessment_id"]:
        return '<div class="gap">not yet assessed</div>'
    # the status line it expands from already shows the dot, label and date
    out = ['<div class="ass">' + (assessment_note(m) if rationale else ""),
           f'<div>{esc(m["rationale"])}</div>' if rationale else ""]
    basis = json.loads(m["basis"] or "null") or {}
    rows = [(k, BASIS_LABELS[k], basis_html(basis[k])) for k in BASIS_LABELS if basis.get(k) not in (None, "", [], {})]
    eta = basis.get("eta")
    if isinstance(eta, dict) and "p50" in eta:  # rubric v2+ forecast: median + 80% range (+ v4 chance), reasoning
        yr = lambda k: eta[k] if eta.get(k) is not None else "never/after 2100"
        p = eta.get("p_achieved")
        pct = f"{round(100 * p)}%" if isinstance(p, (int, float)) and not isinstance(p, bool) else None
        head = (f"~{eta['p50']} (80% range {yr('p10')}–{yr('p90')}" + (f"; P(by 2100) {pct}" if pct else "") + ")"
                if eta.get("p50") is not None else
                f"unlikely by 2100 (P {pct or '?'}" + (f"; 10% chance by {eta['p10']}" if eta.get("p10") is not None else "") + ")")
        i = next(i for i, (k, _, _) in enumerate(rows) if k == "eta")
        rows[i:i + 1] = [("eta", "ETA", esc(head))] + [
            (f"eta_{k}", ETA_LABELS[k], basis_html(eta[k])) for k in ETA_LABELS if eta.get(k) not in (None, "", [], {})]
    dl = lambda rs: "".join(f"<dt>{esc(label)}</dt><dd>{v}</dd>" for _, label, v in rs)
    # the outlook (a milestone's ETA and its cruxes, path, blockers) is for every reader; how the
    # status was derived (the data window, benchmark, rubric rule, ETA method, ...) is audit detail: folded
    if outlook := [r for r in rows if r[0] in OUTLOOK_KEYS]:
        out.append(f'<dl class="basis">{dl(outlook)}</dl>')
    by = f'<div class="mute small">by {esc(m["by"])} · {len(json.loads(m["evidence"] or "[]"))} evidence event(s)</div>'
    if tech := [r for r in rows if r[0] not in OUTLOOK_KEYS]:  # the run that made it is audit detail too
        out.append(f'<details class="tech"><summary>{esc(tech_title)}'
                   f'</summary><dl class="basis">{dl(tech)}</dl>{by}</details>')
    else:
        out.append(by)
    out.append("</div>")
    return "".join(out)


def topic_events(db: sqlite3.Connection, sec: str, topic: str) -> list[sqlite3.Row]:
    return db.execute("SELECT e.* FROM event_topics t JOIN current_events e ON e.section = t.section "
                      "AND e.id = t.event_id WHERE t.section=? AND t.topic=? "
                      "ORDER BY e.date_end DESC, e.known_at DESC, e.id DESC", (sec, topic)).fetchall()


def events_ul(evs, names, succ, shown: set, limit: int | None = None, more: str = "") -> str:
    """A front-page event list (no anchors: those are in the event log): the first
    `limit` events, then a link (`more`) to the rest in the event log. Every listed
    event, shown or not, counts as placed under a topic (`shown`)."""
    shown.update(e["id"] for e in evs)
    out = [event_li(e, names, succ, anchor=False) for e in evs[:limit]]
    if limit is not None and len(evs) > limit:
        out.append(f'<li class="ev more-ev"><a href="{esc(more)}">+{len(evs) - limit} older event(s): '
                   "the section's event log</a></li>")
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
        # newest first, like every other event list (the assessor's citation order is arbitrary:
        # a years-old benchmark source must not head the list); unknown ids last
        cited = sorted(cited, key=lambda i: (i in rows, rows[i]["date_end"] or "" if i in rows else "",
                                             rows[i]["known_at"] or "" if i in rows else "", i), reverse=True)
        for eid in cited:
            e = rows.get(eid)
            if e is None:
                lis.append(f'<li class="ev"><span class="gap">{esc(eid)}: not in the ledger as of this date</span></li>')
            elif e["effective"]:
                lis.append(event_li(e, names, succ, anchor=False, cited=True))
                shown.add(eid)
            else:
                lis.append(event_li(e, names, succ, anchor=False, cited=True, replaced=True,
                                    note="since corrected" if e["superseded_by"] else "since withdrawn"))
        out.append(f"<h4>Cited evidence ({len(cited)})</h4><ul>{''.join(lis)}</ul>")
    evs = [e for e in topic_events(db, sec, topic) if e["id"] not in set(cited)]
    if evs:
        out.append(f"<h4>{'Other events' if cited else 'Events'} ({len(evs)})</h4>"
                   + events_ul(evs, names, succ, shown, TOPIC_EVENTS, f"{log_page(sec)}#{topic_anchor(topic)}"))
    elif not cited:
        out.append('<div class="mute">no events tagged yet</div>')
    return "".join(out)


def evidence_fold(db, sec: str, topic: str, m: sqlite3.Row | None, names, succ, shown: set,
                  other: str = "other event(s)") -> str:
    """evidence_and_events folded, its counts in the summary (a KPI's and a milestone's)."""
    cited = json.loads(m["evidence"] or "[]") if m and m["assessment_id"] else []
    n_other = len({e["id"] for e in topic_events(db, sec, topic)} - set(cited))
    what = ", ".join(x for x in ((f"{len(cited)} cited by the assessment" if cited else ""),
                                 (f"{n_other} {other}" if n_other else "")) if x) or "none yet"
    return (f'<details class="kev"><summary>Evidence and news: {what}</summary><div class="more">'
            f'{evidence_and_events(db, sec, topic, m, names, succ, shown)}</div></details>')


def topic_li(db, sec: str, item: dict, m: sqlite3.Row | None, kind: str, names, succ, shown: set) -> str:
    """One milestone/challenge, README-style (dot, name, definition, status line); the
    detail (criteria, assessment, evidence) expands."""
    topic = f"{kind}:{item['slug']}"
    # events = tagged with the topic, or cited by its assessment
    evs = {e["id"] for e in topic_events(db, sec, topic)}
    evs |= set(json.loads(m["evidence"] or "[]")) if m and m["assessment_id"] else set()
    assessed = bool(m and m["assessment_id"])
    head = (f'{marker(m["status"], kind) if assessed else (dot(None) if kind == "milestone" else "")}'
            f'<b>{md_inline(item["name"])}:</b> {md_inline(item["description"])}')
    if kind == "milestone" or assessed:
        st = (f'{esc(m["label"])} <span class="mute">· assessed {esc(m["made_at"])}</span>'
              if assessed else '<span class="gap">not yet assessed</span>')
        head += f'<span class="st">{st} <span class="mute">· {len(evs)} event(s)</span></span>'
    else:
        head += f'<span class="st mute">{len(evs)} event(s)</span>'
    body = ""
    if item.get("details"):
        body += '<ul class="md">' + "".join(f"<li>{md_inline(d)}</li>" for d in item["details"]) + "</ul>"
    pre = [t for m_id in item.get("precursors") or [] for t in db.execute(
        "SELECT * FROM latest_kpi WHERE section=? AND metric=? AND NOT retired", (sec, m_id))]
    if pre:   # the milestone's precursor ladder: the best achieved so far
        body += ('<h4>Closest so far</h4><div class="tiles">' + "".join(kpi_tile(db, t) for t in pre) + "</div>")
    if kind == "milestone":
        body += assessment_html(m) if m else '<div class="gap">not yet assessed</div>'
    elif assessed:
        body += assessment_html(m, tech_title="How the momentum was judged: advances, setbacks and prospects")
    # a milestone's evidence folds (its detail is criteria + assessment + evidence: long);
    # a challenge's events are its whole detail
    body += (evidence_fold(db, sec, topic, m, names, succ, shown) if kind == "milestone"
             else evidence_and_events(db, sec, topic, m, names, succ, shown))
    return (f'<li class="topic" id="t-{esc(sec)}-{esc(kind)}-{esc(item["slug"])}"><details><summary>{head}</summary>'
            f'<div class="more">{body}</div></details></li>')


# The milestone timeline's time axis runs from the as-of date to 2100, compressed (log of
# 1 + years-from-now / ETA_K): next year gets room, 2075 vs 2080 does not, so near and far
# milestones share one axis. Right of 2100, a zone for medians after 2100.
ETA_K = 2.0
ETA_LATER = 9.0  # % of the track
ETA_TICKS = (2027, 2028, 2030, 2035, 2040, 2050, 2060, 2075, 2100)
ETA_MAJOR = (2030, 2050)  # the tick labels kept on a phone


def sequential(fsec: dict | None) -> bool:
    """framework.yaml milestones_order: a sequence (each after the one before) or parallel."""
    return (fsec or {}).get("milestones_order") == "sequence"


def _eta(m: sqlite3.Row | None) -> dict | None:
    """A milestone assessment's forecast (rubric v2+: p10/p50/p90 years, p_achieved by 2100)."""
    if not (m and m["assessment_id"]):
        return None
    eta = (json.loads(m["basis"] or "null") or {}).get("eta")
    if not isinstance(eta, dict) or "p50" not in eta:
        return None
    year = lambda v: v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return {k: year(eta.get(k)) for k in ("p10", "p50", "p90", "p_achieved")}


def eta_x(year: float | None, now: float) -> float:
    """Position (% of the track) of a moment on the timeline; None or past 2100 = after 2100."""
    if year is None or year > 2100:
        return 100 - ETA_LATER / 2
    horizon = max(2100 - now, 0)
    return (100 - ETA_LATER) * math.log1p(min(max(year - now, 0), horizon) / ETA_K) / math.log1p(max(horizon, 1) / ETA_K)


def _year_x(y: float | None, now: float) -> float:
    """A forecast year's position: mid-year, or the after-2100 zone (None, or a year past 2100)."""
    return eta_x(None if y is None or y > 2100 else min(y + .5, 2100), now)


def _achieved(m: sqlite3.Row | None) -> bool:
    return bool(m and m["assessment_id"] and m["status"] == "achieved")


def eta_order(items: list, by_topic: dict) -> list:
    """Independent milestones soonest first: achieved, then by median year (one after 2100
    by its chance by 2100, the likelier first), then those without an ETA."""
    def key(it):
        m = by_topic.get(f"milestone:{it['slug']}")
        e = _eta(m)
        if _achieved(m):
            return (0, 0)
        if e and e["p50"] is not None and e["p50"] <= 2100:
            return (1, e["p50"])
        return (2, -(e["p_achieved"] or 0)) if e else (3, 0)
    return sorted(items, key=key)


def eta_chart(sec: str, items: list, by_topic: dict, seq: bool, as_of: dt.date) -> str:
    """The milestones on one (compressed) time axis: dot = median year (hollow: after 2100),
    bar = 80% range. A sequence keeps its order, with arrows from each milestone to the
    next; independent milestones are sorted soonest first (eta_order)."""
    now = as_of.year + (as_of.timetuple().tm_yday - .5) / 365.25
    rows = [(it, m, _eta(m)) for it in (items if seq else eta_order(items, by_topic))
            for m in [by_topic.get(f"milestone:{it['slug']}")]]
    if not any(e or _achieved(m) for _, m, e in rows):
        return ""
    after = lambda y: y is None or y > 2100
    yr = lambda y: "after 2100" if after(y) else str(y)
    out, prev = [], None
    for it, m, e in rows:
        st = m["status"] if m and m["assessment_id"] else "none"
        x, marks, hollow = None, [], ""
        if _achieved(m):
            x, tip = 0.0, f'{it["name"]}: achieved'
        elif e:
            x = _year_x(e["p50"], now)
            hollow = " ho" if after(e["p50"]) else ""
            pa = f'; {round(100 * e["p_achieved"])}% chance by 2100' if e["p_achieved"] is not None else ""
            # no p10 by 2100: even the 10% quantile is after 2100 (or never)
            rng = f'{yr(e["p10"])}–{yr(e["p90"])}' if not after(e["p10"]) else "after 2100 or never"
            tip = f'{it["name"]}: median {yr(e["p50"])}, 80% range {rng}{pa}'
            if not after(e["p10"]):
                a, b = _year_x(e["p10"], now), (100.0 if after(e["p90"]) else _year_x(e["p90"], now))
                marks.append(f'<i class="eb" style="left:{a:.1f}%;width:{max(b - a, .6):.1f}%"></i>')
        if x is None:
            marks.append('<span class="ena">no ETA yet</span>')
        else:
            marks.append(f'<i class="ed{hollow}" style="left:{x:.1f}%" title="{esc(tip)}"></i>')
        if seq and prev is not None and x is not None:
            # down from the previous dot to the row boundary, along it, then down into this dot
            way = "fw" if x >= prev else "bk"  # back: expected before its predecessor
            marks.append(f'<i class="dep {way}" style="left:{min(x, prev):.1f}%;width:{abs(x - prev):.1f}%"></i>'
                         f'<i class="dpa" style="left:{x:.1f}%"></i>')
        prev = x
        out.append(f'<div class="er e-{esc(st)}"><a class="en" href="#t-{esc(sec)}-milestone-{esc(it["slug"])}" '
                   f'title="{esc(it["name"])}">{plain_md(it["name"])}</a><div class="et">{"".join(marks)}</div></div>')
    ticks, last = [], -99.0
    for y in ETA_TICKS:
        x = eta_x(y, now)
        if x >= 6 and x - last >= 7:
            ticks.append((y, x))
            last = x
    grid = ("".join(f'<i style="left:{x:.1f}%"></i>' for _, x in ticks)
            + f'<b class="lz" style="left:{100 - ETA_LATER:.1f}%"></b>')
    axis = ('<span style="left:0;transform:none">now</span>'
            + "".join(f'<span{"" if y in ETA_MAJOR else ' class="mn"'} style="left:{x:.1f}%">{y}</span>'
                      for y, x in ticks)
            + f'<span style="left:100%;transform:translateX(-100%)">later</span>')
    cap = ("Expected year: dot = median (hollow: after 2100), bar = 80% range"
           + ("; arrows: each milestone is expected after the one before" if seq else "")
           + ". The time axis is compressed: the farther out, the more years per step.")
    return (f'<div class="ec{" seq" if seq else ""}"><div class="eg">{grid}</div>{"".join(out)}'
            f'<div class="er ea"><span></span><div class="et">{axis}</div></div></div>'
            f'<div class="mute small">{cap}</div>')


def kpi_about_html(db, sec: str, about, tiles: dict, definition: str = "") -> tuple[str, set[str]]:
    """framework.yaml kpi_about: markdown, or {summary, sections: [{title?, text?, chart?, metrics?}]}
    (a chart id of views/kpi_charts.py; metrics = tiles shown with the section), opened by the
    KPI's framework definition (the headline tile names it; the precise wording folds here).
    Returns the folded explainer and the metrics it placed."""
    if not about and not definition:
        return "", set()
    if isinstance(about, str):
        about = {"sections": [{"text": about}]}
    about = about or {"summary": "The KPI's precise definition"}
    placed: set[str] = set()
    as_of = D(db.execute("SELECT value FROM build_info WHERE key='as_of'").fetchone()[0])
    body = [f'<p class="kdef"><b>The KPI, as defined:</b> {md_inline(definition)}</p>'] if definition else []
    for part in about.get("sections") or []:
        if part.get("title"):
            body.append(f'<h4 class="ab">{md_inline(part["title"])}</h4>')
        body.append(md_block(part.get("text")))
        if (ch := part.get("chart")) and ch in kpi_charts.CHARTS:
            body.append(kpi_charts.CHARTS[ch](db, as_of))
        ts = [tiles[m] for m in part.get("metrics") or [] if m in tiles]
        placed |= {t["metric"] for t in ts}
        if ts:
            body.append('<div class="tiles">' + "".join(kpi_tile(db, t) for t in ts) + "</div>")
    summary = about.get("summary") or "What this measures and how it is judged"
    return (f'<details class="about"><summary>{md_inline(summary)}</summary>'
            f'<div class="more md">{"".join(body)}</div></details>'), placed


def kpi_block(db, sec: str, s: sqlite3.Row, ms: list, names, succ, shown: set, fsec: dict | None = None) -> str:
    """The KPI, top down. Shown: the headline tile(s) next to the status and why (the
    rationale). Folded: its precise definition and how it is built (framework.yaml kpi_about:
    the story, charts and the tiles of its parts), how the status was judged (the basis), the evidence
    and news, and the section's other metrics."""
    tiles = db.execute("SELECT * FROM latest_kpi WHERE section=? AND NOT retired "
                       "ORDER BY required DESC, metric", (sec,)).fetchall()
    km = next((m for m in ms if m["kind"] == "kpi"), None)
    assessed = bool(km and km["assessment_id"])
    # the heading only: the headline tile names the metric; the framework's precise
    # definition opens the folded explainer
    out = [f'<div class="kpiblk" id="t-{esc(sec)}-kpi"><h3>KPI</h3>']
    heads = [t for t in tiles if t["required"]]
    # shown: the required metric(s) only (or every tile, while none is required); the explainer
    # places its tiles; the rest folds (an overdue or empty one keeps its warning in the fold)
    main = heads or tiles
    about, placed = kpi_about_html(db, sec, (fsec or {}).get("kpi_about"),
                                   {t["metric"]: t for t in tiles if t not in heads}, s["kpi"])
    # precursor series are shown with their milestone (topic_li)
    placed |= {p for it in (fsec or {}).get("milestones") or [] for p in it.get("precursors") or []}
    main = [t for t in main if t in heads or t["metric"] not in placed]
    rest = label_order(sec, [t for t in tiles if t not in main and t["metric"] not in placed])
    status = (f'{dot(km["status"])}<b>{esc(km["label"])}</b> <span class="mute">· assessed {esc(km["made_at"])}</span>'
              if assessed else f'{dot(None)}<span class="gap">not yet assessed</span>')
    why = f'{assessment_note(km)}<p class="why">{esc(km["rationale"])}</p>' if assessed else ""
    lead = ""
    if not tiles:
        lead = '<div class="gap">no KPI metric tracked yet</div>'
    elif not heads:
        lead = '<div class="mute">none of these metrics is the official KPI yet</div>'
    if main and len(main) <= 2:  # the headline next to its status
        out.append(f'<div class="khead"><div class="tiles">{"".join(kpi_tile(db, t) for t in main)}</div>'
                   f'<div><div class="kst">{status}</div>{why}{lead}</div></div>')
    else:
        out.append(f'<div class="kst">{status}</div>{why}{lead}')
        if main:
            out.append('<div class="tiles">' + "".join(kpi_tile(db, t) for t in main) + "</div>")
    out.append(cases_html(db, sec))   # a counting KPI's cases (robots-hardware): the case for each
    out.append(about)
    if assessed:
        out.append(assessment_html(km, rationale=False,
                                   tech_title="How the status was judged: the data window, the pace benchmark, the rule"))
    out.append(evidence_fold(db, sec, "kpi", km, names, succ, shown, "other KPI news"))
    if rest:
        out.append(f"<details><summary>{len(rest)} more metric(s) we track</summary>"
                   '<div class="tiles">' + "".join(kpi_tile(db, t) for t in rest) + "</div></details>")
    return "".join(out) + "</div>"


def cases_html(db, sec: str) -> str:
    """The deployment cases a counting KPI counts (ledger.deployment_roster over the effective
    events as of the build), one row each: the case for counting it, the deployments at work
    first, then those since reported ended or disputed (greyed, with that later report).
    Empty without any."""
    evs = [{"id": r["id"], "published": r["published"], "deployment": json.loads(r["deployment"])}
           for r in db.execute("SELECT id, published, deployment FROM events WHERE section=? AND effective "
                               "AND deployment IS NOT NULL", (sec,))]
    cases, _ = ledger.deployment_roster(evs)
    cases = [c for c in cases if c["since"]]   # documented working at least once
    if not cases:
        return ""
    at_work = [c for c in cases if c["counted"]]
    other = [c for c in cases if not c["counted"]]
    makers: dict[str, int] = {}
    for c in cases:
        k = ledger._deploy_key(c)[0]
        makers[k] = makers.get(k, 0) + 1
    rows = []
    for c in at_work + other:
        plat = esc(c["platform"]) + (f' <span class="mute">({esc(c["form"])})</span>' if c["form"] else "")
        n_other = makers[ledger._deploy_key(c)[0]] - 1
        if n_other:
            plat += f' <span class="mute">· also at {n_other} other customer(s)</span>'
        job = esc(c["job"])
        for u in c["updates"]:   # later reports: shown, never overwriting what the work was
            job += (f'<br><span class="mute small">{esc(u["status"])}, reported '
                    f'<a href="{ev_href(sec, u["event"])}">{esc(fmt_date(u["date"]))}</a>'
                    + (f': {esc(u["job"])}' if u["job"] and u["job"] != c["job"] else "") + "</span>")
        status = "at work" if c["counted"] else esc(c["status"])
        if c["counted"] and c["work_event"] != c["first_event"]:   # the latest report of it working
            status = f'<a href="{ev_href(sec, c["work_event"])}">{status}</a>'
        rows.append(
            f'<tr{"" if c["counted"] else " class=mute"}><td><a href="{ev_href(sec, c["first_event"])}">'
            f'{esc(fmt_date(c["since"]))}</a></td><td><b>{esc(c["maker"])}</b><br>{plat}</td>'
            f'<td>{esc(c["customer"])}' + (f'<br><span class="mute">{esc(c["site"])}</span>' if c["site"] else "")
            + f'</td><td>{job}</td><td>{esc(c["robots"] or "—")}</td>'
            f'<td class="small">“{esc(c["autonomy"] or "")}”</td><td>{status}</td></tr>')
    as_of = db.execute("SELECT value FROM build_info WHERE key='as_of'").fetchone()
    when = f" as of {esc(fmt_date(as_of[0]))}" if as_of else ""
    more = f' <span class="mute">(and {len(other)} since reported ended or disputed)</span>' if other else ""
    return (f'<details class="cases" open><summary>The {len(at_work)} deployment(s) at work{when}{more}</summary>'
            '<table class="cases"><tr><th>Since</th><th>Maker · platform</th><th>Customer</th><th>Job</th>'
            '<th>Robots</th><th>Autonomy, as reported</th><th>Status</th></tr>' + "".join(rows) + "</table></details>")


SUPP_MAJOR = 10  # a supplemental pane's notable developments (significance 3) shown before the event log


def indicators(db, sec: str, inputs: bool = False) -> list[sqlite3.Row]:
    """A section's tracked metrics in registry order (metrics/<section>.csv), retired ones out;
    without the series that only feed another indicator (metric-labels.yaml _inputs), or
    (inputs) only those."""
    rows = db.execute("SELECT * FROM latest_kpi WHERE section=? AND NOT retired ORDER BY rowid", (sec,)).fetchall()
    return [t for t in rows if (t["metric"] in METRIC_INPUTS.get(sec, [])) == inputs]


def major_events(db, sec: str) -> list[sqlite3.Row]:
    """A section's significance-3 events, the latest (by event date) first."""
    return db.execute("SELECT * FROM current_events WHERE section=? AND significance=3 "
                      "ORDER BY date_end DESC, known_at DESC, id DESC", (sec,)).fetchall()


def supplemental_html(db, sec: str, names, succ) -> str:
    """A section with no KPI, milestones or challenges (a supplemental one): what we do
    track there, the indicators (registry metrics, none of them a KPI) and the notable
    developments (significance 3)."""
    out = ['<div class="mute">Outside the five endeavors: no KPI, milestones or challenges, so nothing here is '
           'assessed. We keep an eye on a few indicators and the notable developments.</div>']
    tiles, inputs = indicators(db, sec), indicators(db, sec, inputs=True)
    out.append("<h3>Indicators we track</h3>" + (
        '<div class="tiles">' + "".join(kpi_tile(db, t) for t in tiles) + "</div>" if tiles
        else '<div class="mute">none registered yet</div>'))
    if inputs:
        out.append(f"<details><summary>Fine print: {len(inputs)} input series behind the indicators above</summary>"
                   '<div class="tiles">' + "".join(kpi_tile(db, t) for t in inputs) + "</div></details>")
    major = major_events(db, sec)
    if major:
        out.append(f'<h3>Notable developments</h3><div class="mute small">The {min(SUPP_MAJOR, len(major))} '
                   f'latest of {len(major)} major (significance ●●●) events, by event date.</div>'
                   + events_ul(major, names, succ, set(), SUPP_MAJOR, log_page(sec)))
    return "".join(out)


def section_html(db: sqlite3.Connection, s: sqlite3.Row, fsec: dict | None = None, n_recent: int = 8,
                 covered: bool = True, crumb: str = "", head: str = "", track: bool = False) -> str:
    """One endeavor's pane, or (track) one section of a multi-section endeavor's pane
    (Robots and Automation: Software, Hardware). crumb: a kicker over the title (a
    supplemental section's group); head: extra header HTML (the activity strip)."""
    sec = s["section"]
    fsec = fsec or {}
    ms = db.execute("SELECT * FROM milestone_status WHERE section=? ORDER BY ord", (sec,)).fetchall()
    by_topic = {m["target"]: m for m in ms}
    names = {r["topic"]: r["name"] for r in db.execute("SELECT topic, name FROM topics WHERE section=?", (sec,))}
    names.update({("ev", r[0]): (r[1], r[2]) for r in db.execute("SELECT id, date, claim FROM events WHERE section=?",
                                                                 (sec,))})
    # superseded id -> its effective successor (follow chains), so links always land on a shown event
    succ = dict(db.execute("SELECT id, superseded_by FROM events WHERE section=? AND NOT effective", (sec,)).fetchall())
    framework = bool(s["kpi"] or fsec.get("milestones") or fsec.get("challenges"))
    shown: set[str] = set()
    crumb = f'<div class="crumb">{esc(crumb)}</div>' if crumb else ""
    out = [f'<section class="{"track" if track else "pane"}" id="{esc(sec)}">{crumb}'
           f'<h2>{icon(sec)} {esc(s["title"])}</h2>{head}']
    if not covered:
        out.append('<div class="note">Not covered by this period\'s bulletins: shown is the ledger '
                   'as of the cutoff, for reference.</div>')
    out.append(md_block(fsec.get("intro")))
    if s["kpi"]:
        out.append(kpi_block(db, sec, s, ms, names, succ, shown, fsec))
    elif not framework:
        out.append(supplemental_html(db, sec, names, succ))
    for kind, title in (("milestone", "Milestone Countdown"),
                        ("challenge", fsec.get("challenges_heading") or "Major Open Challenges")):
        items = fsec.get(kind + "s") or []
        if not items:
            if framework:
                out.append(f'<h3>{esc(title)}</h3><div class="gap">none listed in the framework</div>')
            continue
        seq = sequential(fsec)
        ordered = items if kind == "challenge" or seq else eta_order(items, by_topic)
        lis = [topic_li(db, sec, it, by_topic.get(f"{kind}:{it['slug']}"), kind, names, succ, shown) for it in ordered]
        if kind == "challenge":
            key = ""
            if any((by_topic.get(f"challenge:{it['slug']}") or {"assessment_id": None})["assessment_id"] for it in items):
                key = ('<div class="mute small">Momentum over the last 12 months: '
                       + " · ".join(f"{momentum(st)}{esc(w)}" for st, w in CHALLENGE_KEY) + "</div>")
            out.append(f'<h3>{md_inline(title)}</h3>{key}<ul class="topics">{"".join(lis)}</ul>')
            continue
        as_of = D(db.execute("SELECT value FROM build_info WHERE key='as_of'").fetchone()[0])
        out.append(f'<h3>{md_inline(title)}</h3><div class="mute small">'
                   + ("A sequence: each milestone is expected after the one before it." if seq else
                      "Independent fronts: these can fall in any order.") + "</div>"
                   + eta_chart(sec, items, by_topic, seq, as_of)
                   + (f'<ol class="topics seq">{"".join(lis)}</ol>' if seq else f'<ul class="topics par">{"".join(lis)}</ul>'))

    evs = db.execute("SELECT * FROM current_events WHERE section=? "
                     "ORDER BY known_at DESC, date_end DESC, significance DESC, id DESC", (sec,)).fetchall()
    if not evs:
        out.append('<div class="gap">no events in the ledger yet</div>')
        return "".join(out) + "</section>"
    beyond = topic_events(db, sec, "beyond")
    if beyond:
        out.append(f'<details class="news"><summary>Beyond the framework: {len(beyond)} event(s)</summary>'
                   f'<div class="more">{events_ul(beyond, names, succ, shown, TOPIC_EVENTS, log_page(sec) + "#t-beyond")}'
                   "</div></details>")
    # events no framework topic lists (e.g. tags of a since-changed framework): never silently dropped
    other = [e for e in evs if e["id"] not in shown]
    if other:
        out.append(f'<details class="news"><summary>Events under no current topic: {len(other)}</summary>'
                   f'<div class="more">{events_ul(other, names, succ, shown, TOPIC_EVENTS, log_page(sec) + "#t-other")}'
                   "</div></details>")
    out.append(f'<details class="news"><summary>Latest news: the {min(n_recent, len(evs))} most recently '
               f'published of {len(evs)} events</summary><div class="more">{events_ul(evs[:n_recent], names, succ, shown)}'
               f'<p><a href="{esc(log_page(sec))}">All {len(evs)} events: the event log</a></p></div></details>')
    return "".join(out) + "</section>"


def event_log_html(db: sqlite3.Connection, s: sqlite3.Row, as_of: dt.date, fw: dict,
                   period: str | None, home: str = "index.html") -> str:
    """A section's event log: every effective event once (in full, with its anchor)
    under its first topic in framework order; under later topics a one-line link to it."""
    sec = s["section"]
    names = {r["topic"]: r["name"] for r in db.execute("SELECT topic, name FROM topics WHERE section=?", (sec,))}
    names.update({("ev", r[0]): (r[1], r[2]) for r in db.execute("SELECT id, date, claim FROM events WHERE section=?",
                                                                 (sec,))})
    succ = dict(db.execute("SELECT id, superseded_by FROM events WHERE section=? AND NOT effective", (sec,)).fetchall())
    topics = db.execute("SELECT topic, name FROM topics WHERE section=? ORDER BY ord", (sec,)).fetchall()
    # the front page's grouping: no KPI line -> its kpi-tagged events are under no current topic
    groups = [(t["topic"], t["name"], topic_events(db, sec, t["topic"])) for t in topics
              if t["topic"] != "kpi" or s["kpi"]]
    listed = {e["id"] for _, _, evs in groups for e in evs}
    evs = db.execute("SELECT * FROM current_events WHERE section=? "
                     "ORDER BY date_end DESC, known_at DESC, id DESC", (sec,)).fetchall()
    groups.append(("other", "Under no current topic", [e for e in evs if e["id"] not in listed]))
    shown: set[str] = set()
    body, toc = [], []
    for topic, name, tevs in groups:
        if not tevs:
            continue
        lis = []
        for e in tevs:
            if e["id"] in shown:
                claim = e["claim"] or ""
                lis.append(f'<li class="ev ref">{esc(e["date"])} · <a href="#ev-{esc(sec)}-{esc(e["id"])}">'
                           f'{esc(claim[:140] + ("…" if len(claim) > 140 else ""))}</a></li>')
            else:
                lis.append(event_li(e, names, succ, anchor=True))
                shown.add(e["id"])
        aid = topic_anchor(topic)
        toc.append(f'<a href="#{esc(aid)}">{md_inline(name)} ({len(tevs)})</a>')
        body.append(f'<h3 id="{esc(aid)}">{md_inline(name)} ({len(tevs)})</h3><ul>{"".join(lis)}</ul>')
    title = f'{fw["title"]}{f" — {period}" if period else ""}: {s["title"]}, event log'
    when = (f"period page <b>{esc(period)}</b>, the ledger as of its cutoff <b>{esc(as_of)}</b>, frozen"
            if period else f"live ledger state as of <b>{esc(as_of)}</b>")
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{esc(title)} (as of {esc(as_of)})</title><style>{CSS}</style></head><body class=\"log\">"
            f'<header><h1>{esc(s["title"])}: event log</h1>'
            f'<div class="asof">All {len(evs)} events of this endeavor ({when}), newest first, under their '
            f'first topic; under later topics, a link. <a href="{esc(home)}#{esc(sec)}">← dashboard</a></div>'
            f'<nav>{"".join(toc)}</nav></header><main><section id="{esc(sec)}">{"".join(body)}</section>'
            '<footer><p class="mute small">Generated by views/explore.py from the Grand Endeavors ledger.</p>'
            "</footer></main></body></html>\n")


def pages(as_of: dt.date, fw: dict | None = None, period: str | None = None,
          covered: set[str] | None = None, note: str = "", periods: list[str] = (),
          home: str = "index.html") -> dict[str, str]:
    """The published pages by file name: `home` (the dashboard: the framework, what we
    track and why, with the ledger's state as of `as_of`) and one event log per section
    with events (log_page). period: period pages (frozen at its cutoff, `covered` =
    sections with a bulletin); periods: period pages to link from the live page."""
    fw = fw or ledger.framework()
    db = sqlite3.connect(":memory:")
    try:
        build_db(db, as_of, fw)
        db.row_factory = sqlite3.Row
        out = {home: _dashboard_html(db, as_of, fw, period, covered, note, periods)}
        for s in db.execute("SELECT * FROM sections ORDER BY ord").fetchall():
            if db.execute("SELECT 1 FROM current_events WHERE section=?", (s["section"],)).fetchone():
                out[log_page(s["section"])] = event_log_html(db, s, as_of, fw, period, home)
        return out
    finally:
        db.close()


def dashboard(as_of: dt.date, fw: dict | None = None, period: str | None = None,
              covered: set[str] | None = None, note: str = "", periods: list[str] = ()) -> str:
    """The front page alone (pages()[PAGE])."""
    return pages(as_of, fw, period, covered, note, periods)[PAGE]


def prune_logs(out_dir: str, keep) -> None:
    """Drop event logs (events-*.html) not in `keep` from a directory this module owns
    (the site root, a period dir), e.g. of a section with no events any more."""
    for name in os.listdir(out_dir):
        if re.fullmatch(r"events-.+\.html", name) and name not in keep:
            os.remove(os.path.join(out_dir, name))


def write_pages(out_dir: str, pgs: dict[str, str], prune: bool = False) -> list[str]:
    """Write rendered pages (each replaced atomically); prune: out_dir is ours (site
    root, period dir), drop stale event logs there."""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for name, page in pgs.items():
        p = os.path.join(out_dir, name)
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            f.write(page)
        os.replace(p + ".tmp", p)
        written.append(p)
    if prune:
        prune_logs(out_dir, pgs)
    return written


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
        "A milestone's status is its evidence-based ETA. Both change only on newer evidence.</p>"
        "<p>An open challenge's status is its <i>momentum</i> over the last 12 months, not how close it is "
        "to being solved: " + ", ".join(f"{momentum(st)}{esc(w)}" for st, w in CHALLENGE_KEY) + ". "
        "Because the window rolls, a status can also drop with no new evidence, once the step that earned "
        "it is more than 12 months old.</p>"
        "<p>An endeavor's milestones are either a <b>sequence</b> (each expected after the one before: "
        "numbered, joined by a line) or <b>independent fronts</b> (any order: cards). Its timeline puts "
        "them on one time axis: the median year and the 80% range of each ETA.</p>"
        "<p>Everything shown comes from an append-only <b>ledger</b> of verified facts, each with its "
        "sources and the date it became public. "
        f'{badge("verified")} / {badge("corrected")}: checked against the source at intake. '
        f'{badge("legacy")}: converted from the first (2025) pilot report, not verified at ingest. '
        "“As of” means only what was public by that date is included.</p></div></details>")


ICONS = {"robots-software": "💻", "robots-hardware": "🦾", "rockets": "🚀", "fusion": "⚡", "health": "🧬",
         "climate": "🌍", "knowledge-beyond": "🔭", "society-cohesion": "🤝", "robots-and-automation": "🤖"}
ACTIVITY_WEEKS = 16  # the activity histogram (events per week)
CARD_INDS, CARD_MAJOR = 4, 3  # a supplemental card: its first indicators, its latest major events
STREAM_N = 100  # events in the news stream (+ the status changes over the same span)


def icon(key: str) -> str:
    return f'<span class="ic" aria-hidden="true">{ICONS.get(key, "◆")}</span>'


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def plain_md(text) -> str:
    """Markdown inline -> escaped plain text (for places that must not contain links)."""
    t = re.sub(r"\[([^\]]+)\]\([^)\s]+\)", r"\1", str(text or ""))
    return esc(re.sub(r"\*\*?(\S.*?\S|\S)\*\*?", r"\1", t))


def topic_dot(m: sqlite3.Row) -> str:
    """A milestone's dot, its name and status label as the tooltip."""
    st = m["status"] if m["assessment_id"] else None
    return dot(st, f'{m["name"]}: {m["label"] if st else "not yet assessed"}')


def glance(db: sqlite3.Connection, sec: str, as_of: dt.date, seq: bool = False) -> dict:
    """The at-a-glance facts of a section: KPI status + headline metric, milestones (seq: a
    sequence), activity."""
    ms = db.execute("SELECT * FROM milestone_status WHERE section=? ORDER BY ord", (sec,)).fetchall()
    # headline: a required metric (with data first); else one that becomes required later
    req = db.execute("SELECT k.* FROM latest_kpi k JOIN metrics m USING (section, metric) WHERE k.section=? "
                     "AND NOT k.retired AND (k.required OR COALESCE(m.required_from, '') != '') "
                     "ORDER BY k.required DESC, k.obs IS NULL, k.metric", (sec,)).fetchall()
    n_ev, last = db.execute("SELECT COUNT(*), MAX(known_at) FROM current_events WHERE section=?", (sec,)).fetchone()
    # events per week, the last ACTIVITY_WEEKS weeks to as_of (oldest first)
    weeks = [0] * ACTIVITY_WEEKS
    for (k,) in db.execute("SELECT known_at FROM current_events WHERE section=?", (sec,)):
        w = (as_of - D(k)).days // 7
        if 0 <= w < ACTIVITY_WEEKS:
            weeks[ACTIVITY_WEEKS - 1 - w] += 1
    km = next((m for m in ms if m["kind"] == "kpi"), None)
    return {"km": km if km and km["assessment_id"] else None,
            "mils": [m for m in ms if m["kind"] == "milestone"], "seq": seq,
            "n_ch": sum(m["kind"] == "challenge" for m in ms),
            "head": req[0] if req else None, "n_ev": n_ev, "last": last, "weeks": weeks,
            # a section without a KPI: its indicators with data, its major events
            "inds": [t for t in indicators(db, sec) if t["obs"] is not None], "major": major_events(db, sec)}


def merged(gs: list[dict]) -> dict:
    """The activity of several sections together (a multi-section endeavor)."""
    lasts = [g["last"] for g in gs if g["last"]]
    return {"n_ev": sum(g["n_ev"] for g in gs), "last": max(lasts) if lasts else None,
            "weeks": [sum(w) for w in zip(*(g["weeks"] for g in gs))], "n_ch": sum(g["n_ch"] for g in gs)}


def activity_bars(weeks: list[int], as_of: dt.date, w: int = 96, h: int = 20) -> str:
    """News per week as a labelled bar chart (the newest week at the right)."""
    if not any(weeks):
        return f'<span class="actw">no news in the last {len(weeks)} weeks</span>'
    top, bw, Z = max(weeks) or 1, w / len(weeks), ' class="z"'
    bars = "".join(f'<rect x="{i * bw + .5:.1f}" y="{h - max(1.0, h * n / top):.1f}" width="{bw - 1.5:.1f}" '
                   f'height="{max(1.0, h * n / top):.1f}"{"" if n else Z}/>'
                   for i, n in enumerate(weeks))
    return (f'<span class="actw">news per week <svg class="act" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img"><title>news per week, '
            f'the {len(weeks)} weeks to {as_of}: {", ".join(map(str, weeks))}</title>{bars}</svg></span>')


def _ago(day: str, as_of: dt.date) -> str:
    n = (as_of - D(day)).days
    return ("today" if n <= 0 else "yesterday" if n == 1 else f"{n} days ago" if n < 14
            else f"{n // 7} weeks ago" if n < 60 else f"{n // 30} months ago" if n < 730 else f"{n // 365} years ago")


def recency(last: str | None, as_of: dt.date) -> str:
    """How fresh an endeavor's news is: the latest event's age, brighter = fresher."""
    if not last:
        return '<span class="rc r-cold" title="no news yet">no news</span>'
    n = (as_of - D(last)).days
    txt = ("today" if n <= 0 else f"{n}d ago" if n < 14 else f"{n // 7}w ago" if n < 60
           else f"{n // 30}mo ago" if n < 730 else f"{n // 365}y ago")
    cls = "r-hot" if n <= 7 else "r-warm" if n <= 30 else "r-cold"
    return f'<span class="rc {cls}" title="latest news published {esc(last)} ({_ago(last, as_of)})">{txt}</span>'


def _value(t: sqlite3.Row, named: bool = False) -> str:
    """A metric's latest value (named: with its short name after it, for an indicator)."""
    label = metric_label(t["section"], t["metric"], t["definition"])
    v, u = human_value(t["value_text"], t["unit"], t["metric"])
    return (f'<span class="hv" title="{esc(label)}, {esc(fmt_period(t["obs"]))}"><b>{esc(v)}</b> {esc(u)}'
            + (f' <span class="mute">{esc(label)}</span>' if named else "") + "</span>")


def _headline(db, g: dict, w: int, h: int, axis: str = "below") -> str:
    t = g["head"]
    if t is None or t["obs"] is None:
        return f'<span class="mute">{"no KPI data yet" if t is not None else "no KPI metric yet"}</span>'
    return _value(t) + sparkline(*spark_points(db, t), w=w, h=h, pad=2, axis=axis,
                                 fmt=lambda x: " ".join(human_value(f"{x:.6g}", t["unit"], t["metric"])))


def _kpi_dot(g: dict) -> str:
    km = g["km"]
    return dot(km["status"], f'KPI: {km["label"]}') if km else dot(None, "KPI: not yet assessed")


def nav_rows(db, sec: str, g: dict, has_kpi: bool) -> str:
    """The KPI line (status dot, latest value, series) and the milestone dots; none without
    a KPI (a supplemental section: no one value stands for it)."""
    if not has_kpi:
        return ""
    dots = ('<i class="lk"></i>' if g["seq"] else "").join(topic_dot(m) for m in g["mils"])
    return (f'<span class="nk">{_kpi_dot(g)}{_headline(db, g, 70, 16, "left")}</span>'
            + (f'<span class="nd{" seq" if g["seq"] else ""}" title="milestones'
               f'{", in sequence" if g["seq"] else ""}">{dots}</span>' if dots else ""))


def nav_item(db, sec: str, title: str, g: dict, covered: bool, has_kpi: bool, as_of: dt.date) -> str:
    return (f'<a class="nv{"" if covered else " ncov"}" href="#{esc(sec)}">'
            f'<span class="nt">{icon(sec)}<span class="nn">{esc(title)}</span>{recency(g["last"], as_of)}</span>'
            f'{nav_rows(db, sec, g, has_kpi)}</a>')


def nav_group(db, gid: str, title: str, tracks: list, as_of: dt.date) -> str:
    """A multi-section endeavor: its title, then one sub-item per section."""
    m = merged([g for _, _, g, _, _ in tracks])
    out = [f'<div class="nvg"><a class="nv" href="#{esc(gid)}"><span class="nt">{icon(gid)}'
           f'<span class="nn">{esc(title)}</span>{recency(m["last"], as_of)}</span></a>']
    for sec, stitle, g, cov, has_kpi in tracks:
        out.append(f'<a class="nv sub{"" if cov else " ncov"}" href="#{esc(sec)}"><span class="nt">{icon(sec)}'
                   f'<span class="nn">{esc(stitle)}</span></span>{nav_rows(db, sec, g, has_kpi)}</a>')
    return "".join(out) + "</div>"


def card_track(db, kpi_line: str, g: dict) -> str:
    """A section's KPI and milestones on an overview card."""
    km = g["km"]
    if not kpi_line:  # a supplemental section: its indicators and latest major events instead
        inds = [f'<li>{_value(t, True)} <span class="mute">({esc(fmt_period(t["obs"]))})</span></li>'
                for t in g["inds"][:CARD_INDS]]
        if len(g["inds"]) > CARD_INDS:
            inds.append(f'<li class="mute">+{len(g["inds"]) - CARD_INDS} more</li>')
        out = ('<div class="ck">No KPI: outside the five endeavors. '
               + (f'Indicators we track:</div><ul class="ci">{"".join(inds)}</ul>' if inds
                  else "No indicators tracked yet.</div>"))
        if g["major"]:
            out += ('<div class="ck">Latest major developments:</div><ul class="cn">'
                    + "".join(f'<li><span class="mute">{esc(e["date"])}</span> {esc(e["claim"])}</li>'
                              for e in g["major"][:CARD_MAJOR]) + "</ul>")
    else:
        status = (f'{dot(km["status"])}<span>{esc(km["label"])}</span>' if km
                  else f'{dot(None)}<span class="mute">KPI not yet assessed</span>')
        out = (f'<div class="ck">KPI: {plain_md(kpi_line)}</div><div class="cv">{_headline(db, g, 120, 26)}</div>'
               f'<div class="cs">{status}</div>')
    mils = "".join(f'<li>{topic_dot(m)}{plain_md(m["name"])}</li>' for m in g["mils"])
    return out + (f'<ul class="cm{" seq" if g["seq"] else ""}">{mils}</ul>' if mils else "")


def card_foot(m: dict, as_of: dt.date) -> str:
    facts = [f'{m["n_ev"]} events'] + ([f'{m["n_ch"]} open challenges'] if m["n_ch"] else [])
    return (f'<div class="cf"><span>{" · ".join(facts)}</span>'
            f'{activity_bars(m["weeks"], as_of)}</div>')


def card(db, sec: str, title: str, kpi_line: str, g: dict, as_of: dt.date) -> str:
    """The overview's card of an endeavor (all of it one link to its pane)."""
    return (f'<a class="card" href="#{esc(sec)}"><div class="ct">{icon(sec)}<span class="nn">{esc(title)}</span>'
            f'{recency(g["last"], as_of)}</div>{card_track(db, kpi_line, g)}{card_foot(g, as_of)}</a>')


def group_card(db, gid: str, title: str, tracks: list, as_of: dt.date) -> str:
    """A multi-section endeavor's card: its sections side by side."""
    m = merged([g for _, _, g, _, _ in tracks])
    body = "".join(f'<div class="trk"><div class="tt">{icon(sec)} {esc(stitle)}</div>{card_track(db, kl, g)}</div>'
                   for sec, stitle, g, kl, _ in tracks)
    return (f'<a class="card wide" href="#{esc(gid)}"><div class="ct">{icon(gid)}<span class="nn">{esc(title)}'
            f'</span>{recency(m["last"], as_of)}</div><div class="trks">{body}</div>{card_foot(m, as_of)}</a>')


def strip(m: dict, as_of: dt.date) -> str:
    """A pane's activity line: event count, the latest news, news per week."""
    return (f'<div class="strip"><span>{m["n_ev"]} events'
            + (f' · latest news published {esc(m["last"])} ({_ago(m["last"], as_of)})' if m["last"] else "")
            + f'</span>{activity_bars(m["weeks"], as_of, 80, 16)}</div>')


def status_changes(db: sqlite3.Connection, since: str) -> list[dict]:
    """Assessments that changed a target's status (or first assessed it), made on/after `since`.
    Same-day flips collapse to the day's final status (a re-assessment that ends where it began
    is not a change)."""
    names = {(r[0], r[1]): (r[2], r[3]) for r in db.execute("SELECT section, topic, name, kind FROM topics")}
    rows = db.execute("SELECT section, target, status, label, made_at FROM assessments "
                      "ORDER BY section, target, made_at, line").fetchall()
    days: dict[tuple, dict] = {}
    for r in rows:  # the status at the end of each day
        days.setdefault((r["section"], r["target"]), {})[r["made_at"]] = r
    out = []
    for (sec, target), byday in days.items():
        prev = None
        for day in sorted(byday):
            r = byday[day]
            if r["status"] != prev and day >= since:
                name, kind = names.get((sec, target), (target, None))
                out.append({"section": sec, "target": target, "name": name, "kind": kind, "day": day,
                            "prev": prev, "status": r["status"], "label": r["label"]})
            prev = r["status"]
    return out


def stream_html(db: sqlite3.Connection, as_of: dt.date, where: dict[str, tuple[str, str]], anchors: set[str]) -> str:
    """The news stream: the latest events by the date they became known, with the status
    changes of the same span (all of them while there are fewer events). where: section ->
    (its pane, its display title), for the sections with a pane only (a period's frozen
    framework may lack some), so every link lands. anchors: the topic anchors on the page."""
    secs = list(where)
    evs = db.execute(f"SELECT * FROM current_events WHERE section IN ({','.join('?' * len(secs))}) "
                     "ORDER BY known_at DESC, significance DESC, date_end DESC, id DESC LIMIT ?",
                     (*secs, STREAM_N)).fetchall()
    since = evs[-1]["known_at"] if len(evs) == STREAM_N else ""
    changes = [c for c in status_changes(db, since) if c["section"] in where]
    if not evs and not changes:
        return '<aside class="stream"><h3>Latest news</h3><div class="mute">no events yet</div></aside>'
    items: list[tuple[str, int, str]] = []
    for c in changes:
        sec = c["section"]
        pane, title = where[sec]
        a = f't-{sec}-{c["target"].replace(":", "-")}'
        frm = f'{marker(c["prev"], c["kind"])}→' if c["prev"] else '<span class="mute">first assessed</span> '
        items.append((c["day"], 0,
                      f'<li class="si chg x-{esc(pane)}"><a href="#{esc(a if a in anchors else sec)}">'
                      f'<span class="sm">{icon(sec)} {esc(title)} · status change</span>'
                      f'<span class="cl">{frm}{marker(c["status"], c["kind"])} <b>{plain_md(c["name"])}</b>: '
                      f'{esc(c["label"])}</span></a></li>'))
    for e in evs:
        sec, sig = e["section"], int(e["significance"] or 0)
        pane, title = where[sec]
        items.append((e["known_at"], 1,
                      f'<li class="si sig{sig} x-{esc(pane)}"><a href="{esc(ev_href(sec, e["id"]))}">'
                      f'<span class="sm">{icon(sec)} {esc(title)} · {esc(e["kind"])} · '
                      f'<span title="significance {sig}/3">{"●" * sig}{"○" * (3 - sig)}</span>'
                      f'{" · legacy" if e["verification_status"] == "legacy" else ""}</span>'
                      f'<span class="cl">{esc(e["claim"])}</span></a></li>'))
    items.sort(key=lambda x: (x[0], -x[1]), reverse=True)
    out, day = [], None
    for d, _, li in items:
        if d != day:
            if day is not None:
                out.append("</ul></li>")
            day = d
            out.append(f'<li class="dg"><div class="dh">{esc(fmt_date(d))} <span class="mute">{_ago(d, as_of)}'
                       f'</span></div><ul>')
        out.append(li)
    out.append("</ul></li>")
    return ('<aside class="stream"><div class="sh"><h3>Latest news</h3>'
            '<span class="mute small">newest first, by publication date</span></div>'
            '<div class="sf"><label title="significance 3/3, and status changes"><input type="checkbox" id="f-major"> major only</label>'
            '<label class="here"><input type="checkbox" id="f-here"> this endeavor only</label></div>'
            f'<ul class="days">{"".join(out)}</ul>'
            + (f'<p class="mute small">The {len(evs)} most recently published events and the status changes since '
               f'{esc(since)}. Older: each endeavor\'s event lists.</p>' if since else
               f'<p class="mute small">All {len(evs)} events and all status changes.</p>') + "</aside>")


def selection_css(panes: list[str], tracks: list[str]) -> str:
    """Per-pane rules for the pure-CSS pane switching (:target): highlight the nav item,
    dim (or, on request, hide) other endeavors' news; tracks = sections inside a pane."""
    out = []
    for s in panes:
        on = f"body:has(#{s}:target,#{s} :target)"
        out.append(f'{on} .nv[href="#{s}"]{{background:var(--sel);border-color:var(--acc)}}'
                   f"{on} .si:not(.x-{s}){{opacity:.55}}"
                   f"{on} .stream:has(#f-here:checked) .si:not(.x-{s}),"
                   f"{on} .stream:has(#f-here:checked) .dg:not(:has(.x-{s})),"
                   f"{on} .stream:has(#f-here:checked):has(#f-major:checked) .dg:not(:has(.x-{s}:is(.sig3,.chg)))"
                   "{display:none}")
    out += [f'body:has(#{s}:target,#{s} :target) .nv[href="#{s}"]{{background:var(--sel)}}' for s in tracks]
    return "@supports selector(:has(a)){" + "".join(out) + "}"


def _dashboard_html(db: sqlite3.Connection, as_of: dt.date, fw: dict, period: str | None,
                    covered: set[str] | None, note: str, periods: list[str]) -> str:
    secs = {r["section"]: r for r in db.execute("SELECT * FROM sections ORDER BY ord")}
    one = lambda q: db.execute(q).fetchone()[0]
    n_ev, n_leg = one("SELECT COUNT(*) FROM current_events"), \
        one("SELECT COUNT(*) FROM current_events WHERE verification_status='legacy'")
    n_sup = one("SELECT COUNT(*) FROM events WHERE NOT effective")
    n_obs = one("SELECT COUNT(*) FROM observations")
    gaps = db.execute("SELECT g.*, m.definition FROM gaps g JOIN metrics m USING (section, metric)").fetchall()
    cov = lambda s: covered is None or s in covered
    # endeavors: a section, or a group of sections shown as ONE endeavor (Robots and Automation:
    # Software + Hardware); a supplemental group's sections are endeavors of their own, listed apart
    panes, nav, cards, supp_nav, supp_cards = [], [], [], [], []
    where: dict[str, tuple[str, str]] = {}
    pane_ids, track_ids = [], []
    for e in fw["endeavors"]:
        if "sections" in e and not e.get("supplemental"):
            gid = slug(e["title"])
            tracks = [(fs["id"], fs["title"], glance(db, fs["id"], as_of, sequential(fs)), secs[fs["id"]]["kpi"], fs)
                      for fs in e["sections"] if fs["id"] in secs]
            if not tracks:
                continue
            m = merged([t[2] for t in tracks])
            nav.append(nav_group(db, gid, e["title"],
                                 [(s, t, g, cov(s), bool(k)) for s, t, g, k, _ in tracks], as_of))
            cards.append(group_card(db, gid, e["title"], [(s, t, g, k, None) for s, t, g, k, _ in tracks], as_of))
            jump = " · ".join(f'<a href="#{esc(s)}">{icon(s)} {esc(t)}</a>' for s, t, *_ in tracks)
            panes.append(f'<div class="pane" id="{esc(gid)}"><h2>{icon(gid)} {esc(e["title"])}</h2>'
                         f'{strip(m, as_of)}{md_block(e.get("intro"))}<div class="jump">{jump}</div>'
                         + "".join(section_html(db, secs[s], fs, covered=cov(s), track=True, head=strip(g, as_of))
                                   for s, _, g, _, fs in tracks) + "</div>")
            pane_ids.append(gid)
            for s, t, *_ in tracks:
                where[s] = (gid, f"{e['title']} · {t}")
                track_ids.append(s)
            continue
        supp = e.get("supplemental")
        for fs in (e["sections"] if "sections" in e else [e]):
            sec = fs["id"]
            if sec not in secs:
                continue
            g = glance(db, sec, as_of, sequential(fs))
            (supp_nav if supp else nav).append(nav_item(db, sec, fs["title"], g, cov(sec), bool(secs[sec]["kpi"]), as_of))
            (supp_cards if supp else cards).append(card(db, sec, fs["title"], secs[sec]["kpi"], g, as_of))
            panes.append(section_html(db, secs[sec], fs, covered=cov(sec), crumb=e["title"] if supp else "",
                                      head=strip(g, as_of)))
            pane_ids.append(sec)
            where[sec] = (sec, fs["title"])
    anchors = set(re.findall(r' id="(t-[^"]+)"', "".join(panes)))
    # a gap of a section without a pane (a period's frozen framework may lack it) is listed, unlinked
    def gap(g) -> str:
        sec = g["section"]
        name = esc(secs[sec]["title"])
        return (f'<li>{f"""<a href="#{esc(sec)}">{name}</a>""" if sec in where else name}: '
                f'<span title="{esc(g["metric"])}">{esc(metric_label(sec, g["metric"], g["definition"]))}</span>'
                f'{" (a KPI metric)" if g["required"] else ""} — <span class="gap">{esc(g["gap"])}</span></li>')
    gap_li = "".join(gap(g) for g in gaps)
    title = fw["title"] + (f" — {period}" if period else "")
    if period:
        when = (f'<div class="banner">Period page <b>{esc(period)}</b>: the ledger as of the period\'s cutoff '
                f'<b>{esc(as_of)}</b>, frozen. <a href="../">→ live dashboard</a></div>')
    else:
        when = ""
    stats = (f'<div class="mute small">{n_ev} events ({n_ev - n_leg} verified, {n_leg} legacy'
             f"{f'; {n_sup} superseded not shown' if n_sup else ''}) · {n_obs} observations · "
             f"{len(gaps)} metric gap(s)</div>")
    per = ("<p>Earlier periods: " + " · ".join(f'<a href="{esc(p)}/">{esc(p)}</a>' for p in periods) + "</p>"
           if periods else "")
    intro = (f'<div class="pane" id="intro"><div class="hero"><h1>{esc(title)}</h1>'
             f'<div class="tagline">{md_inline(fw["tagline"])}</div>'
             f'<div class="asof">{"Frozen" if period else "Live"} ledger state as of <b>{esc(as_of)}</b> · '
             f'{n_ev} events · {len(gaps)} data gap(s)</div></div>'
             f'<div class="manifesto">{md_block(fw["manifesto"])}</div>{legend_html()}'
             f'<h3>At a glance</h3><div class="cards">{"".join(cards)}</div>'
             + (f'<h3>Supplemental</h3><div class="cards">{"".join(supp_cards)}</div>' if supp_cards else "")
             + "</div>")
    side = (f'<nav class="side"><a class="brand" href="#intro"><b>{esc(fw["title"])}</b>'
            f'<span class="mute small">{"period " + esc(period) + ", " if period else ""}as of {esc(as_of)}</span></a>'
            f'<a class="nv ov" href="#intro"><span class="nt"><span class="ic">✦</span>'
            f'<span class="nn">Introduction &amp; overview</span></span></a>{"".join(nav)}'
            + (f'<div class="ng">Supplemental</div>{"".join(supp_nav)}' if supp_nav else "")
            + '<div class="nleg small mute">' + "".join(f"<span>{dot(st)}{w}</span>" for st, w in (
                ("green", "on track"), ("yellow", "behind pace"), ("red", "off track"), ("achieved", "achieved"),
                ("unknown", "unassessed"), (None, "not yet assessed")))
            + "<p>Per endeavor: the KPI's status dot and latest value (the series since the year shown), "
              "then one dot per milestone (joined when they form a sequence).</p><p>"
            + "".join(f'<span class="rc {c}">{t}</span> ' for c, t in (("r-hot", "≤ 1 week"), ("r-warm", "≤ 1 month"),
                                                                     ("r-cold", "older")))
            + "<br>how long ago its latest news was published</p></div></nav>")
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{esc(title)} (as of {esc(as_of)})</title><style>{CSS}{selection_css(pane_ids, track_ids)}</style>"
            f"</head><body>{side}<main>{when}"
            f'{f"<div class=note>{md_inline(note)}</div>" if note else ""}'
            + intro + "".join(panes)
            + '<footer>' + stats
            + (f"<details><summary>Data gaps ({len(gaps)})</summary><ul>{gap_li}</ul></details>" if gaps else "")
            + per
            + '<p class="mute small">Generated by views/explore.py from the Grand Endeavors ledger '
              '(<a href="https://github.com/pasky/grand-endeavors-data">data</a>, '
              '<a href="https://github.com/pasky/grand-endeavors">code and definitions</a>'
            + ('' if period else ', <a href="ledger.sqlite">ledger.sqlite</a> for Datasette')
            + ").</p></footer></main>"
            + stream_html(db, as_of, where, anchors) + "</body></html>\n")


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
    pgs = pages(cut, fw, period=name, covered=covered, note=note)  # render first, then replace atomically
    write_pages(period_dir, dict(sorted(pgs.items(), key=lambda kv: kv[0] == PAGE)), prune=True)  # index.html last
    return out


def site(out_dir: str, as_of: dt.date) -> list[str]:
    """The published directory: index.html + event logs (live), the frozen period pages
    (<period>/index.html + its event logs, copied from the data repo), ledger.sqlite +
    metadata.json, and dashboard.html redirecting to the old URL's successor."""
    import shutil
    os.makedirs(out_dir, exist_ok=True)
    periods = period_dirs()
    written = []
    for d in periods:
        os.makedirs(os.path.join(out_dir, d), exist_ok=True)
        frozen = [n for n in sorted(os.listdir(os.path.join(ledger.DATA, d)))
                  if n == PAGE or re.fullmatch(r"events-.+\.html", n)]
        for name in frozen:
            shutil.copy(os.path.join(ledger.DATA, d, name), os.path.join(out_dir, d, name))
            written.append(os.path.join(out_dir, d, name))
        prune_logs(os.path.join(out_dir, d), frozen)   # the published copy mirrors the data repo
    written += write_pages(out_dir, pages(as_of, periods=periods), prune=True)
    with open(os.path.join(out_dir, "dashboard.html"), "w", encoding="utf-8") as f:
        f.write('<!DOCTYPE html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=./">'
                '<title>Moved</title><a href="./">Grand Endeavors dashboard</a>\n')
    written.append(build(out_dir, as_of))
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
            pgs = pages(a.as_of, periods=period_dirs(), home=os.path.basename(a.out))
            for p in write_pages(os.path.dirname(os.path.abspath(a.out)), pgs):
                print(f"wrote {p} as of {a.as_of}")
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
