#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Regression tests for explore.py (SQLite build + static dashboard).

Run:  uv run views/tests/test_explorer.py      (stdlib, offline; builds a throwaway fixture ledger)
"""
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import tempfile
from unittest import mock

VIEWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [VIEWS, os.path.join(os.path.dirname(VIEWS), "core")]
import explore  # noqa: E402
import kpi  # noqa: E402
import ledger  # noqa: E402

FAILS = []
D = dt.date.fromisoformat


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


FRAMEWORK = """title: Five Grand Endeavors
tagline: Tracking humanity's progress.
manifesto: Science has a communication problem.
endeavors:
  - id: climate
    title: Climate and Environment
    intro: Fixing the past.
    kpi: Atmospheric CO₂ concentration (ppm) and 10-year trend (ppm/year)
    milestones:
      - {slug: the-bend, name: The Bend, description: Global emissions peak & decline.}
      - {slug: the-balance, name: The Balance, description: Net zero.}
    challenges:
      - {slug: permanent-removal, name: Permanent Removal, description: Durable carbon removal at gigaton scale.}
  - title: Supplemental
    supplemental: true
    sections:
      - {id: knowledge-beyond, title: The Knowledge Beyond, intro: Deep understanding.}
"""

REGISTRY = """metric,unit,cadence,release_lag_days,required_from,retired_after,definition
co2-monthly,ppm,monthly,7,pilot-26H1,,Monthly mean CO2 at a fixture station for tests
co2-trend,ppm/yr,annual,10,pilot-26H1,,Ten-year mean CO2 growth for the fixture tests
co2-never,ppm,monthly,7,pilot-26H1,,A required metric that was never observed at all
co2-old,ppm/yr,annual,,,pilot-2025,Retired decadal growth series kept only for history
horizon,minutes,irregular,,,,Task horizon with both dated (daily) and monthly obs labels
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
    ("co2-monthly", "2025-06", "426.00", "ppm", "2025-07-07", "verified"),  # year-ago comparison
    # precedence: a LATER-dated legacy row must not override the verified value
    ("co2-monthly", "2026-04", "427.80", "ppm", "2026-05-07", "verified"),
    ("co2-monthly", "2026-04", "427.9", "ppm", "2026-08-01", "legacy"),
    # mixed granularity: 3 daily obs + 1 monthly headline obs
    ("horizon", "2026-01-10", "30", "minutes", "2026-01-10", "collector"),
    ("horizon", "2026-03-05", "45", "minutes", "2026-03-05", "collector"),
    ("horizon", "2026-04-02", "60", "minutes", "2026-04-02", "collector"),
    ("horizon", "2026-04", "58", "minutes", "2026-05-01", "collector"),
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
    # supersedes: a correction replaces the original once it is known (2026-08-15)
    {"id": "2026-05-01-pledge-coverage", "date": "2026-05-01", "published": "2026-05-02",
     "published_basis": "source", "retrieved": "2026-05-02", "kind": "analysis",
     "topics": ["milestone:the-balance"], "claim": "A tracker found net-zero pledges cover 90% of global emissions.",
     "sources": [{"url": "https://example.org/d", "title": "D", "primary": True}],
     "significance": 2, "verification": {"status": "verified", "by": "v", "at": "2026-05-02"},
     "collector": "gather:test"},
    {"id": "2026-06-01-pledge-followup", "date": "2026-06-01", "published": "2026-06-02",
     "published_basis": "source", "retrieved": "2026-06-02", "kind": "analysis",
     "topics": ["milestone:the-balance"], "claim": "A follow-up study examined how many of those pledges are legally binding.",
     "sources": [{"url": "https://example.org/e", "title": "E", "primary": True}],
     "relates": [{"id": "2026-05-01-pledge-coverage", "rel": "followup"}],
     "significance": 1, "verification": {"status": "verified", "by": "v", "at": "2026-06-02"},
     "collector": "gather:test"},
    {"id": "2026-05-01-pledge-coverage-corrected", "date": "2026-05-01", "published": "2026-08-15",
     "published_basis": "source", "retrieved": "2026-08-15", "kind": "analysis",
     "topics": ["milestone:the-balance"], "claim": "A tracker found net-zero pledges cover 88% of global emissions (corrected).",
     "sources": [{"url": "https://example.org/d2", "title": "D corrected", "primary": True}],
     "supersedes": ["2026-05-01-pledge-coverage"],
     "significance": 2, "verification": {"status": "corrected", "by": "v", "at": "2026-08-15"},
     "collector": "gather:test"},
]

ASSESSMENTS = [
    {"id": "climate-the-bend-2026-07-02", "target": "milestone:the-bend", "status": "green",
     "label": "Peak in sight", "made_at": "2026-07-02", "rationale": "Emissions fell \"><b onclick=alert(3)>.",
     "evidence": ["2026-07-01-peak-update"], "by": "assess-agent"},
    {"id": "climate-the-bend-2026-10-01", "target": "milestone:the-bend", "status": "red",
     "label": "Rebound", "made_at": "2026-10-01", "rationale": "Later judgment.",
     "evidence": [], "by": "assess-agent"},
    {"id": "climate-the-balance-2026-03-03", "target": "milestone:the-balance", "status": "red",
     "label": "Distant", "made_at": "2026-03-03", "rationale": "Pilot-era judgment.",
     "evidence": ["2026-03-01-first-peak-claim"], "by": "migration:pilot-2025/climate.md"},
]


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def make_fixture(root):
    write(root, "framework.yaml", FRAMEWORK)
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
            mock.patch.object(ledger, "ROOT", root), mock.patch.object(kpi, "ROOT", root), \
            mock.patch.object(ledger, "DATA", root):
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
        case("as-of filters events (late news excluded)", n("events") == 5)
        case("event_topics / sources / relates / supersedes flattened",
             (n("event_topics"), n("event_sources"), n("event_relates"), n("event_supersedes")) == (6, 6, 2, 1))
        case("superseded event kept for audit, not effective",
             q(db, "SELECT effective, superseded_by, supersedes FROM events WHERE id='2026-05-01-pledge-coverage'")
             == [(0, "2026-05-01-pledge-coverage-corrected", None)]
             and q(db, "SELECT supersedes FROM events WHERE id='2026-05-01-pledge-coverage-corrected'")
             == [('["2026-05-01-pledge-coverage"]',)])
        case("current_events == ledger.effective_events",
             sorted(r[0] for r in q(db, "SELECT id FROM current_events")) ==
             sorted(e["id"] for e in ledger.effective_events(ledger.events("climate"), D("2026-09-28"))))
        case("recent_events: effective only", "2026-05-01-pledge-coverage" not in
             {r[0] for r in q(db, "SELECT id FROM recent_events")} and n("recent_events") == 4)
        case("observations incl. revisions", n("observations") == 15)
        case("assessments as-of (later one excluded)", n("assessments") == 2)
        case("sections: all SECTIONS, framework-less ones included", n("sections") == len(ledger.SECTIONS))
        case("topics from framework.yaml", {r[0] for r in q(db, "SELECT topic FROM topics WHERE section='climate'")}
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
        # P1 precedence: tier (non-legacy > legacy) before known_at
        cur = dict(q(db, "SELECT verification, value_text FROM current_obs WHERE metric='co2-monthly' AND obs='2026-04'"))
        case("later-dated legacy row does not override verified (current_obs)", cur == {"verified": "427.80"})
        eff = q(db, "SELECT metric, obs, value_text FROM current_obs")
        case("current_obs == ledger.obs_as_of (one implementation)",
             sorted(eff) == sorted((m_, o_, r["value"]) for (m_, o_), r in table.items()))
        case("observations.tier/effective columns",
             q(db, "SELECT tier, effective FROM observations WHERE metric='co2-monthly' AND obs='2026-04' "
                   "ORDER BY tier") == [(0, 0), (1, 1)])
        # comparability safeguards (as ledger.snapshot)
        k = q(db, "SELECT change_text, change_label, comparable, caveat, year_ago_obs, year_ago_change_text "
                  "FROM latest_kpi WHERE metric='co2-monthly'")[0]
        case("monthly change vs previous obs: labelled, flagged seasonal, year-ago like-for-like",
             k == ("+1.15", "vs previous observation (2026-05)", 0,
                   "different calendar month: seasonal cycle not removed", "2025-06", "+3.25"))
        k = q(db, "SELECT obs, prev_obs, comparable, caveat FROM latest_kpi WHERE metric='horizon'")[0]
        case("granularity change flagged not comparable",
             k == ("2026-04", "2026-04-02", 0, "different observation granularity"))
        k = q(db, "SELECT comparable, caveat, year_ago_obs FROM latest_kpi WHERE metric='co2-trend'")[0]
        case("annual vs annual comparable, no year-ago row", k == (1, "", None))
        mk = lambda o, v: {"metric": "x", "obs": o, "value": v}
        c = explore.compare
        case("compare: same obs revised -> not comparable",
             (c(mk("2026-05", "1.5"), mk("2026-05", "1.4"))["comparable"],
              c(mk("2026-05", "1.5"), mk("2026-05", "1.4"))["caveat"]) == (False, "same observation revised by the source"))
        case("compare: same obs unchanged", c(mk("2026", "2"), mk("2026", "2.0"))["caveat"]
             == "same observation, unchanged: no new data")
        case("compare: same calendar month a year apart is comparable",
             c(mk("2026-05", "430"), mk("2025-05", "427.5")) ==
             {"value": "+2.5", "from_obs": "2025-05", "to_obs": "2026-05", "comparable": True, "caveat": ""})
        case("compare: daily vs daily comparable", c(mk("2026-05-02", "3"), mk("2026-05-01", "1"))["comparable"])
        # sparkline: one granularity only
        db.row_factory = sqlite3.Row
        row = lambda m_: db.execute("SELECT * FROM latest_kpi WHERE metric=?", (m_,)).fetchone()
        pts, kind = explore.spark_points(db, row("horizon"))
        case("sparkline falls back to the dominant granularity, never mixes",
             kind == "daily" and [str(d) for d, _ in pts] == ["2026-01-10", "2026-03-05", "2026-04-02"])
        pts, kind = explore.spark_points(db, row("co2-monthly"))
        case("sparkline uses the headline granularity",
             kind == "monthly" and len(pts) == 4 and (D("2026-04-30"), 427.8) in pts)
        db.row_factory = None
        ass = ledger.assessment_as_of("climate", when)
        case("milestone_status agrees with ledger.assessment_as_of",
             {t: a["id"] for t, a in ass.items()} ==
             dict(q(db, "SELECT target, assessment_id FROM milestone_status WHERE assessment_id IS NOT NULL")))
        ms = {r[0]: r[1] for r in q(db, "SELECT target, status FROM milestone_status WHERE section='climate'")}
        case("milestone_status latest + not yet assessed",
             ms.get("milestone:the-bend") == "green" and ms.get("challenge:permanent-removal") == "not yet assessed"
             and "beyond" not in ms)
        leg = dict(q(db, "SELECT target, legacy_evidence FROM milestone_status WHERE assessment_id IS NOT NULL"))
        case("milestone_status flags all-legacy evidence",
             leg == {"milestone:the-bend": 0, "milestone:the-balance": 1})
        case("recent_events newest known first",
             q(db, "SELECT id FROM recent_events")[0][0] == "2026-05-01-pledge-coverage-corrected")
        case("milestone_status n_events counts effective events only",
             q(db, "SELECT n_events FROM milestone_status WHERE target='milestone:the-balance'")[0][0] == 2)

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
        case("lifecycle threads via relates + supersedes",
             sorted((r[1], r[4], r[5]) for r in thread) == [
                 ("2026-03-01-first-peak-claim", None, "update"),
                 ("2026-05-01-pledge-coverage", "2026-05-01-pledge-coverage-corrected", "followup"),
                 ("2026-05-01-pledge-coverage", "2026-05-01-pledge-coverage-corrected", "supersedes")])
        by_ms = q(db, queries["events_by_milestone"]["sql"].replace(":topic", "'milestone:the-balance'"))
        case("events_by_milestone: effective only", len(by_ms) == 2 and not any("90%" in r[6] for r in by_ms))
        legacy = {(r[1], r[2]): r[3] for r in q(db, queries["legacy_vs_verified"]["sql"])}
        case("legacy vs verified counts (effective records)",
             legacy[("events", "legacy")] == 1 and legacy[("events", "verified")] == 2
             and legacy[("events", "corrected")] == 1
             and legacy[("observations", "legacy")] == 2)
        db.close()

        # earlier / later as-of: revision not yet known; later assessment + event visible
        db = sqlite3.connect(":memory:")
        explore.build_db(db, D("2026-07-10"))
        case("as-of before revision -> original value",
             q(db, "SELECT value_text FROM latest_kpi WHERE metric='co2-monthly'")[0][0] == "429.00")
        case("as-of before the correction is known -> original event effective",
             q(db, "SELECT id FROM current_events WHERE id LIKE '2026-05-01-pledge%'")
             == [("2026-05-01-pledge-coverage",)] and q(db, "SELECT COUNT(*) FROM event_supersedes")[0][0] == 0)
        db = sqlite3.connect(":memory:")
        explore.build_db(db, D("2026-10-10"))
        case("later as-of sees late event + newer assessment",
             q(db, "SELECT COUNT(*) FROM current_events")[0][0] == 5 and
             q(db, "SELECT status, prev_status FROM milestone_status WHERE target='milestone:the-bend'")[0]
             == ("red", "green"))

        page = explore.dashboard(D("2026-09-28"))
        case("dashboard escapes claims", "<script>alert(1)" not in page and "&lt;script&gt;alert(1)" in page)
        case("dashboard escapes source titles/urls", "Data &quot;B&quot; &amp; more" in page
             and 'href="https://example.org/b?x=1&amp;y=2"' in page)
        case("dashboard drops non-http links", "javascript:" not in page)
        case("dashboard links rel=noopener", 'rel="noopener noreferrer"' in page)
        case("dashboard self-contained (no script/link/src)",
             not any(s in page for s in ("<script", "<link", " src=", "@import")))
        case("dashboard gap markers", all(s in page for s in ("OVERDUE", "no data yet", "not yet assessed",
                                                             "no events in the ledger yet")))
        case("dashboard is self-explanatory: tagline, manifesto, intros, definitions, legend",
             all(s in page for s in ("Tracking humanity&#x27;s progress.", "<p>Science has a communication problem.</p>",
                                     "<p>Fixing the past.</p>", "<b>The Bend:</b> Global emissions peak &amp; decline.",
                                     "<b>KPI:</b> Atmospheric CO₂", "How to read this page", "<h3>Milestone Countdown</h3>",
                                     "<h3>Major Open Challenges</h3>", '<h2 class="gh">Supplemental</h2>')))
        case("dashboard: milestone line shows its status, detail shows rationale + evidence",
             re.search(r'<li class="topic"><details><summary><span class="dot s-green"[^>]*></span><b>The Bend:</b>'
                       r'[^<]*<span class="st">Peak in sight', page) is not None
             and "cited as evidence" in page and "Emissions fell &quot;&gt;&lt;b onclick" in page)
        ids = re.findall(r' id="([^"]+)"', page)
        case("dashboard: each event anchor once although events repeat under topics",
             len(ids) == len(set(ids)) and page.count("Updated data &lt;script&gt;") >= 2)
        case("dashboard legacy/verified badges", '<span class="badge b-legacy">legacy</span></div>'
             '<div>An agency' in page and '<span class="badge b-verified">verified</span>' in page)
        case("dashboard escapes attributes", "<b onclick" not in page and '" onmouseover="' not in page
             and "&quot;&gt;&lt;b onclick" in page)
        case("dashboard sparkline", "<svg" in page and "<polyline" in page)
        case("dashboard change vs previous: labelled + not-comparable flag",
             "+1.15 vs previous observation (2026-05): 428.10 " in page
             and "not comparable: different calendar month: seasonal cycle not removed" in page)
        case("dashboard year-ago change", "+3.25</span> vs same month a year earlier (2025-06: 426.00)" in page)
        case("dashboard comparable change has an arrow", "\u25bc -0.08</span> vs previous observation (2024): 2.64"
             in page)
        case("dashboard sparkline names its granularity", "<title>3 daily obs 2026-01-10..2026-04-02" in page)
        case("dashboard lifecycle link", 'href="#ev-climate-2026-03-01-first-peak-claim"' in page)
        case("dashboard as-of excludes late event", "late announcement" not in page)
        case("dashboard hides superseded event, shows the correction",
             "cover 90%" not in page and "cover 88%" in page and "1 superseded not shown" in page
             and "4 events (3 verified, 1 legacy" in page)
        case("dashboard: supersedes line + relates link redirected to the successor",
             "supersedes (corrects / adds sources to) 2026-05-01-pledge-coverage" in page
             and 'href="#ev-climate-2026-05-01-pledge-coverage-corrected">2026-05-01-pledge-coverage '
                 '(superseded by 2026-05-01-pledge-coverage-corrected)</a>' in page)
        case("dashboard shows required + gap tiles, folds the rest",
             page.index("co2-never") < page.index("more registered metric") < page.index("co2-nolag"))
        db = sqlite3.connect(":memory:")
        explore.build_db(db, D("2026-10-10"))
        db.row_factory = sqlite3.Row
        fsec, _ = ledger.fw_section("climate")
        sec = explore.section_html(db, db.execute("SELECT * FROM sections WHERE section='climate'").fetchone(), fsec, 1)
        case("events under their topics, beyond + latest folded",
             "Beyond the framework: 1 event(s)" in sec and "Latest events (the 1 most recently known of 5)" in sec
             and "previously green on 2026-07-02" in sec and "under no current topic" not in sec)
        other = dict(fsec, milestones=[m for m in fsec["milestones"] if m["slug"] != "the-balance"])
        sec = explore.section_html(db, db.execute("SELECT * FROM sections WHERE section='climate'").fetchone(), other, 1)
        case("events of a topic the framework no longer lists are not dropped",
             "Events under no current topic: 2" in sec and "cover 88%" in sec)
        case("cited evidence shown under the target even when tagged with another topic",
             re.search(r"<b>The Balance:</b>.*?Cited evidence \(1\).*?An agency projected", page, re.S) is not None)
        ev_sec = explore.evidence_and_events(
            db, "climate", "milestone:the-balance",
            {"assessment_id": "x", "evidence": '["2026-05-01-pledge-coverage", "nope"]'}, {}, {}, set())
        case("superseded / unknown evidence is flagged, not dropped",
             "since superseded by 2026-05-01-pledge-coverage-corrected" in ev_sec and "cover 90%" in ev_sec
             and "nope: not in the ledger as of this date" in ev_sec and "Other events (2)" in ev_sec)
        tomb = dict(db.execute("SELECT * FROM current_events LIMIT 1").fetchone())
        tomb["relates"] = '[{"id": "x", "rel": "update"}]'
        case("lifecycle link to a withdrawn record: no dangling anchor",
             "x (withdrawn)" in explore.event_li(tomb, {}, {"x": "t", "t": None}) and 'href="#ev-climate-"' not in page)
        case("markdown: inline emphasis, escaped, http links only",
             explore.md_inline("**b** *i* <x> [t](https://a.b/?q=1&r=2) [j](javascript:x)")
             == '<b>b</b> <i>i</i> &lt;x&gt; <a href="https://a.b/?q=1&amp;r=2" target="_blank" '
                'rel="noopener noreferrer">t</a> [j](javascript:x)'
             and explore.md_block("a\nb\n\n* x\n* y") == '<p>a b</p><ul class="md"><li>x</li><li>y</li></ul>')
        case("dashboard deterministic", page == explore.dashboard(D("2026-09-28")))

        with mock.patch.object(sys, "argv", ["explore.py", "dashboard", "--as-of", "2026-09-28",
                                             "--out", os.path.join(out, "d.html")]):
            rc = explore.main()
        case("CLI dashboard", rc == 0 and open(os.path.join(out, "d.html"), encoding="utf-8").read() == page)

        # --- period pages and the published site ------------------------------------------
        pdir = os.path.join(root, "pilot-26H1")
        write(root, "pilot-26H1/climate.md", "# Climate\n")
        write(root, "pilot-2026-W38/climate.md", "# Climate\n")   # a period without a page: not linked
        frozen = FRAMEWORK.replace("Global emissions peak &amp; decline.", "OLD bend wording.").replace(
            "Global emissions peak & decline.", "OLD bend wording.")
        write(root, "pilot-26H1/framework.yaml", frozen)
        p = explore.period_page(pdir, note="Reconstructed *later*.")
        pg = open(p, encoding="utf-8").read()
        case("period page: as of the cutoff, with the period's frozen framework",
             "cutoff <b>2026-07-14</b>" in pg and "OLD bend wording." in pg and "peak &amp; decline" not in pg
             and "Reconstructed <i>later</i>." in pg and 'href="../"' in pg and "ledger.sqlite" not in pg)
        case("period page: sections without a bulletin are marked",
             pg.count("Not covered by this period") == 1 and "late announcement" not in pg)
        try:
            explore.period_page(pdir)
            refused = False
        except ValueError:
            refused = True
        case("period page is frozen: no silent overwrite, --force replaces it",
             refused and open(p, encoding="utf-8").read() == pg
             and "Reconstructed" not in open(explore.period_page(pdir, force=True), encoding="utf-8").read())
        explore.period_page(pdir, note="Reconstructed *later*.", force=True)
        fresh = os.path.join(root, "pilot-2025")
        os.makedirs(fresh)
        explore.period_page(fresh)
        case("period page: first run freezes the current framework.yaml",
             open(os.path.join(fresh, "framework.yaml")).read() == FRAMEWORK)
        site_dir = os.path.join(root, "site")
        explore.site(site_dir, D("2026-09-28"))
        live = open(os.path.join(site_dir, "index.html"), encoding="utf-8").read()
        case("site: live page links the period pages (newest first), copies them",
             'Earlier periods: <a href="pilot-26H1/">pilot-26H1</a> · <a href="pilot-2025/">pilot-2025</a>' in live
             and open(os.path.join(site_dir, "pilot-26H1", "index.html"), encoding="utf-8").read() == pg
             and not os.path.exists(os.path.join(site_dir, "pilot-2026-W38")))
        case("site: ledger.sqlite + old dashboard.html redirects",
             os.path.exists(os.path.join(site_dir, "ledger.sqlite"))
             and 'url=./' in open(os.path.join(site_dir, "dashboard.html")).read())

    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall explorer tests passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
