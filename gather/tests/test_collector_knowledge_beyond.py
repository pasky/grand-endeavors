#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Offline tests for gather/collectors/knowledge_beyond.py (World Bank/ITU internet use, the
Erdős problems database, TOP500, NASA Exoplanet Archive), on trimmed real fixtures in
gather/tests/fixtures/knowledge-beyond/. Reads the data repo's metric registry.

Run:  uv run gather/tests/test_collector_knowledge_beyond.py
"""
import datetime as dt
import os
import sys

GATHER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(GATHER, "tests", "fixtures", "knowledge-beyond")
sys.path.insert(0, os.path.join(GATHER, "collectors"))

import common  # noqa: E402
import knowledge_beyond as kb  # noqa: E402

FAILS = []
TODAY = dt.date(2026, 10, 16)
kb.MIN_PLANETS = 10  # the exoplanet fixture is trimmed to 40 planets


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def raises(exc, fn, *a):
    try:
        fn(*a)
    except exc:
        return True
    return False


def read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


HAVE = [{"metric": kb.M_TOP500, "obs": "2025-11", "verification": "collector"}]  # TOP500: fetch from Nov 2025 on
rows = kb.collect(FIX, TODAY, "t", HAVE)
by = {(r["metric"], r["obs"]): r for r in rows}
errs = common.check(rows, common.registry(kb.SECTION))
case("all rows pass the registry/ledger row checks", not errs and bool(rows))
for e in errs[:5]:
    print("     ", e)

# --- World Bank / ITU
case("internet: non-null World years, values verbatim (no float noise; '67' stays '67')",
     [(o, r["value"]) for (m, o), r in sorted(by.items()) if m == kb.M_INTERNET]
     == [("2005", "15.6"), ("2022", "67"), ("2024", "71.2"), ("2025", "73.6")])
case("internet: rule-basis date = year end + lag, capped at retrieval",
     by[(kb.M_INTERNET, "2024")]["published"] == "2025-10-27" and by[(kb.M_INTERNET, "2025")]["published"] == str(TODAY))
case("internet: a paged answer is refused",
     raises(ValueError, kb.parse_wb, read("wb_internet_users.json").replace('"pages": 1', '"pages": 2')))

# --- Erdős problems
snaps = kb.parse_erdos(read("statistics_history.csv"))
case("erdos: snapshot dates are converted to UTC (21:19 PDT on Aug 31 = Sept 1 UTC)",
     snaps[2]["at"] == dt.datetime(2025, 9, 1, 4, 19, 42, tzinfo=dt.timezone.utc))
case("erdos: complete months only, from 2025-09 (2026-10 is still running)",
     sorted(o for m, o in by if m == kb.M_ERDOS)[0] == "2025-09" and (kb.M_ERDOS, "2026-10") not in by)
case("erdos: a month's value = the last snapshot by its end (UTC): Sept 2025 = 379/1062, not Oct 1's row",
     by[(kb.M_ERDOS, "2025-09")]["value"] == "35.7" and "6da7146ee659" in by[(kb.M_ERDOS, "2025-09")]["note"])
case("erdos: a month without snapshots carries the previous one (Aug 2026 = Sept 2025's 379/1062)",
     by[(kb.M_ERDOS, "2026-08")]["value"] == "35.7")
case("erdos: 579 of 1221 solved = 47.4 % (Sept 2026)", by[(kb.M_ERDOS, "2026-09")]["value"] == "47.4")
case("erdos: out-of-order snapshot dates are refused",
     raises(ValueError, kb.parse_erdos, "\n".join(read("statistics_history.csv").splitlines()[::-1][-1:]
                                                  + read("statistics_history.csv").splitlines()[:0:-1])))

# --- TOP500
v, name = kb.parse_top500(read("top500-1993-06.html"), "u")
case("top500: GFlop/s header converted exactly (59.70 GFlop/s = 0.0000597 PFlop/s), system named",
     format(v.normalize(), "f") == "0.0000597" and name == "CM-5/1024")
case("top500: lists to fetch = from the latest in the ledger to the newest due",
     kb.top500_lists(dt.date(2026, 12, 1), [{"metric": kb.M_TOP500, "obs": "2025-11", "verification": "collector"}])
     == [(2025, 11), (2026, 6), (2026, 11)] and kb.top500_lists(dt.date(1993, 12, 1), []) == [(1993, 6), (1993, 11)])
t5 = {r["obs"]: r for r in kb.collect(FIX, dt.date(2026, 12, 1), "t", HAVE) if r["metric"] == kb.M_TOP500}
case("top500: the newest list may be missing (Nov 2026 not out); PFlop/s values verbatim",
     sorted(t5) == ["2025-11", "2026-06"] and t5["2026-06"]["value"] == "2198.4" and t5["2025-11"]["value"] == "1809")
case("top500: a missing older list fails the run",
     raises(kb.NotFound, kb.collect, FIX, dt.date(2026, 12, 1), "t",
            [{"metric": kb.M_TOP500, "obs": "2024-11", "verification": "collector"}]))

# --- exoplanets
case("exoplanets: cumulative by discovery year, complete years past the lag only",
     by[(kb.M_EXO, "2009")]["value"] == "23" and by[(kb.M_EXO, "2014")]["value"] == "40"
     and (kb.M_EXO, "2026") not in by and kb.collect(FIX, dt.date(2026, 1, 29), "t", HAVE)[-1]["obs"] == "2024")
case("exoplanets: a truncated answer is refused",
     raises(ValueError, kb.parse_exo, "\n".join(read("exoplanets_pscomppars.csv").splitlines()[:5])))

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall knowledge-beyond collector tests passed")
sys.exit(1 if FAILS else 0)
