#!/usr/bin/env python3
"""Regression tests for explore.py (SQLite build + static dashboard).

Run:  uv run test_explorer.py      (stdlib, offline; builds a throwaway fixture ledger)
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import tempfile
from unittest import mock

import explore
import kpi
import ledger

FAILS = []
D = dt.date.fromisoformat


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


README = """# Five Grand Endeavors

## Climate and Environment

**KPI:** Atmospheric CO₂ concentration (ppm) and 10-year trend (ppm/year)

**Milestone Countdown:**
*   **The Bend:** Global emissions peak & decline.
*   **The Balance:** Net zero.

**Major Open Challenges:**
*   **Permanent Removal:** Durable carbon removal at gigaton scale.

## Supplemental
"""

REGISTRY = """metric,unit,cadence,release_lag_days,required_from,retired_after,definition
co2-monthly,ppm,monthly,7,pilot-26H1,,Monthly mean CO2 at a fixture station for tests
co2-trend,ppm/yr,annual,10,pilot-26H1,,Ten-year mean CO2 growth for the fixture tests
co2-never,ppm,monthly,7,pilot-26H1,,A required metric that was never observed at all
co2-old,ppm/yr,annual,,,pilot-2025,Retired decadal growth series kept only for history
co2-nolag,ppm,annual,,,,"Annual series with no regular release (empty lag) "" onmouseover=""x"
"""

OBS = [
    # metric, obs, value, unit, published, verification
    ("co2-monthly", "2026-05", "428.10", "ppm", "2026-06-07", "verified"),
    ("co2-monthly", "2026-06", "429.00", "ppm", "2026-07-07", "verified"),
    ("co2-monthly", "2026-06", "429.25", "ppm", "2026-07-20", "corrected"),  # source revision
    ("co2-trend", "2025", "2.56", "ppm/yr", "2026-01-10", "verified"),
    ("co2-trend", "2024", "2.64", "ppm/yr", "2025-01-10", "legacy"),
    ("co2-old", "2020", "2.4", "ppm/yr", "2025-01-03", "legacy"),
    ("co2-monthly", "2026-09", "430.00", "ppm", "2026-09-05", "verified"),  # period still in progress
    ("co2-nolag", "2023", "1.0", "ppm", "2024-02-01", "verified"),
]

EVENTS = [
    {"id": "2026-03-01-first-peak-claim", "date": "2026-03-01", "published": "2026-03-02",
     "published_basis": "source", "retrieved": "2026-03-05", "kind": "projection",
     "topics": ["milestone:the-bend"], "claim": "An agency projected that global fossil CO2 emissions peak in 2026.",
     "sources": [{"url": "https://example.org/a", "title": "Report A", "primary": True}],
     "significance": 2, "verification": {"status": "legacy"}, "collector": "backfill:test"},
    {"id": "2026-07-01-peak-update", "date": "2026-07-01", "published": "2026-07-02",
     "published_basis": "source", "retrieved": "2026-07-03", "kind": "data",
     "topics": ["kpi", "milestone:the-bend"],
     "claim": "Updated data <script>alert(1)</script> show fossil CO2 emissions fell 1% in H1 2026.",
     "sources": [{"url": "https://example.org/b?x=1&y=2", "title": "Data \"B\" & more", "primary": True},
                 {"url": "javascript:alert(2)", "title": "bad link", "primary": False}],
     "metrics": [{"metric": "co2-monthly", "obs": "2026-06", "value": "429.25"}],
     "significance": 3, "relates": [{"id": "2026-03-01-first-peak-claim", "rel": "update"}],
     "verification": {"status": "verified", "by": "verify-agent", "at": "2026-07-04"},
     "collector": "gather:climate/milestone-the-bend@2026-07-04"},
    {"id": "2026-09-30-late-news", "date": "2026-09-30", "published": "2026-10-05",
     "published_basis": "source", "retrieved": "2026-10-06", "kind": "announcement",
     "topics": ["beyond"], "claim": "A late announcement that is published after the default as-of.",
     "sources": [{"url": "https://example.org/c", "title": "C", "primary": True}],
     "significance": 1, "verification": {"status": "verified", "by": "v", "at": "2026-10-06"},
     "collector": "gather:test"},
]

ASSESSMENTS = [
    {"id": "climate-the-bend-2026-07-02", "target": "milestone:the-bend", "status": "green",
     "label": "Peak in sight", "made_at": "2026-07-02", "rationale": "Emissions fell \"><b onclick=alert(3)>.",
     "evidence": ["2026-07-01-peak-update"], "by": "assess-agent"},
    {"id": "climate-the-bend-2026-10-01", "target": "milestone:the-bend", "status": "red",
     "label": "Rebound", "made_at": "2026-10-01", "rationale": "Later judgment.",
     "evidence": [], "by": "assess-agent"},
]


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def make_fixture(root):
    write(root, "README.md", README)
    write(root, "metrics/climate.csv", REGISTRY)
    rows = [",".join(ledger.OBS_COLUMNS)]
    for m, o, v, u, pub, ver in OBS:
        rows.append(f"{m},{o},{v},{u},https://example.org/data,{pub},source,{pub},test:fixture,{ver},")
    write(root, "ledger/observations/climate.csv", "\n".join(rows) + "\n")
    write(root, "ledger/events/climate.jsonl", "".join(json.dumps(e) + "\n" for e in EVENTS))
    write(root, "ledger/assessments/climate.jsonl", "".join(json.dumps(a) + "\n" for a in ASSESSMENTS))
    write(root, "ledger/events/fusion.jsonl", "\n  \n")  # empty files must work like missing ones
    write(root, "ledger/assessments/fusion.jsonl", "")


def q(db, sql, *args):
    return db.execute(sql, args).fetchall()


def main():
    # pure date math
    ne = explore.next_expected
    case("next_expected monthly: month end + 1 month + lag", ne("monthly", "7", D("2026-01-31")) == D("2026-03-07"))
    case("next_expected quarterly", ne("quarterly", "0", D("2026-03-31")) == D("2026-06-30"))
    case("next_expected annual + lag", ne("annual", "10", D("2025-12-31")) == D("2027-01-10"))
    case("next_expected daily", ne("daily", "2", D("2026-05-10")) == D("2026-05-13"))
    case("next_expected weekly, zero lag", ne("weekly", "0", D("2026-05-10")) == D("2026-05-17"))
    case("next_expected leap year month end", ne("monthly", "0", D("2028-01-31")) == D("2028-02-29"))
    case("next_expected irregular -> None", ne("irregular", "5", D("2026-05-10")) is None)
    case("next_expected empty lag = no regular release -> None", ne("annual", "", D("2025-12-31")) is None)

    with tempfile.TemporaryDirectory() as root, \
            mock.patch.object(ledger, "ROOT", root), mock.patch.object(kpi, "ROOT", root):
        make_fixture(root)
        out = os.path.join(root, "build")
        explore.build(out, D("2026-09-28"))
        db = sqlite3.connect(os.path.join(out, "ledger.sqlite"))
        names = {r[0] for r in q(db, "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
        want = {"events", "event_topics", "event_sources", "event_relates", "observations", "assessments",
                "metrics", "sections", "topics", "latest_kpi", "milestone_status", "recent_events", "gaps"}
        case("all tables and views exist", want <= names)
        case("indexes exist", len(q(db, "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'")) >= 5)
        n = lambda t: q(db, f"SELECT COUNT(*) FROM {t}")[0][0]
        case("as-of filters events (late news excluded)", n("events") == 2)
        case("event_topics / sources / relates flattened",
             (n("event_topics"), n("event_sources"), n("event_relates")) == (3, 3, 1))
        case("observations incl. revisions", n("observations") == 8)
        case("assessments as-of (later one excluded)", n("assessments") == 1)
        case("sections: all SECTIONS, README-less ones included", n("sections") == len(ledger.SECTIONS))
        case("topics from README", {r[0] for r in q(db, "SELECT topic FROM topics WHERE section='climate'")}
             == {"kpi", "beyond", "milestone:the-bend", "milestone:the-balance", "challenge:permanent-removal"})
        ev = q(db, "SELECT known_at, verification_status, primary_url, json_array_length(relates) FROM events "
                   "WHERE id='2026-07-01-peak-update'")[0]
        case("event flattened columns", ev == ("2026-07-02", "verified", "https://example.org/b?x=1&y=2", 1))

        m = {r[0]: r[1:] for r in q(db, "SELECT metric, next_expected, overdue, status, required, retired, n_obs FROM metrics")}
        case("overdue monthly metric", m["co2-monthly"][:3] == ("2026-08-07", 1, "overdue"))
        case("annual metric on schedule", m["co2-trend"][:3] == ("2027-01-10", 0, "ok"))
        case("never-observed required metric", m["co2-never"] == (None, 0, "no data", 1, 0, 0))
        case("retired metric", m["co2-old"][2:5] == ("retired", 0, 1))
        case("empty lag: no schedule, not overdue", m["co2-nolag"][:3] == (None, 0, "ok"))
        gaps = {r[0]: r[1] for r in q(db, "SELECT metric, gap FROM gaps")}
        case("gaps view", gaps == {"co2-monthly": "overdue since 2026-08-07", "co2-never": "never observed"})

        k = q(db, "SELECT value_text, prev_value_text, change, obs, prev_obs FROM latest_kpi WHERE metric='co2-monthly'")[0]
        case("latest_kpi uses revised value + previous obs, skips in-progress period",
             k == ("429.25", "428.10", 1.15, "2026-06", "2026-05"))
        when = D("2026-09-28")
        table = ledger.obs_as_of("climate", when)
        same = all((ledger.latest_obs(table, mm, when) or {}).get("obs") == obs and
                   (ledger.latest_obs(table, mm, when) or {}).get("value") == val
                   for mm, obs, val in q(db, "SELECT metric, obs, value_text FROM latest_kpi"))
        case("latest_kpi agrees with ledger.latest_obs(obs_as_of)", same)
        ass = ledger.assessment_as_of("climate", when)
        case("milestone_status agrees with ledger.assessment_as_of",
             {t: a["id"] for t, a in ass.items()} ==
             dict(q(db, "SELECT target, assessment_id FROM milestone_status WHERE assessment_id IS NOT NULL")))
        ms = {r[0]: r[1] for r in q(db, "SELECT target, status FROM milestone_status WHERE section='climate'")}
        case("milestone_status latest + not yet assessed",
             ms.get("milestone:the-bend") == "green" and ms.get("milestone:the-balance") == "not yet assessed"
             and "beyond" not in ms)
        case("recent_events newest known first", q(db, "SELECT id FROM recent_events")[0][0] == "2026-07-01-peak-update")

        meta = json.load(open(os.path.join(out, "metadata.json")))
        queries = meta["databases"]["ledger"]["queries"]
        case("metadata: canned queries", {"kpi_dashboard", "events_by_milestone", "lifecycle_threads",
                                          "legacy_vs_verified", "overdue_metrics"} <= set(queries))
        ok = True
        for name, qq in queries.items():
            try:
                db.execute(qq["sql"], {"topic": "milestone:the-bend"}).fetchall()
            except sqlite3.Error as e:
                print(f"     {name}: {e}")
                ok = False
        case("canned queries execute", ok)
        thread = q(db, queries["lifecycle_threads"]["sql"])
        case("lifecycle thread via relates", len(thread) == 1 and thread[0][1] == "2026-03-01-first-peak-claim")
        legacy = {(r[1], r[2]): r[3] for r in q(db, queries["legacy_vs_verified"]["sql"])}
        case("legacy vs verified counts", legacy[("events", "legacy")] == 1 and legacy[("observations", "legacy")] == 2)
        db.close()

        # earlier / later as-of: revision not yet known; later assessment + event visible
        db = sqlite3.connect(":memory:")
        explore.build_db(db, D("2026-07-10"))
        case("as-of before revision -> original value",
             q(db, "SELECT value_text FROM latest_kpi WHERE metric='co2-monthly'")[0][0] == "429.00")
        db = sqlite3.connect(":memory:")
        explore.build_db(db, D("2026-10-10"))
        case("later as-of sees late event + newer assessment",
             q(db, "SELECT COUNT(*) FROM events")[0][0] == 3 and
             q(db, "SELECT status FROM milestone_status WHERE target='milestone:the-bend'")[0][0] == "red")

        page = explore.dashboard(D("2026-09-28"))
        case("dashboard escapes claims", "<script>alert(1)" not in page and "&lt;script&gt;alert(1)" in page)
        case("dashboard escapes source titles/urls", "Data &quot;B&quot; &amp; more" in page
             and 'href="https://example.org/b?x=1&amp;y=2"' in page)
        case("dashboard drops non-http links", "javascript:" not in page)
        case("dashboard links rel=noopener", 'rel="noopener noreferrer"' in page)
        case("dashboard self-contained (no script/link/src)",
             not any(s in page for s in ("<script", "<link", " src=", "@import")))
        case("dashboard gap markers", all(s in page for s in ("OVERDUE", "no data yet", "not yet assessed",
                                                             "no events in the ledger yet", "no metrics registered yet")))
        case("dashboard legacy/verified badges", '<span class="badge b-legacy">legacy</span></div>'
             '<div>An agency' in page and '<span class="badge b-verified">verified</span>' in page)
        case("dashboard escapes attributes", "<b onclick" not in page and '" onmouseover="' not in page
             and "&quot;&gt;&lt;b onclick" in page)
        case("dashboard sparkline", "<svg" in page and "<polyline" in page)
        case("dashboard change vs previous", "+1.15" in page)
        case("dashboard lifecycle link", 'href="#ev-climate-2026-03-01-first-peak-claim"' in page)
        case("dashboard as-of excludes late event", "late announcement" not in page)
        case("dashboard deterministic", page == explore.dashboard(D("2026-09-28")))

        with mock.patch.object(sys, "argv", ["explore.py", "dashboard", "--as-of", "2026-09-28",
                                             "--out", os.path.join(out, "d.html")]):
            rc = explore.main()
        case("CLI dashboard", rc == 0 and open(os.path.join(out, "d.html"), encoding="utf-8").read() == page)

    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall explorer tests passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
