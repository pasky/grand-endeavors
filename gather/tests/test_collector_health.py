#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Offline tests for gather/collectors/health.py (WHO GHO HALE at birth).

Run:  uv run gather/tests/test_collector_health.py     (no network; the source is
      gather/tests/fixtures/who_hale.json, verbatim records trimmed from the real
      https://ghoapi.azureedge.net/api/WHOSIS_000002 answer: 2000/2020/2021, 7/6/7
      countries x 3 sexes, GLOBAL x 3 sexes, one WHO region and one WB income group)
"""
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
GATHER = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, os.path.join(GATHER, "collectors"))

import common  # noqa: E402
import health  # noqa: E402

FAILS = []
TODAY = dt.date(2026, 10, 1)


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


with open(os.path.join(FIX, health.FIXTURE), encoding="utf-8") as f:
    TEXT = f.read()

# --- parsing ---------------------------------------------------------------------------
recs = health.parse(TEXT)
case("parse: all 75 fixture records", len(recs) == 75)
jpn = [r for r in recs if r["place"] == "JPN" and r["year"] == 2021 and r["sex"] == "SEX_BTSX"]
case("parse: JPN 2021 both sexes = unrounded NumericValue, GHO date",
     len(jpn) == 1 and jpn[0]["value"] == Decimal("73.39518386") and jpn[0]["date"] == "2024-08-02")
doc = json.loads(TEXT)
case("parse: paged answer (@odata.nextLink) is refused",
     raises(health.parse, json.dumps(dict(doc, **{"@odata.nextLink": "https://x/?$skip=1"}))))
case("parse: duplicated record is refused",
     raises(health.parse, json.dumps(dict(doc, value=doc["value"] + doc["value"][:1]))))
case("parse: empty answer is refused", raises(health.parse, json.dumps({"value": []})))
nodate = dict(doc, value=[dict(doc["value"][0], Date=None)])
case("parse: missing Date -> None", health.parse(json.dumps(nodate))[0]["date"] is None)

# --- median math -----------------------------------------------------------------------
D = Decimal
case("median: odd count = middle value", health.median([D("3"), D("1"), D("2")]) == D("2"))
case("median: even count = mean of the two middle values",
     health.median([D("4"), D("1"), D("3"), D("2")]) == D("2.5"))
case("median: empty is an error", raises(health.median, []))

# --- both-sexes filter and per-year medians ----------------------------------------------
warn = []
meds = {y: (m, n, d) for y, m, n, d in health.country_medians(recs, warn)}
case("medians: years 2000/2020/2021, no warnings", sorted(meds) == [2000, 2020, 2021] and not warn)
case("medians: 2021 odd (7 countries) = BRA 61.8265355",
     meds[2021][:2] == (D("61.8265355"), 7))
case("medians: 2020 even (6 countries) = (BRA 63.27264316 + USA 64.4312583) / 2",
     meds[2020][:2] == ((D("63.27264316") + D("64.4312583")) / 2, 6))
case("medians: date = GHO record date", meds[2021][2] == "2024-08-02")
# both-sexes filter: male/female records must not leak into the median
only_m = [r for r in recs if r["sex"] != "SEX_BTSX"]
case("filter: no both-sexes records -> no medians", health.country_medians(only_m, []) == [])
# region / income-group / global records are not countries
case("filter: only COUNTRY records count",
     meds[2021][1] == len({r["place"] for r in recs if r["kind"] == "COUNTRY" and r["year"] == 2021}))
# coverage guard: a year with far fewer countries is skipped
thin = [r for r in recs if not (r["year"] == 2000 and r["kind"] == "COUNTRY" and r["place"] not in ("JPN", "USA"))]
w = []
case("guard: a thin year (2 of 7 countries) is skipped with a warning",
     [y for y, *_ in health.country_medians(thin, w)] == [2020, 2021] and len(w) == 1 and "2000" in w[0])

# --- staged rows ------------------------------------------------------------------------
rows = health.collect(FIX, TODAY, f"collectors/health.py@{TODAY}")
by = {(r["metric"], r["obs"]): r for r in rows}
case("rows: 3 median + 3 global", sorted(by) == sorted(
    [(m, y) for m in ("hale-median-country", "hale-global") for y in ("2000", "2020", "2021")]))
case("rows: median values rounded half-up to 1 decimal",
     [by[("hale-median-country", y)]["value"] for y in ("2000", "2020", "2021")] == ["60.9", "63.9", "61.8"])
case("rows: global values = WHO display point estimates (both sexes)",
     [by[("hale-global", y)]["value"] for y in ("2000", "2020", "2021")] == ["58.1", "62.8", "61.9"])
case("rows: note gives the number of countries and the series span",
     "median across 6 countries" in by[("hale-median-country", "2020")]["note"]
     and "GHE series 2000-2021" in by[("hale-median-country", "2020")]["note"])
case("rows: published = GHO record date, basis source",
     all(r["published"] == "2024-08-02" and r["published_basis"] == "source" for r in rows))
case("rows: all pass ledger.check_obs_row against metrics/health.csv",
     common.check(rows, common.registry("health")) == [])
early = health.collect(FIX, dt.date(2024, 1, 1), "collectors/health.py@2024-01-01")
case("rows: a GHO date after retrieval falls back to basis seen (published = retrieved)",
     all(r["published_basis"] == "seen" and r["published"] == "2024-01-01" for r in early)
     and common.check(early, common.registry("health")) == [])

# --- CLI --------------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    out = os.path.join(tmp, "health.csv")
    p = subprocess.run([sys.executable, os.path.join(GATHER, "collectors", "health.py"), "--out", out,
                        "--fixture", FIX, "--today", str(TODAY)], capture_output=True, text=True)
    case("cli: exit 0 and writes 6 rows", p.returncode == 0 and os.path.exists(out)
         and len(open(out, encoding="utf-8").read().splitlines()) == 7)
    if p.returncode:
        print(p.stdout, p.stderr)

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall ok")
sys.exit(1 if FAILS else 0)
