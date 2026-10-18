#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Offline tests for gather/collectors/robots_hardware.py (gp-deployment-pairs, derived from the
section's events with deployment cases). Reads the data repo's metric registry.

Run:  uv run gather/tests/test_collector_robots_hardware.py
"""
import datetime as dt
import os
import sys

GATHER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(GATHER, "collectors"))

import common  # noqa: E402
import robots_hardware as rh  # noqa: E402

FAILS = []
TODAY = dt.date(2026, 10, 18)
REG = common.registry(rh.SECTION)


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


def by_obs(rows):
    return {r["obs"]: r for r in rows}


EVS = [ev("2025-04-06-a", "2025-04-06", "Figure", "BMW"),
       ev("2025-11-20-b", "2025-11-20", "Agility", "GXO"),
       ev("2025-12-18-c", "2025-12-18", "Spirit AI", "CATL"),
       ev("2025-12-18-d", "2025-12-18", "Figure", "BMW", status="ended"),
       ev("2026-06-24-e", "2026-06-24", "Galbot", "CATL", basis="seen")]
rows = rh.pair_rows(REG, EVS, [], "t", TODAY)
r = by_obs(rows)
case("rows pass the registry/ledger row checks", common.check(rows, REG) == [] and len(rows) == 4)
case("one row per date the count changes, value = the count after it",
     [(o, r[o]["value"]) for o in sorted(r)] == [("2025-04-06", "1"), ("2025-11-20", "2"),
                                                 ("2025-12-18", "3"), ("2026-06-24", "4")])
case("dated by the changing event's publication (basis source); its source; note names the case",
     r["2025-11-20"]["published"] == "2025-11-20" and r["2025-11-20"]["published_basis"] == "source"
     and r["2025-11-20"]["source"] == "https://x.org/2025-11-20-b" and "+ Agility / GXO" in r["2025-11-20"]["note"])
case("a first-seen event makes its row first-seen (published = retrieved = today)",
     r["2026-06-24"]["published_basis"] == "seen" and r["2026-06-24"]["published"] == str(TODAY))

# the merged ledger, then a backfilled earlier case and a superseded event
existing = [dict(x, verification="collector") for x in rows]
more = EVS + [ev("2024-06-27-f", "2024-06-27", "Agility", "GXO")]  # an earlier source of a known pair
r2 = by_obs(rh.pair_rows(REG, more, existing, "t", TODAY))
case("an earlier source of a known pair moves its start: new row dated by source, the old date withdrawn",
     r2["2024-06-27"]["value"] == "1" and r2["2024-06-27"]["published"] == "2024-06-27"
     and r2["2025-11-20"]["verification"] == "withdrawn")
case("later counts that change are revisions dated first seen",
     r2["2025-04-06"]["value"] == "2" and r2["2025-04-06"]["published"] == str(TODAY)
     and "revises 1" in r2["2025-04-06"]["note"])
gone = EVS + [dict(ev("2025-12-18-c-wd", "2026-10-18", "Spirit AI", "CATL"), kind="retraction", withdrawn=True,
                   supersedes=["2025-12-18-c"])]
r3 = by_obs(rh.pair_rows(REG, gone, existing, "t", TODAY))
case("a withdrawn event drops its case; the date it alone changed is withdrawn",
     r3["2025-12-18"]["verification"] == "withdrawn" and r3["2026-06-24"]["value"] == "3")
case("no deployment cases: no rows", rh.pair_rows(REG, [], [], "t", TODAY) == [])

print(f"\n{len(FAILS)} failure(s)")
sys.exit(1 if FAILS else 0)
