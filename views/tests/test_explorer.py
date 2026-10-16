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


def q_page_db(as_of):
    """(id,) of the effective climate events as of a date."""
    db = sqlite3.connect(":memory:")
    explore.build_db(db, as_of)
    try:
        return q(db, "SELECT id FROM current_events WHERE section='climate'")
    finally:
        db.close()


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
        case("dashboard gap markers", all(s in page for s in ("update overdue since 7 Aug 2026", "no data yet", "not yet assessed",
                                                             "no events in the ledger yet")))
        case("dashboard is self-explanatory: tagline, manifesto, intros, definitions, legend",
             all(s in page for s in ("Tracking humanity&#x27;s progress.", "<p>Science has a communication problem.</p>",
                                     "<p>Fixing the past.</p>", "<b>The Bend:</b> Global emissions peak &amp; decline.",
                                     "<b>KPI:</b> Atmospheric CO₂", "How to read this page", "<h3>Milestone Countdown</h3>",
                                     "<h3>Major Open Challenges</h3>", '<div class="crumb">Supplemental</div>')))
        case("dashboard: milestone line shows its status, detail shows rationale + evidence",
             re.search(r'<li class="topic" id="t-climate-milestone-the-bend"><details><summary>'
                       r'<span class="dot s-green"[^>]*></span><b>The Bend:</b>'
                       r'[^<]*<span class="st">Peak in sight', page) is not None
             and "cited as evidence" in page and "Emissions fell &quot;&gt;&lt;b onclick" in page)
        pgs = explore.pages(D("2026-09-28"))
        log = pgs.get("events-climate.html", "")
        ids = re.findall(r' id="([^"]+)"', log)
        case("event log: every effective event once with its anchor; later topics link to it",
             sorted(i for i in ids if i.startswith("ev-")) == sorted(
                 f"ev-climate-{r[0]}" for r in q_page_db(D("2026-09-28")))
             and len(ids) == len(set(ids)) and log.count("Updated data &lt;script&gt;") >= 2
             and '<li class="ev ref">' in log and 'href="index.html#climate"' in log)
        case("front page: no event anchors (they live in the event log), events still under each topic",
             ' id="ev-' not in page and page.count("Updated data &lt;script&gt;") >= 2
             and pgs[explore.PAGE] == page and set(pgs) == {"index.html", "events-climate.html"})
        hrefs = re.findall(r'href="events-climate\.html#([^"]+)"', page + log) + re.findall(r'href="#([^"]+)"', log)
        case("every event-log link (front page and log) lands on an anchor in the log",
             hrefs and all(f' id="{h}"' in log for h in hrefs))
        with mock.patch.object(explore, "TOPIC_EVENTS", 0):
            capped = explore.dashboard(D("2026-09-28"))
        more = re.findall(r'<li class="ev more-ev"><a href="events-climate\.html#([^"]+)">\+(\d+) older', capped)
        case("front page caps each topic's other events, linking the rest in the event log",
             more and all(f' id="{h}"' in log for h, _ in more) and capped.count("Updated data &lt;script&gt;") < page.count("Updated data &lt;script&gt;")
             and "cited as evidence" in capped)
        case("dashboard legacy/verified badges", '<span class="badge b-legacy">legacy</span></div>'
             '<div>An agency' in page and '<span class="badge b-verified">verified</span>' in page)
        case("dashboard escapes attributes", "<b onclick" not in page and '" onmouseover="' not in page
             and "&quot;&gt;&lt;b onclick" in page)
        case("dashboard sparkline", "<svg" in page and "<polyline" in page)
        case("dashboard tiles: no change vs the previous observation (the series shows it)",
             "vs previous observation" not in page and "not comparable" not in page)
        case("dashboard tiles: monthly like-for-like change vs a year earlier, human periods",
             '<div class="c" title="Jun 2025: 426.00"><span class="up">\u25b2 +3.25</span> vs Jun 2025</div>' in page
             and '<span title="published 2026-07-20">Jun 2026</span>' in page and ">obs " not in page
             and "known 2026" not in page and "required</span>" not in page)
        case("dashboard tiles: metric label (id + definition as tooltip), else the definition's first clause",
             explore.metric_label("climate", "co2-mlo-monthly") == "CO\u2082 at Mauna Loa, monthly mean (NOAA)"
             and '<div class="m" title="co2-monthly: Monthly mean CO2 at a fixture station for tests">'
                 'Monthly mean CO2 at a fixture station for tests</div>' in page
             and explore.metric_label("x", "m", "Mean of NOAA rates (Jan 1 -> Dec 31); obs = final year")
             == "Mean of NOAA rates" and explore.metric_label("x", "m2") == "m2")
        case("dashboard sparkline names its granularity, labels its time axis",
             "<title>3 daily values, 2026-01-10 to 2026-04-02" in page
             and re.search(r'class="ax">Jan 26</text><text [^>]*class="ax" text-anchor="end">Apr 26</text>', page)
             is not None)
        case("dashboard lifecycle link", 'href="events-climate.html#ev-climate-2026-03-01-first-peak-claim"' in page)
        case("dashboard as-of excludes late event", "late announcement" not in page)
        case("dashboard hides superseded event, shows the correction",
             page.count("cover 90%") == page.count('<s class="mute">2026-05-01: A tracker found net-zero pledges cover 90%') and "cover 88%" in page and "1 superseded not shown" in page
             and "4 events (3 verified, 1 legacy" in page)
        case("dashboard: supersedes line + relates link redirected to the successor",
             'corrects (or adds sources to) an earlier record: <s class="mute">2026-05-01: A tracker found net-zero '
             'pledges cover 90%' in page
             and 'href="events-climate.html#ev-climate-2026-05-01-pledge-coverage-corrected" title="2026-05-01-pledge-coverage-corrected">'
                 '2026-05-01: A tracker found net-zero pledges cover 88% of global emissions (corrected).</a> '
                 '<span class="mute">(corrected version)</span>' in page
             and "\u21b3 follows up on <a" in page and "\u21b3 updates <a" in page)
        case("dashboard shows required + gap tiles, folds the rest",
             page.index("co2-never") < page.index("more metric(s) we track") < page.index("co2-nolag"))
        db = sqlite3.connect(":memory:")
        explore.build_db(db, D("2026-10-10"))
        db.row_factory = sqlite3.Row
        fsec, _ = ledger.fw_section("climate")
        sec = explore.section_html(db, db.execute("SELECT * FROM sections WHERE section='climate'").fetchone(), fsec, 1)
        case("events under their topics, beyond + latest folded",
             "Beyond the framework: 1 event(s)" in sec and "Latest news: the 1 most recently published of 5 events" in sec
             and re.search(r"Previously <span class=\"dot s-green\"[^>]*></span>green \(assessed 2026-07-02\)", sec) and "under no current topic" not in sec)
        other = dict(fsec, milestones=[m for m in fsec["milestones"] if m["slug"] != "the-balance"])
        sec = explore.section_html(db, db.execute("SELECT * FROM sections WHERE section='climate'").fetchone(), other, 1)
        case("events of a topic the framework no longer lists are not dropped",
             "Events under no current topic: 2" in sec and "cover 88%" in sec)
        case("cited evidence shown under the target even when tagged with another topic",
             re.search(r"<b>The Balance:</b>.*?Cited evidence \(1\).*?An agency projected", page, re.S) is not None)
        ev_sec = explore.evidence_and_events(
            db, "climate", "milestone:the-balance",
            {"assessment_id": "x", "evidence": '["2026-05-01-pledge-coverage", "nope"]'}, {},
            {"2026-05-01-pledge-coverage": "2026-05-01-pledge-coverage-corrected"}, set())
        case("superseded / unknown evidence is flagged, not dropped",
             "since corrected</span>" in ev_sec and "\u21b3 since corrected: <a href=\"events-climate.html#ev-climate-2026-05-01-pledge-coverage-corrected\"" in ev_sec and "cover 90%" in ev_sec
             and "nope: not in the ledger as of this date" in ev_sec and "Other events (2)" in ev_sec)
        am = {"assessment_id": "x", "status": "yellow", "label": "Progressing: x, ETA ~2034", "made_at": "2026-10-06",
              "prev_status": None, "prev_made_at": None, "legacy_evidence": 0, "rationale": "r", "by": "t",
              "evidence": "[]", "basis": json.dumps({"rule": "§4", "path": "p", "eta": {
                  "p10": 2031, "p50": 2034, "p90": None, "method": "trend", "calc": "log(31)/log(1.45)", "cruxes": "c"}})}
        ah = explore.assessment_html(am)
        case("rubric v2 ETA: median + 80% range and its cruxes with the outlook (before Path); its "
             "method/calculation folded with how it was assessed",
             "<dt>ETA</dt><dd>~2034 (80% range 2031–never/after 2100)</dd><dt>ETA cruxes</dt><dd>c</dd>"
             "<dt>Path</dt><dd>p</dd>" in ah
             and ah.index('<details class="tech">') < ah.index("<dt>ETA method</dt><dd>trend</dd>")
             < ah.index("<dt>ETA calculation</dt><dd>log(31)/log(1.45)</dd>"))
        am4 = dict(am, basis=json.dumps({"eta": {"p_achieved": 0.2, "p10": 2078, "p50": None, "p90": None,
                                                  "method": "m", "calc": "c", "cruxes": "x"}}))
        case("rubric v4 ETA without a median: the chance, not a fake year",
             "<dt>ETA</dt><dd>unlikely by 2100 (P 20%; 10% chance by 2078)</dd>" in explore.assessment_html(am4)
             and "P(by 2100) 95%" in explore.assessment_html(dict(am, basis=json.dumps({"eta": {
                 "p_achieved": 0.95, "p10": 2031, "p50": 2034, "p90": 2040, "method": "m", "calc": "c", "cruxes": "x"}}))))
        tomb = dict(db.execute("SELECT * FROM current_events LIMIT 1").fetchone())
        tomb["relates"] = '[{"id": "x", "rel": "update"}]'
        case("lifecycle link to a withdrawn record: no dangling anchor",
             'x <span class="mute">(since withdrawn)</span>' in explore.event_li(tomb, {}, {"x": "t", "t": None}) and '#ev-climate-"' not in page)
        case("markdown: inline emphasis, escaped, http links only",
             explore.md_inline("**b** *i* <x> [t](https://a.b/?q=1&r=2) [j](javascript:x)")
             == '<b>b</b> <i>i</i> &lt;x&gt; <a href="https://a.b/?q=1&amp;r=2" target="_blank" '
                'rel="noopener noreferrer">t</a> [j](javascript:x)'
             and explore.md_block("a\nb\n\n* x\n* y") == '<p>a b</p><ul class="md"><li>x</li><li>y</li></ul>')

        # --- layout: sidebar navigation, one pane per endeavor, news stream ---------------
        nav = page[page.index('<nav class="side">'):page.index("</nav>")]
        case("layout: pane per section + the intro pane, switched by pure CSS (:target)",
             '<div class="pane" id="intro">' in page and '<section class="pane" id="climate">' in page
             and '<section class="pane" id="knowledge-beyond">' in page and ".pane:target" in page
             and 'body:has(#climate:target,#climate :target) .nv[href="#climate"]' in page)
        case("layout: nav item = KPI dot + headline value, then a dot per milestone",
             re.search(r'<a class="nv" href="#climate">.*?<span class="nk"><span class="dot s-none"[^>]*></span>'
                       r'<span class="hv"[^>]*><b>429.25</b> ppm</span><svg.*?<span class="nd" title="milestones">'
                       r'<span class="dot s-green" title="The Bend: Peak in sight"></span>'
                       r'<span class="dot s-red" title="The Balance: Distant"></span></span></a>', nav) is not None
             and 'href="#knowledge-beyond"' in nav and "#intro" in nav
             and '<span class="rc r-cold" title="latest news published 2026-08-15 (6 weeks ago)">6w ago</span>' in nav
             and nav.index('href="#climate"') < nav.index('<div class="ng">Supplemental</div>')
             < nav.index('href="#knowledge-beyond"'))
        # a supplemental section (no KPI, milestones or challenges): its indicators and major events instead
        kb = {"metrics/knowledge-beyond.csv": "metric,unit,cadence,release_lag_days,required_from,retired_after,"
              "definition\nqubits,qubits,annual,,,,Largest logical qubit count\nempty,x,annual,,,,Never observed\n",
              "ledger/observations/knowledge-beyond.csv": ",".join(ledger.OBS_COLUMNS) + "\n" + "".join(
                  f"qubits,{y},{v},qubits,https://example.org/q,{y}-12-31,source,{y}-12-31,test:fixture,verified,\n"
                  for y, v in ((2024, 12), (2025, 48))),
              "ledger/events/knowledge-beyond.jsonl": "".join(json.dumps(
                  {"id": f"2026-0{i}-01-kb", "date": f"2026-0{i}-01", "published": f"2026-0{i}-01",
                   "published_basis": "source", "retrieved": f"2026-0{i}-01", "kind": "achievement",
                   "topics": ["beyond"], "claim": f"KB claim {i}.", "significance": sig,
                   "sources": [{"url": "https://example.org/k", "title": "K", "primary": True}],
                   "verification": {"status": "verified"}, "collector": "test"}) + "\n"
                  for i, sig in ((1, 3), (2, 2), (3, 3)))}
        for rel, text in kb.items():
            write(root, rel, text)
        sp = explore.dashboard(D("2026-09-28"))
        for rel in kb:
            os.remove(os.path.join(root, rel))
        kpane = sp[sp.index('<section class="pane" id="knowledge-beyond">'):]
        kpane = kpane[:kpane.index("</section>")]
        knav = re.search(r'<a class="nv" href="#knowledge-beyond">.*?</a>', sp)[0]
        kcard = re.search(r'<a class="card" href="#knowledge-beyond">.*?</a>', sp)[0]
        case("supplemental: pane shows indicator tiles and the major events, newest first",
             "<h3>Indicators we track</h3>" in kpane and kpane.count('<div class="tile ') + kpane.count('<div class="tile"') == 2
             and "Notable developments" in kpane and "The 2 latest of 2 major" in kpane
             and kpane.index("KB claim 3.") < kpane.index("KB claim 1.") < kpane.index("<summary>Beyond the framework"))
        case("supplemental: nav = title + news freshness only, card = indicators + major events",
             'class="nk"' not in knav and 'class="dot' not in knav and 'class="rc ' in knav
             and "Indicators we track:" in kcard and "<b>48</b> qubits" in kcard and "Never observed" not in kcard
             and kcard.index("KB claim 3.") < kcard.index("KB claim 1.") and "KB claim 2." not in kcard)
        gdir = os.path.join(root, "grouped")
        write(gdir, "framework.yaml", FRAMEWORK.replace("endeavors:\n", "endeavors:\n"
              "  - title: Robots and Automation\n    intro: Automating labor.\n    sections:\n"
              "      - {id: robots-software, title: Software, kpi: Task horizon}\n"
              "      - {id: robots-hardware, title: Hardware, kpi: Fleet size}\n", 1))
        gp = explore.dashboard(D("2026-09-28"), fw=ledger.framework(gdir))
        gpane = gp[gp.index('<div class="pane" id="robots-and-automation">'):gp.index('<section class="pane" id="climate">')]
        case("layout: a multi-section endeavor is ONE pane, nav item, card (its sections as tracks)",
             "<p>Automating labor.</p>" in gpane and gpane.count('<section class="track" id="robots-') == 2
             and '<div class="nvg"><a class="nv" href="#robots-and-automation">' in gp
             and '<a class="nv sub" href="#robots-software">' in gp and '<a class="card wide" href="#robots-and-automation">' in gp
             and 'body:has(#robots-software:target,#robots-software :target) .nv[href="#robots-software"]' in gp
             and 'class="si chg x-robots' not in gp and gp.count('<a class="card') == 3
             and "body:has(.pane:not(#intro):target,.pane:not(#intro) :target) .here{display:inline}" in gp)
        nocl = explore.dashboard(D("2026-09-28"), fw=ledger.framework(gdir) | {"endeavors": [
            e for e in ledger.framework(gdir)["endeavors"] if e.get("id") != "climate"]})
        case("gaps: by section title + metric name (definition fallback); unlinked without a pane",
             "<li>climate: <span title=\"co2-never\">A required metric that was never observed at all"
             "</span> (a KPI metric)" in nocl and 'href="#climate"' not in nocl
             and '<li><a href="#climate">Climate and Environment</a>: ' in page)
        case("layout: overview card per section, linking to its pane",
             page.count('<a class="card" href="#') == 2  # the fixture framework's 2 sections
             and '<a class="card" href="#climate">' in page)
        stream = page[page.index('<aside class="stream">'):page.index("</aside>")]
        hrefs = re.findall(r'href="([^"]+)"', stream)
        log = "events-climate.html#"
        case("stream: events newest-known first, status changes first within their day",
             hrefs == [log + "ev-climate-2026-05-01-pledge-coverage-corrected", "#t-climate-milestone-the-bend",
                       log + "ev-climate-2026-07-01-peak-update", log + "ev-climate-2026-06-01-pledge-followup",
                       "#t-climate-milestone-the-balance", log + "ev-climate-2026-03-01-first-peak-claim"])
        logpage = explore.pages(D("2026-09-28"))["events-climate.html"]
        case("event log: lifecycle lines show the linked claim; own one-column layout",
             "\u21b3 updates <a href=\"events-climate.html#ev-climate-2026-03-01-first-peak-claim\"" in logpage
             and "An agency projected" in logpage and '<body class="log">' in logpage)
        case("stream: event links land in the event log, status changes on the page; superseded/late left out",
             all(f' id="{h.split("#")[1]}"' in (logpage if h.startswith("events-") else page) for h in hrefs)
             and "cover 90%" not in stream
             and "late announcement" not in stream and "first assessed" in stream)
        db.execute("INSERT INTO assessments (section, target, status, label, made_at, line) VALUES "
                   "('climate', 'milestone:the-balance', 'yellow', 'x', '2026-09-01', 10), "
                   "('climate', 'milestone:the-balance', 'red', 'y', '2026-09-01', 11), "
                   "('climate', 'milestone:the-balance', 'yellow', 'z', '2026-09-02', 12)")
        ch = [(c["day"], c["prev"], c["status"]) for c in explore.status_changes(db, "2026-01-01")
              if c["target"] == "milestone:the-balance"]
        case("status changes: first assessment, same-day flips collapse, since cutoff",
             ch == [("2026-03-03", None, "red"), ("2026-09-02", "red", "yellow")]
             and [c["day"] for c in explore.status_changes(db, "2026-09-02")
                  if c["target"] == "milestone:the-balance"] == ["2026-09-02"])
        only_kb = explore.stream_html(db, D("2026-10-10"), {"knowledge-beyond": ("knowledge-beyond", "K")}, set())
        case("stream: only sections with a pane (a frozen framework may lack some)",
             "no events yet" in only_kb and "climate" not in only_kb)
        db.execute("DELETE FROM events")
        no_ev = explore.stream_html(db, D("2026-10-10"), {"climate": ("climate", "C")}, set())
        case("stream: status changes shown without any events, all-history footer",
             no_ev.count("· status change</span>") == 4 and "All 0 events and all status changes" in no_ev
             and 'href="#climate"' in no_ev)
        case("values in readable units: minutes from 2 hours on as hours",
             explore.human_value("1044.78", "min") == ("17.4", "hours")
             and explore.human_value("185.91", "min") == ("3.1", "hours")
             and explore.human_value("90", "min") == ("90", "min") and explore.human_value("89", "s") == ("89", "s"))
        bend = re.search(r'<li class="topic" id="t-climate-milestone-the-bend">.*?</li>', page, re.S)[0]
        case("an expanded status does not repeat its status line", bend.count("Peak in sight") == 1)
        ah = explore.assessment_html({"assessment_id": "a", "status": "yellow", "prev_status": None, "legacy_evidence": 0,
                                      "rationale": "R.", "by": "b", "evidence": "[]",
                                      "basis": json.dumps({"eta": "5-10 years", "window": {"n_points": 9}})})
        case("assessment basis: the outlook shown, how it was assessed folded",
             ah.index("5-10 years") < ah.index('<details class="tech">') < ah.index("n points: 9"))
        bars = explore.activity_bars([0, 2, 1], D("2026-09-28"))
        case("activity bars: one per week, empty weeks marked",
             bars.count("<rect") == 3 and bars.count('class="z"') == 1 and "2026-09-28: 0, 2, 1" in bars)

        # the cap at a positive limit: newest first, exact omitted count; cited evidence exempt
        db = sqlite3.connect(":memory:")
        explore.build_db(db, D("2026-09-28"))
        db.row_factory = sqlite3.Row
        topic, tevs = next((t, e) for t in ("kpi", "milestone:the-bend", "milestone:the-balance")
                           if len(e := explore.topic_events(db, "climate", t)) >= 2)
        with mock.patch.object(explore, "TOPIC_EVENTS", 1):
            one = explore.evidence_and_events(db, "climate", topic, None, {}, {}, set())
            allcited = explore.evidence_and_events(
                db, "climate", topic, {"assessment_id": "x", "evidence": json.dumps([e["id"] for e in tevs])},
                {}, {}, set())
        claim = lambda e: explore.esc(e["claim"])
        case("cap 1: the newest event shown, the rest counted and linked",
             claim(tevs[0]) in one and claim(tevs[1]) not in one
             and f'#{explore.topic_anchor(topic)}">+{len(tevs) - 1} older event(s)' in one)
        case("cap does not apply to cited evidence",
             all(claim(e) in allcited for e in tevs) and "older event(s)" not in allcited)
        db.close()

        write(out, "events-personal.html", "not ours")
        with mock.patch.object(sys, "argv", ["explore.py", "dashboard", "--as-of", "2026-09-28",
                                             "--out", os.path.join(out, "d.html")]):
            rc = explore.main()
        case("CLI dashboard", rc == 0 and open(os.path.join(out, "d.html"), encoding="utf-8").read() == page)
        case("CLI dashboard: event logs link back to the named page; unrelated files kept",
             'href="d.html#climate"' in open(os.path.join(out, "events-climate.html"), encoding="utf-8").read()
             and os.path.exists(os.path.join(out, "events-personal.html")))

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
        plog = open(os.path.join(pdir, "events-climate.html"), encoding="utf-8").read()
        case("period page: its event log is frozen next to it, as of the cutoff",
             "pilot-26H1" in plog and "2026-07-14" in plog and "late announcement" not in plog)
        write(root, "pilot-26H1/events-gone.html", "stale")
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
        site_dir = os.path.join(out, "site")   # not in the data dir (it would look like a period dir)
        explore.site(site_dir, D("2026-09-28"))
        live = open(os.path.join(site_dir, "index.html"), encoding="utf-8").read()
        case("site: live page links the period pages (newest first), copies them",
             'Earlier periods: <a href="pilot-26H1/">pilot-26H1</a> · <a href="pilot-2025/">pilot-2025</a>' in live
             and open(os.path.join(site_dir, "pilot-26H1", "index.html"), encoding="utf-8").read() == pg
             and os.path.exists(os.path.join(site_dir, "pilot-26H1", "events-climate.html"))
             and not os.path.exists(os.path.join(site_dir, "pilot-26H1", "events-gone.html"))
             and os.path.exists(os.path.join(site_dir, "events-climate.html"))
             and not os.path.exists(os.path.join(site_dir, "pilot-2026-W38")))
        anchors, links = {}, []
        for dp, _, fs in os.walk(site_dir):
            for f in fs:
                if f.endswith(".html"):
                    h = open(os.path.join(dp, f), encoding="utf-8").read()
                    anchors[os.path.join(dp, f)] = set(re.findall(r' id="([^"]+)"', h))
                    links += [(os.path.join(dp, f), t) for t in re.findall(r'href="([^":]*#[^"]*)"', h)]
        def target(f, href):  # (page path, anchor) of a relative link
            page, frag = href.split("#", 1)
            p = os.path.normpath(os.path.join(os.path.dirname(f), page)) if page else f
            return (p if p.endswith(".html") else os.path.join(p, "index.html")), frag
        dangling = [(f, t) for f, t in links if target(f, t)[1] not in anchors.get(target(f, t)[0], set())]
        case("site: every internal #anchor link resolves (front pages, event logs, period pages)",
             links and not dangling)
        os.remove(os.path.join(pdir, "events-climate.html"))   # e.g. regenerated with no climate events
        explore.site(site_dir, D("2026-09-28"))
        case("site: published period dir mirrors the data repo (stale event log dropped)",
             not os.path.exists(os.path.join(site_dir, "pilot-26H1", "events-climate.html"))
             and os.path.exists(os.path.join(site_dir, "pilot-26H1", "index.html")))
        case("site: ledger.sqlite + old dashboard.html redirects",
             os.path.exists(os.path.join(site_dir, "ledger.sqlite"))
             and 'url=./' in open(os.path.join(site_dir, "dashboard.html")).read())

    print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall explorer tests passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
