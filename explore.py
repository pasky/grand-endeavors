#!/usr/bin/env python3
"""Grand Endeavors explorer: derived, read-only views of the ledger
(DESIGN.md §1 "explorer (SQLite/Datasette)"). Nothing here is canonical;
outputs go to build/ (gitignored) and can be rebuilt at any time.

COMMANDS
  explore.py build     [--out build/] [--as-of YYYY-MM-DD]
        -> <out>/ledger.sqlite (tables, indexes, views) + <out>/metadata.json (Datasette)
  explore.py dashboard [--out build/dashboard.html] [--as-of YYYY-MM-DD]
        -> one self-contained static HTML dashboard (no JS/CSS/CDN dependencies)

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

import kpi
import ledger

SCHEMA = """
CREATE TABLE build_info (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE sections (section TEXT PRIMARY KEY, ord INTEGER, grp TEXT, title TEXT, kpi TEXT);
CREATE TABLE topics (section TEXT, topic TEXT, kind TEXT, slug TEXT, name TEXT, description TEXT,
    ord INTEGER, PRIMARY KEY (section, topic));
CREATE TABLE events (section TEXT, id TEXT, date TEXT, date_end TEXT, published TEXT,
    published_basis TEXT, retrieved TEXT, known_at TEXT, kind TEXT, significance INTEGER,
    claim TEXT, verification_status TEXT, verified_by TEXT, verified_at TEXT, collector TEXT,
    note TEXT, primary_url TEXT, topics JSON, sources JSON, metrics JSON, relates JSON,
    verification JSON, line INTEGER, PRIMARY KEY (section, id));
CREATE TABLE event_topics (section TEXT, event_id TEXT, topic TEXT);
CREATE TABLE event_sources (section TEXT, event_id TEXT, ord INTEGER, url TEXT, title TEXT, is_primary INTEGER);
CREATE TABLE event_relates (section TEXT, event_id TEXT, rel TEXT, related_id TEXT);
CREATE TABLE observations (section TEXT, metric TEXT, obs TEXT, obs_start TEXT, obs_end TEXT,
    value REAL, value_text TEXT, unit TEXT, source TEXT, published TEXT, published_basis TEXT,
    retrieved TEXT, known_at TEXT, collector TEXT, verification TEXT, note TEXT, line INTEGER);
CREATE TABLE assessments (section TEXT, id TEXT, target TEXT, status TEXT, label TEXT, made_at TEXT,
    known_at TEXT, rationale TEXT, evidence JSON, by TEXT, line INTEGER);
CREATE TABLE metrics (section TEXT, metric TEXT, unit TEXT, cadence TEXT, release_lag_days INTEGER,
    required_from TEXT, retired_after TEXT, definition TEXT, required INTEGER, retired INTEGER,
    n_obs INTEGER, latest_obs TEXT, latest_obs_end TEXT, latest_known_at TEXT, next_expected TEXT,
    overdue INTEGER, status TEXT, PRIMARY KEY (section, metric));

CREATE INDEX ev_known ON events (known_at);
CREATE INDEX ev_date ON events (date_end);
CREATE INDEX evt_topic ON event_topics (topic, section);
CREATE INDEX evt_event ON event_topics (section, event_id);
CREATE INDEX evs_url ON event_sources (url);
CREATE INDEX evr_related ON event_relates (section, related_id);
CREATE INDEX obs_metric ON observations (section, metric, obs_end);
CREATE INDEX obs_known ON observations (known_at);
CREATE INDEX ass_target ON assessments (section, target, made_at);

-- the latest-known row per (metric, obs): source revisions are appended, never overwritten
CREATE VIEW current_obs AS
SELECT * FROM (SELECT o.*, ROW_NUMBER() OVER (PARTITION BY section, metric, obs
                ORDER BY known_at DESC, retrieved DESC, line DESC) AS rn FROM observations o)
WHERE rn = 1;

-- headline candidates: only periods that have ended by as_of (as ledger.latest_obs(..., when))
CREATE VIEW headline_obs AS
SELECT * FROM current_obs WHERE obs_end <= (SELECT value FROM build_info WHERE key = 'as_of');

CREATE VIEW latest_kpi AS
WITH ranked AS (SELECT h.*, ROW_NUMBER() OVER (PARTITION BY section, metric
                ORDER BY obs_end DESC, obs_start DESC) AS k FROM headline_obs h)
SELECT m.section, m.metric, m.unit, m.required, m.retired, m.cadence,
       cur.obs, cur.value, cur.value_text, cur.known_at, cur.verification, cur.source,
       prev.obs AS prev_obs, prev.value AS prev_value, prev.value_text AS prev_value_text,
       round(cur.value - prev.value, 9) AS change, m.next_expected, m.overdue, m.status, m.definition
FROM metrics m
LEFT JOIN ranked cur ON cur.section = m.section AND cur.metric = m.metric AND cur.k = 1
LEFT JOIN ranked prev ON prev.section = m.section AND prev.metric = m.metric AND prev.k = 2
ORDER BY m.section, m.required DESC, m.metric;

CREATE VIEW milestone_status AS
WITH ranked AS (SELECT a.*, ROW_NUMBER() OVER (PARTITION BY section, target
                ORDER BY made_at DESC, line DESC) AS k FROM assessments a)
SELECT t.section, t.topic AS target, t.kind, t.name, t.ord,
       COALESCE(a.status, 'not yet assessed') AS status, a.label, a.made_at, a.rationale,
       a.evidence, a.id AS assessment_id,
       (SELECT COUNT(*) FROM event_topics et
         WHERE et.section = t.section AND et.topic = t.topic) AS n_events
FROM topics t LEFT JOIN ranked a ON a.section = t.section AND a.target = t.topic AND a.k = 1
WHERE t.kind != 'beyond'
ORDER BY t.section, t.ord;

CREATE VIEW recent_events AS
SELECT section, known_at, date, id, kind, significance, verification_status, claim, primary_url, topics
FROM events ORDER BY known_at DESC, date_end DESC, id DESC;

CREATE VIEW gaps AS
SELECT section, metric, unit, required, cadence, latest_obs, next_expected, status,
       CASE WHEN n_obs = 0 THEN 'never observed' ELSE 'overdue since ' || next_expected END AS gap
FROM metrics WHERE NOT retired AND (overdue OR n_obs = 0)
ORDER BY required DESC, section, metric;
"""

TABLE_DOCS = {
    "build_info": "Build parameters (as_of: the known_at cutoff applied to every record).",
    "sections": "README endeavors (sections), in README order, with their KPI line.",
    "topics": "Topic tags per section from README: kpi, milestone:<slug>, challenge:<slug>, beyond.",
    "events": "News/claims (ledger/events). known_at = published. JSON columns keep nested fields.",
    "event_topics": "One row per (event, topic tag).",
    "event_sources": "One row per event source URL (ord 0 = first-listed).",
    "event_relates": "Event lifecycle links: event_id --rel--> related_id (update, retraction, ...).",
    "observations": "KPI datapoints incl. source revisions (ledger/observations); known_at = published.",
    "assessments": "Timestamped milestone/KPI status judgments; known_at = made_at.",
    "metrics": "Metric registry (metrics/*.csv) + derived: latest obs, next_expected "
               "(latest obs end + cadence + release_lag_days), overdue vs as_of.",
    "current_obs": "Latest-known row per (metric, obs) (revisions resolved).",
    "headline_obs": "current_obs restricted to periods that ended by as_of (headline/schedule basis).",
    "latest_kpi": "Latest value per registered metric, with the previous obs and the change.",
    "milestone_status": "Latest assessment per milestone/challenge/kpi target ('not yet assessed' if none).",
    "recent_events": "Events, most recently known first.",
    "gaps": "Registered (non-retired) metrics that are overdue or were never observed.",
}

QUERIES = {
    "kpi_dashboard": ("KPI dashboard", "Latest value, change vs previous obs and schedule per metric.",
        "SELECT section, metric, required, value_text || ' ' || unit AS latest, obs, known_at, "
        "verification, prev_value_text AS previous, prev_obs, round(change, 4) AS change, "
        "next_expected, status FROM latest_kpi WHERE NOT retired ORDER BY section, required DESC, metric"),
    "events_by_milestone": ("Events by milestone", "Events tagged with a topic, e.g. milestone:the-bend.",
        "SELECT e.section, e.date, e.known_at, e.kind, e.significance, e.verification_status, e.claim, "
        "e.primary_url FROM event_topics t JOIN events e ON e.section = t.section AND e.id = t.event_id "
        "WHERE t.topic = :topic ORDER BY e.date_end DESC, e.id DESC"),
    "lifecycle_threads": ("Lifecycle threads", "Event pairs linked via relates (later event -> earlier one).",
        "SELECT r.section, r.related_id AS earlier_id, b.date AS earlier_date, b.claim AS earlier_claim, "
        "r.rel, r.event_id AS later_id, a.date AS later_date, a.claim AS later_claim "
        "FROM event_relates r JOIN events a ON a.section = r.section AND a.id = r.event_id "
        "LEFT JOIN events b ON b.section = r.section AND b.id = r.related_id "
        "ORDER BY r.section, r.related_id, a.date_end"),
    "legacy_vs_verified": ("Legacy vs verified", "Record counts by verification status.",
        "SELECT section, 'events' AS records, verification_status AS verification, COUNT(*) AS n "
        "FROM events GROUP BY 1, 2, 3 UNION ALL "
        "SELECT section, 'observations', verification, COUNT(*) FROM observations GROUP BY 1, 2, 3 "
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


def readme_meta(section: str) -> tuple[str, str, str, dict[str, str]]:
    """(group, title, KPI line, {topic name: description}) from README.md.
    (ledger.readme_topics gives slugs/names only; this adds the prose.)"""
    head = ledger._HEADINGS[section]
    lines = open(os.path.join(ledger.ROOT, "README.md"), encoding="utf-8").read().splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == head), None)
    if start is None:
        return "", head.lstrip("# "), "", {}
    level = len(head.split()[0])
    end = next((i for i in range(start + 1, len(lines)) if re.match(r"^#{1,%d} " % level, lines[i])), len(lines))
    group = ""
    if level > 2:
        group = next((ln[3:].strip() for ln in reversed(lines[:start]) if ln.startswith("## ")), "")
    body = lines[start:end]
    kpi_line = next((ln.split("**KPI:**", 1)[1].strip() for ln in body if ln.startswith("**KPI:**")), "")
    desc = {}
    for ln in body:
        if m := re.match(r"^\*\s+\*\*(.+?)\*\*:?\s*(.*)$", ln):
            desc[m[1].rstrip(":").strip().strip('"“”')] = m[2].strip()
    return group, head.lstrip("# "), kpi_line, desc


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
def build_db(db: sqlite3.Connection, as_of: dt.date) -> None:
    db.executescript(SCHEMA)
    ins = lambda table, row: db.execute(
        f"INSERT INTO {table} VALUES ({','.join('?' * len(row))})", row)
    ins("build_info", ("as_of", str(as_of)))
    for n, sec in enumerate(ledger.SECTIONS):
        group, title, kpi_line, desc = readme_meta(sec)
        ins("sections", (sec, n, group, title, kpi_line))
        try:
            t = ledger.readme_topics(sec)
        except StopIteration:  # section heading not in README
            t = {"milestones": [], "challenges": []}
        tops = [("kpi", "kpi", "kpi", "KPI", kpi_line)]
        tops += [(f"milestone:{s}", "milestone", s, name, desc.get(name, "")) for s, name in t["milestones"]]
        tops += [(f"challenge:{s}", "challenge", s, name, desc.get(name, "")) for s, name in t["challenges"]]
        tops.append(("beyond", "beyond", "beyond", "Beyond the framework", ""))
        for i, (topic, kind, slug, name, d) in enumerate(tops):
            ins("topics", (sec, topic, kind, slug, name, d, i))

        for e, known in _known(ledger.events(sec), as_of, f"events/{sec}"):
            v = e.get("verification") or {}
            srcs = [s for s in e.get("sources") or [] if isinstance(s, dict)]
            ins("events", (sec, e.get("id"), e.get("date"), _date_end(e.get("date", "")), e.get("published"),
                           e.get("published_basis"), e.get("retrieved"), known, e.get("kind"),
                           e.get("significance"), e.get("claim"), v.get("status"), v.get("by"), v.get("at"),
                           e.get("collector"), e.get("note"), srcs[0].get("url") if srcs else None,
                           _j(e.get("topics")), _j(e.get("sources")), _j(e.get("metrics")),
                           _j(e.get("relates")), _j(v), e.get("_line")))
            for tp in e.get("topics") or []:
                ins("event_topics", (sec, e.get("id"), tp))
            for i, s in enumerate(srcs):
                ins("event_sources", (sec, e.get("id"), i, s.get("url"), s.get("title"), int(bool(s.get("primary")))))
            for r in e.get("relates") or []:
                ins("event_relates", (sec, e.get("id"), r.get("rel"), r.get("id")))

        for r, known in _known(ledger.observations(sec), as_of, f"observations/{sec}"):
            try:
                start, end = kpi.obs_range(r["obs"])
                value = float(r["value"])
            except ValueError:
                warn(f"observations/{sec}:{r['_line']}: skipping malformed obs/value")
                continue
            ins("observations", (sec, r["metric"], r["obs"], str(start), str(end), value, r["value"],
                                 r["unit"], r["source"], r["published"], r["published_basis"],
                                 r["retrieved"], known, r["collector"], r["verification"], r["note"], r["_line"]))

        for a, known in _known(ledger.assessments(sec), as_of, f"assessments/{sec}"):
            ins("assessments", (sec, a.get("id"), a.get("target"), a.get("status"), a.get("label"),
                                a.get("made_at"), known, a.get("rationale"), _j(a.get("evidence")),
                                a.get("by"), a.get("_line")))

        reg, _ = kpi.load_registry(sec)
        for m, row in (reg or {}).items():
            rows = db.execute("SELECT obs, obs_end, known_at FROM headline_obs WHERE section=? AND metric=? "
                              "ORDER BY obs_end DESC, obs_start DESC", (sec, m)).fetchall()
            last = rows[0] if rows else None
            retired = bool(row["_ret"] and as_of > row["_ret"])
            nxt = next_expected(row["cadence"], row["release_lag_days"], D(last[1])) if last else None
            overdue = bool(nxt and nxt < as_of and not retired)
            status = ("retired" if retired else "no data" if not last else "overdue" if overdue else "ok")
            ins("metrics", (sec, m, row["unit"], row["cadence"],
                            int(row["release_lag_days"]) if row["release_lag_days"].isdigit() else None,
                            row["required_from"], row["retired_after"], row["definition"],
                            int(kpi.required_active(row, as_of)), int(retired), len(rows),
                            *(last or (None, None, None)),
                            nxt and str(nxt), int(overdue), status))
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
:root{--bg:#f6f7f9;--card:#fff;--ink:#1d2330;--mute:#6b7385;--line:#e2e5ea;--green:#1f9d55;
--yellow:#d69e2e;--red:#d64545;--gap:#b83280;--acc:#2b6cb0}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;
background:var(--bg);color:var(--ink)}header,main{max-width:1180px;margin:0 auto;padding:16px}
header h1{margin:0 0 4px;font-size:22px}.mute{color:var(--mute)}a{color:var(--acc)}
nav a{margin-right:10px;white-space:nowrap}section{background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:14px 18px;margin:16px 0}section h2{margin:0;font-size:19px}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:var(--mute);margin:16px 0 6px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
.tile{border:1px solid var(--line);border-radius:8px;padding:10px;background:#fbfcfd}
.tile .m{font-weight:600;font-size:12px;word-break:break-word}.tile .v{font-size:24px;font-weight:700}
.tile .v small{font-size:13px;color:var(--mute);font-weight:400}.tile .d,.tile .c{font-size:12px;color:var(--mute)}
.up,.down{color:var(--ink)}.spark{display:block;margin:4px 0;color:var(--acc)}
.gap{color:var(--gap);font-weight:700}.tile.nodata,.tile.overdue{border:2px dashed var(--gap);background:#fff5fa}
.badge{display:inline-block;font-size:11px;border-radius:4px;padding:0 5px;margin-left:4px;
border:1px solid currentColor;vertical-align:1px}.b-legacy{color:#975a16;background:#fffaf0}
.b-verified,.b-corrected,.b-collector{color:var(--green)}.b-req{color:var(--acc)}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:0}
.s-green{background:var(--green)}.s-yellow{background:var(--yellow)}.s-red{background:var(--red)}
.s-none{border:2px dashed var(--mute)}ul{padding-left:0;list-style:none;margin:0}
li.ms,li.ev{padding:5px 0;border-bottom:1px solid var(--line)}li.ev .meta{font-size:12px;color:var(--mute)}
.chip{font-size:11px;background:#edf2f7;border-radius:3px;padding:0 4px;margin-right:3px}
.sig3{font-weight:600}.rel{font-size:12px;color:var(--mute);margin-left:12px}
details summary{cursor:pointer;color:var(--acc);margin:6px 0}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:0 28px}
"""


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def link(url, text) -> str:
    if url and ledger.URL_RE.match(str(url)):
        return f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(text)}</a>'
    return esc(text)


def badge(status) -> str:
    return f'<span class="badge b-{esc(status)}">{esc(status or "unverified")}</span>'


def _decimals(s: str | None) -> int:
    return len(s.split(".")[1]) if s and "." in s else 0


def sparkline(points: list[tuple[dt.date, float]], w: int = 200, h: int = 34, pad: int = 3) -> str:
    if len(points) < 2:
        return ""
    x0, x1 = points[0][0].toordinal(), points[-1][0].toordinal()
    lo, hi = min(v for _, v in points), max(v for _, v in points)
    sx = lambda d: pad + (w - 2 * pad) * ((d.toordinal() - x0) / (x1 - x0) if x1 > x0 else 0.5)
    sy = lambda v: h - pad - (h - 2 * pad) * ((v - lo) / (hi - lo) if hi > lo else 0.5)
    pts = " ".join(f"{sx(d):.1f},{sy(v):.1f}" for d, v in points)
    d, v = points[-1]
    return (f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img">'
            f'<title>{len(points)} obs {points[0][0]}..{d}; range {lo:g}..{hi:g}</title>'
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
    if k["prev_obs"] is not None:
        ch = k["change"]
        cls, arrow = ("up", "▲") if ch > 0 else ("down", "▼") if ch < 0 else ("", "=")
        dec = max(_decimals(k["value_text"]), _decimals(k["prev_value_text"]))
        body += (f'<div class="c"><span class="{cls}">{arrow} {ch:+.{dec}f}</span> vs '
                 f'{esc(k["prev_value_text"])} ({esc(k["prev_obs"])})</div>')
    pts = [(dt.date.fromisoformat(r["obs_end"]), r["value"]) for r in db.execute(
        "SELECT obs_end, value FROM headline_obs WHERE section=? AND metric=? ORDER BY obs_end, obs_start",
        (k["section"], k["metric"]))]
    body += sparkline(pts)
    if k["overdue"]:
        body += f'<div class="gap">OVERDUE — next obs expected by {esc(k["next_expected"])}</div>'
    elif k["next_expected"]:
        body += f'<div class="d">next expected by {esc(k["next_expected"])}</div>'
    else:
        body += f'<div class="d">{esc(k["cadence"])} cadence (no schedule)</div>'
    return f'<div class="tile{" overdue" if k["overdue"] else ""}">{head}{body}</div>'


def event_li(e: sqlite3.Row, names: dict[str, str]) -> str:
    sig = int(e["significance"] or 0)
    chips = "".join(f'<span class="chip">{esc(names.get(t, t))}</span>' for t in json.loads(e["topics"] or "[]"))
    srcs = json.loads(e["sources"] or "[]")
    links = " ".join(link(s.get("url"), f"[{i}] {s.get('title') or 'source'}")
                     for i, s in enumerate(srcs, 1) if isinstance(s, dict))
    rels = "".join(f'<div class="rel">↳ {esc(r.get("rel"))} of '
                   f'<a href="#ev-{esc(e["section"])}-{esc(r.get("id"))}">{esc(r.get("id"))}</a></div>'
                   for r in json.loads(e["relates"] or "[]") if isinstance(r, dict))
    return (f'<li class="ev sig{sig}" id="ev-{esc(e["section"])}-{esc(e["id"])}">'
            f'<div class="meta">{esc(e["date"])} · {esc(e["kind"])} · '
            f'<span title="significance {sig}/3">{"●" * sig}{"○" * (3 - sig)}</span> · '
            f'known {esc(e["known_at"])}{badge(e["verification_status"])}</div>'
            f'<div>{esc(e["claim"])}</div><div>{chips} {links}</div>{rels}</li>')


def section_html(db: sqlite3.Connection, s: sqlite3.Row, n_recent: int = 8) -> str:
    sec = s["section"]
    out = [f'<section id="{esc(sec)}"><h2>{esc(s["grp"] + " › " if s["grp"] else "")}{esc(s["title"])}</h2>']
    out.append(f'<div class="mute">KPI: {esc(s["kpi"]) if s["kpi"] else "<span class=gap>no KPI defined in README</span>"}</div>')
    out.append("<h3>KPI metrics</h3>")
    tiles = db.execute("SELECT * FROM latest_kpi WHERE section=? AND NOT retired "
                       "ORDER BY required DESC, metric", (sec,)).fetchall()
    if not tiles:
        out.append(f'<div class="gap">no metrics registered yet (metrics/{esc(sec)}.csv)</div>')
    elif not any(t["required"] for t in tiles):
        out.append('<div class="gap">no required KPI metric in the registry yet</div>')
    out.append('<div class="tiles">' + "".join(kpi_tile(db, t) for t in tiles) + "</div>")

    out.append('<div class="cols"><div>')
    ms = db.execute("SELECT * FROM milestone_status WHERE section=? ORDER BY ord", (sec,)).fetchall()
    for kind, title in (("kpi", "KPI assessment"), ("milestone", "Milestones"), ("challenge", "Challenges")):
        rows = [m for m in ms if m["kind"] == kind]
        if not rows:
            if kind != "kpi":
                out.append(f'<h3>{title}</h3><div class="gap">none listed in README</div>')
            continue
        out.append(f"<h3>{title}</h3><ul>")
        for m in rows:
            if m["assessment_id"]:
                st = (f'<span class="dot s-{esc(m["status"])}"></span><b>{esc(m["name"])}</b> — '
                      f'{esc(m["label"])} <span class="mute">({esc(m["status"])}, assessed {esc(m["made_at"])})</span>')
            else:
                st = (f'<span class="dot s-none"></span><b>{esc(m["name"])}</b> — '
                      f'<span class="gap">not yet assessed</span>')
            out.append(f'<li class="ms" title="{esc(m["rationale"] or "")}">{st} '
                       f'<span class="mute">· {m["n_events"]} event(s)</span></li>')
        out.append("</ul>")

    names = {r["topic"]: r["name"] for r in db.execute("SELECT topic, name FROM topics WHERE section=?", (sec,))}
    evs = db.execute("SELECT * FROM events WHERE section=? ORDER BY known_at DESC, date_end DESC, id DESC",
                     (sec,)).fetchall()
    out.append(f"</div><div><h3>Latest events ({len(evs)})</h3>")
    if not evs:
        out.append('<div class="gap">no events in the ledger yet</div>')
    out.append("<ul>" + "".join(event_li(e, names) for e in evs[:n_recent]) + "</ul>")
    if len(evs) > n_recent:
        out.append(f"<details><summary>{len(evs) - n_recent} older event(s)</summary><ul>"
                   + "".join(event_li(e, names) for e in evs[n_recent:]) + "</ul></details>")
    return "".join(out) + "</div></div></section>"


def dashboard(as_of: dt.date) -> str:
    db = sqlite3.connect(":memory:")
    try:
        build_db(db, as_of)
        db.row_factory = sqlite3.Row
        return _dashboard_html(db, as_of)
    finally:
        db.close()


def _dashboard_html(db: sqlite3.Connection, as_of: dt.date) -> str:
    secs = db.execute("SELECT * FROM sections ORDER BY ord").fetchall()
    one = lambda q: db.execute(q).fetchone()[0]
    n_ev, n_leg = one("SELECT COUNT(*) FROM events"), one("SELECT COUNT(*) FROM events WHERE verification_status='legacy'")
    n_obs = one("SELECT COUNT(*) FROM observations")
    gaps = db.execute("SELECT * FROM gaps").fetchall()
    gap_li = "".join(f'<li><a href="#{esc(g["section"])}">{esc(g["section"])}</a>: {esc(g["metric"])}'
                     f'{" (required)" if g["required"] else ""} — <span class="gap">{esc(g["gap"])}</span></li>'
                     for g in gaps)
    nav = "".join(f'<a href="#{esc(s["section"])}">{esc(s["title"])}</a>' for s in secs)
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Grand Endeavors — dashboard as of {esc(as_of)}</title><style>{CSS}</style></head><body>"
            f"<header><h1>Grand Endeavors — ledger dashboard</h1>"
            f'<div class="mute">As of <b>{esc(as_of)}</b> (records with known_at ≤ as-of) · {n_ev} events '
            f"({n_ev - n_leg} verified, {n_leg} legacy) · {n_obs} observations · {len(gaps)} metric gap(s)</div>"
            f"<nav>{nav}</nav>"
            + (f"<h3>Gaps</h3><ul>{gap_li}</ul>" if gaps else "")
            + "</header><main>" + "".join(section_html(db, s) for s in secs)
            + '<p class="mute">Generated by explore.py from the Grand Endeavors ledger. '
              '<span class="badge b-legacy">legacy</span> = converted from pilot-2025, not verified at ingest.</p>'
            + "</main></body></html>\n")


# --- CLI ----------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--out", default=os.path.join(ledger.ROOT, "build"))
    d = sub.add_parser("dashboard"); d.add_argument("--out", default=os.path.join(ledger.ROOT, "build", "dashboard.html"))
    for p in (b, d):
        p.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date.today(), help="YYYY-MM-DD (default: today)")
    a = ap.parse_args()
    try:
        if a.cmd == "build":
            p = build(a.out, a.as_of)
            db = sqlite3.connect(p)
            counts = {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("events", "observations", "assessments", "metrics", "gaps")}
            db.close()
            print(f"wrote {p} (+ metadata.json) as of {a.as_of}: {counts}")
        else:
            os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
            with open(a.out, "w", encoding="utf-8") as f:
                f.write(dashboard(a.as_of))
            print(f"wrote {a.out} as of {a.as_of}")
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
