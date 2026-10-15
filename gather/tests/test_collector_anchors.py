#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Offline tests of the external-anchor collector (gather/collectors/anchors.py).

Run:  uv run gather/tests/test_collector_anchors.py   (no network; Manifold/Metaculus responses are
                                                       small fixtures written here; the Metaculus
                                                       schema follows its open-source serializers)
"""
import datetime as dt
import json
import os
import sys
import tempfile

GATHER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(GATHER, "collectors"))

import anchors  # noqa: E402
import common  # noqa: E402
import kpi  # noqa: E402
import ledger  # noqa: E402
import yaml  # noqa: E402

FAILS = []
TODAY = dt.date(2026, 10, 15)


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def raises(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return True
    return False


def epoch(d):
    return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp()


with tempfile.TemporaryDirectory() as root:
    ledger.ROOT = kpi.ROOT = ledger.DATA = root
    fw = yaml.safe_load(open(os.path.join(GATHER, "..", "framework.yaml"), encoding="utf-8"))
    sec = next(s for s, _ in ledger.fw_sections(fw) if s["id"] == "fusion")
    first = next(m for m in sec["milestones"] if m["slug"] == "the-first-watt")
    first["anchors"] = [{"source": "manifold", "id": "AbC1", "relation": "weaker", "by": "2035-12-31"},
                        {"source": "metaculus", "id": "77", "relation": "same"},
                        {"source": "metaculus", "id": "78", "relation": "weaker", "by": "2029-12-31"}]
    yaml.safe_dump(fw, open(f"{root}/framework.yaml", "w"), sort_keys=False, allow_unicode=True)
    os.makedirs(f"{root}/metrics")
    with open(f"{root}/metrics/fusion.csv", "w") as f:
        f.write(",".join(kpi.REG_COLUMNS) + "\n")
        for m, unit in (("manifold-abc1-p", "probability"), ("metaculus-77-p10", "year"), ("metaculus-77-p50", "year"),
                        ("metaculus-77-p90", "year"), ("metaculus-78-p", "probability")):
            f.write(f"{m},{unit},weekly,,,,anchor test metric with a long enough definition\n")
    fix = os.path.join(root, "fix")
    os.makedirs(fix)
    json.dump({"id": "AbC1", "outcomeType": "BINARY", "question": "Fusion by 2035?", "probability": 0.367803,
               "uniqueBettorCount": 11, "isResolved": False}, open(f"{fix}/AbC1", "w"))
    lo, hi = dt.date(2025, 1, 1), dt.date(2045, 1, 1)
    cdf = [min(1.0, i / 200 * 1.25) for i in range(201)]  # linear, reaching 1 at 80% of the range
    json.dump({"title": "When fusion?", "question": {"type": "date", "status": "open",
               "scaling": {"range_min": epoch(lo), "range_max": epoch(hi), "zero_point": None},
               "aggregations": {"recency_weighted": {"latest": {"forecast_values": cdf, "forecaster_count": 40}}}}},
              open(f"{fix}/77", "w"))
    json.dump({"title": "Fusion by 2030?", "question": {"type": "binary", "status": "open",
               "aggregations": {"recency_weighted": {"latest": {"centers": [0.2], "forecaster_count": 9}}}}},
              open(f"{fix}/78", "w"))

    rows = anchors.collect(fix, TODAY, "collectors/anchors.py@2026-10-15", [], "fusion")
    by = {r["metric"]: r for r in rows}
    m = by.get("manifold-abc1-p", {})
    case("manifold: probability rounded, obs = published = retrieved = today (seen), forecasters in the note",
         m.get("value") == "0.3678" and m.get("obs") == m.get("published") == m.get("retrieved") == "2026-10-15"
         and m.get("published_basis") == "seen" and "forecasters=11" in m.get("note", "")
         and "event by 2035-12-31" in m.get("note", ""))
    span = anchors.anchoring.decimal_year(hi) - anchors.anchoring.decimal_year(lo)
    want = {q: anchors.anchoring.decimal_year(lo) + span * x for q, x in (("p10", 0.08), ("p50", 0.4), ("p90", 0.72))}
    case("metaculus date: p10/p50/p90 from the CDF, as decimal years",
         all(abs(float(by[f"metaculus-77-{q}"]["value"]) - v) < 0.02 for q, v in want.items()))
    case("metaculus binary: P(yes) from the aggregate centers", by.get("metaculus-78-p", {}).get("value") == "0.2000")
    case("all staged rows pass the ledger's row checks", common.check(rows, common.registry("fusion")) == [])
    again = anchors.collect(fix, TODAY + dt.timedelta(days=6), "x", rows, "fusion")
    later = anchors.collect(fix, TODAY + dt.timedelta(days=7), "x", rows, "fusion")
    case("weekly: an anchor observed in the last 7 days is skipped", again == [] and len(later) == len(rows))
    saved = os.environ.pop("METACULUS_TOKEN", None)
    live = anchors.collect(None, TODAY, "x", [dict(r, metric="manifold-abc1-p") for r in rows[:1]], "fusion")
    if saved is not None:
        os.environ["METACULUS_TOKEN"] = saved
    case("metaculus without METACULUS_TOKEN is skipped (no network call, no row)", live == [])
    cut = [min(1.0, i / 200 * 0.85) for i in range(201)]  # 15% of the mass beyond the open upper bound
    json.dump({"title": "t", "question": {"type": "date", "status": "open",
               "scaling": {"range_min": epoch(lo), "range_max": epoch(hi), "zero_point": None},
               "aggregations": {"recency_weighted": {"latest": {"forecast_values": cut, "forecaster_count": 3}}}}},
              open(f"{fix}/77", "w"))
    vals, _, title, _ = anchors.metaculus({"source": "metaculus", "id": "77", "relation": "same"}, fix, None)
    case("metaculus date: a quantile beyond the range has no value and the note says so",
         set(vals) == {"p10", "p50"} and "p90 outside the question range" in title)
    case("metaculus: log scaling (zero_point) maps the CDF location geometrically",
         abs(anchors.unscale(0.5, 1.0, 100.0, 0.0) - 10.0) < 1e-9 and anchors.unscale(0.5, 1.0, 100.0, None) == 50.5)
    json.dump({"id": "X", "outcomeType": "MULTIPLE_CHOICE"}, open(f"{fix}/AbC1", "w"))
    case("manifold: a non-binary market is an error, not a silent row",
         raises(anchors.manifold, {"source": "manifold", "id": "AbC1"}, fix))

print(f"\n{len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
