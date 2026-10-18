#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Offline tests for gather/collectors/robots_hardware.py (gp-deployment-pairs, a monthly series
derived from the section's events with deployment cases), including multi-run merges through
ledger.prepare on a scratch data repo. Reads the data repo's metric registry.

Run:  uv run gather/tests/test_collector_robots_hardware.py
"""
import datetime as dt
import os
import shutil
import sys
import tempfile

GATHER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(GATHER, "collectors"))

import common  # noqa: E402
import ledger  # noqa: E402
import robots_hardware as rh  # noqa: E402

FAILS = []
TODAY = dt.date(2026, 10, 18)
REG = common.registry(rh.SECTION)
REAL_DATA = ledger.DATA


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def ev(id_, published, maker, customer, status="working", basis="source", **kw):
    d = {"maker": maker, "platform": "P", "customer": customer, "job": "moves totes", "status": status}
    if status == "working":
        d["autonomy"] = "autonomously"
    return {"id": id_, "date": id_[:10], "published": published, "published_basis": basis,
            "retrieved": published if basis == "seen" else "2026-10-18", "kind": "achievement",
            "topics": ["kpi"], "claim": "A humanoid does production work at a named customer site.",
            "sources": [{"url": f"https://x.org/{id_}", "title": "t", "primary": True}],
            "significance": 2, "collector": "test", "deployment": d,
            "verification": {"status": "verified", "by": "t", "at": "2026-10-18"}, **kw}


def wd(id_, published, target):
    return dict(ev(id_, published, "X", "Y"), kind="retraction", withdrawn=True, supersedes=[target])


EVS = [ev("2025-04-06-a", "2025-04-06", "Figure", "BMW"),
       ev("2025-11-20-b", "2025-11-20", "Agility", "GXO"),
       ev("2025-12-18-c", "2025-12-18", "Spirit AI", "CATL"),
       ev("2025-12-20-d", "2025-12-20", "Figure", "BMW", status="ended")]

rows = rh.pair_rows(REG, EVS, "t", TODAY)
r = {x["obs"]: x for x in rows}
case("rows pass the registry/ledger row checks", common.check(rows, REG) == [])
case("one row per month from START to the current month",
     sorted(r) == rh.months(rh.START, TODAY) and sorted(r)[0] == "2023-01" and sorted(r)[-1] == "2026-10")
case("value = cases counted among events published by the month's end (ended stays counted)",
     [r[m]["value"] for m in ("2025-03", "2025-04", "2025-11", "2025-12", "2026-10")] == ["0", "1", "2", "3", "3"])
case("dated by rule: month end, the current month capped at today",
     r["2025-11"]["published"] == "2025-11-30" and r["2025-11"]["published_basis"] == "rule"
     and r["2026-10"]["published"] == "2026-10-18")
case("note names the month's changes and their events",
     "+ Agility / GXO" in r["2025-11"]["note"] and "2025-11-20-b" in r["2025-11"]["note"])
case("no case ever counted: no rows (not a run of zeros)",
     rh.pair_rows(REG, [ev("2025-01-01-z", "2025-01-01", "A", "B", status="disputed")], "t", TODAY) == [])


# --- multi-run merges through the real ledger code on a scratch data repo ------------------
def run(events, today):
    """One collector run + merge, as gather/collectors/run.sh does; the effective series after it."""
    existing = ledger.observations(rh.SECTION)
    staged = common.mark_revisions(rh.pair_rows(REG, events, "t", today), existing)
    path = os.path.join(ledger.DATA, "staged.csv")
    common.write(path, staged)
    errs, _ = ledger.merge(rh.SECTION, obs_files=[path])
    return errs, {o: rw["value"] for (m, o), rw in ledger.obs_as_of(rh.SECTION).items() if m == rh.M_PAIRS}


def as_of(day):
    return {o: rw["value"] for (m, o), rw in ledger.obs_as_of(rh.SECTION, dt.date.fromisoformat(day)).items()
            if m == rh.M_PAIRS}


tmp = tempfile.mkdtemp()
try:
    os.makedirs(os.path.join(tmp, "metrics"))
    os.makedirs(os.path.join(tmp, "ledger", "observations"))
    shutil.copy(os.path.join(REAL_DATA, "metrics", "robots-hardware.csv"), os.path.join(tmp, "metrics"))
    ledger.DATA = tmp
    one = [ev("2026-01-10-a", "2026-01-10", "Agility", "GXO")]
    errs, s = run(one, dt.date(2026, 3, 1))
    case("run 1 merges: Jan-Feb count 1", errs == [] and s["2026-01"] == "1" and s["2026-02"] == "1")
    two = one + [ev("2025-12-05-b", "2025-12-05", "Agility", "GXO")]   # an earlier source of the same pair
    errs, s = run(two, dt.date(2026, 3, 2))
    case("a backfilled earlier source revises Dec 2025 to 1; Jan stays 1", errs == [] and s["2025-12"] == "1"
         and s["2026-01"] == "1")
    errs, s = run(two + [wd("2025-12-05-b-wd", "2026-03-03", "2025-12-05-b")], dt.date(2026, 3, 3))
    case("withdrawing it brings Dec back to 0 and Jan stays 1 (values revise, never get banned)",
         errs == [] and s["2025-12"] == "0" and s["2026-01"] == "1")
    three = one + [ev("2026-02-01-c", "2026-02-01", "Figure", "BMW"), ev("2026-03-10-d", "2026-03-10", "Agility", "GXO")]
    errs, s = run(three, dt.date(2026, 4, 1))
    errs2, s2 = run(three + [wd("2026-01-10-a-wd", "2026-05-01", "2026-01-10-a"),
                             wd("2026-02-01-c-wd", "2026-05-01", "2026-02-01-c")], dt.date(2026, 5, 2))
    case("later withdrawals revise the past months, dated first seen: as of April the count is still 2",
         errs == errs2 == [] and s["2026-03"] == "2" and s2["2026-03"] == "1" and s2["2026-01"] == "0"
         and as_of("2026-04-15")["2026-03"] == "2")
    day = dt.date(2026, 6, 10)
    base = [ev("2026-05-01-x", "2026-05-01", "A", "B")]
    plus = base + [ev("2026-06-05-y", "2026-06-05", "C", "D")]
    e1, s1 = run(base, day)
    e2, s2 = run(plus, day)
    e3, s3 = run(plus + [wd("2026-06-05-y-wd", "2026-06-09", "2026-06-05-y")], day)
    case("a same-day revert (1 -> 2 -> 1 in the current month) merges and is effective",
         e1 == e2 == e3 == [] and s1["2026-06"] == "1" and s2["2026-06"] == "2" and s3["2026-06"] == "1"
         and ledger.check_section(rh.SECTION)[0] == [])
finally:
    ledger.DATA = REAL_DATA
    shutil.rmtree(tmp)

print(f"\n{len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
