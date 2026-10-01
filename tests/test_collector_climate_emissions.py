#!/usr/bin/env python3
"""Offline tests for collectors/climate_emissions.py (Global Carbon Budget emissions series).

Run:  uv run tests/test_collector_climate_emissions.py

Fixture: tests/fixtures/Global_Carbon_Budget_2025_v0.6.xlsx is the real GCB 2025 global
budget file (globalcarbonbudget.org/download/2341/) trimmed to its 'Global Carbon Budget'
sheet: the 22 header/notes rows and years 1959, 1960, 2019-2024 kept verbatim (workbook,
rels and shared strings unchanged; other sheets dropped).
"""
import datetime as dt
import io
import os
import sys
import zipfile
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
sys.path.insert(0, os.path.join(ROOT, "collectors"))

import climate  # noqa: E402
import climate_emissions as ce  # noqa: E402
import common  # noqa: E402

FAILS = []
TODAY = dt.date(2026, 10, 1)


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def exits(fn, *a):
    try:
        fn(*a)
    except SystemExit:
        return True
    return False


fname, data = ce.fetch_xlsx(FIX)
case("fixture: vintage filename found", fname == "Global_Carbon_Budget_2025_v0.6.xlsx")

# --- parsing ---------------------------------------------------------------------
budget = ce.parse_budget(data)
by_year = {y: (f, l, c) for y, f, l, c in budget}
case("parse: header located; the fixture's years in order",
     [y for y, *_ in budget] == ["1959", "1960", "2019", "2020", "2021", "2022", "2023", "2024"])
case("parse: GtC values verbatim from the right columns (2024: fossil excl. carbonation, LUC, carbonation)",
     by_year["2024"] == (Decimal("10.5345464062896"), Decimal("1.25150333333333"), Decimal("0.224290502914317")))
case("parse: shared strings resolved (sheet notes state the 3.664 factor)",
     any("3.664" in v for r in ce.read_sheet(data, ce.SHEET).values() for v in r.values()))


def mutate(old: bytes, new: bytes, part="xl/sharedStrings.xml") -> bytes:
    src, buf = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
    with zipfile.ZipFile(buf, "w") as out:
        for n in src.namelist():
            b = src.read(n)
            out.writestr(n, b.replace(old, new) if n == part else b)
    return buf.getvalue()


case("parse: renamed carbonation column fails loudly",
     exits(ce.parse_budget, mutate(b">cement carbonation sink<", b">cement sink<")))
case("parse: unit change (no 'GtC/yr' cell) fails loudly", exits(ce.parse_budget, mutate(b">GtC/yr<", b">MtC/yr<")))
case("parse: missing sheet fails loudly", exits(ce.read_sheet, data, "No Such Sheet"))
case("parse: an empty value cell fails loudly (no silently skipped year)",
     exits(ce.parse_budget, mutate(b'<c r="G88" s="', b'<c r="Z88" s="', "xl/worksheets/sheet2.xml")))
case("fetch: fixture dir without a budget xlsx fails loudly", exits(ce.fetch_xlsx, os.path.join(FIX, "fusion")))

# --- unit conversion -------------------------------------------------------------
case("convert: GtC x 3.664, exact decimal, half-up to 2 dp",
     ce.to_gtco2(Decimal("10")) == "36.64" and ce.to_gtco2(Decimal("0.0025")) == "0.01"
     and ce.to_gtco2(Decimal("1.0000136463")) == "3.66")
ser = {(m, y): v for m, y, v, _ in ce.series(budget)}
# 2024 by hand: (10.5345464062896 - 0.224290502914317) * 3.664 = 37.7768... ; + 1.25150333333333 * 3.664
case("convert: 2024 fossil net of carbonation = 37.78 GtCO2 (gross would be 38.60)",
     ser[("co2-emissions-fossil-gcb", "2024")] == "37.78")
case("convert: 2024 total = 42.36 GtCO2 (GCB 2025 key messages: 42.4)", ser[("co2-emissions-total-gcb", "2024")] == "42.36")
case("convert: 2020 COVID dip visible in fossil (2019 > 2020 < 2021)",
     Decimal(ser[("co2-emissions-fossil-gcb", "2019")]) > Decimal(ser[("co2-emissions-fossil-gcb", "2020")])
     < Decimal(ser[("co2-emissions-fossil-gcb", "2021")]))
case("convert: 1959 fossil = (2.41678824533062 - 0.0134227952138527) * 3.664 = 8.81",
     ser[("co2-emissions-fossil-gcb", "1959")] == "8.81")

# --- staged rows -----------------------------------------------------------------
paper = {"metric": "co2-emissions-total-gcb", "obs": "2024", "value": "42.4", "unit": "GtCO2",
         "source": "https://essd.copernicus.org/articles/18/3211/2026/", "published": "2026-05-13",
         "published_basis": "source", "retrieved": "2026-09-25", "collector": "backfill", "verification": "verified",
         "note": ""}
rows = ce.collect(FIX, TODAY, "collectors/climate_emissions.py@2026-10-01", [paper])
rk = {(r["metric"], r["obs"]): r for r in rows}
errs = common.check(rows, common.registry("climate"))
for e in errs[:5]:
    print("     ", e)
case("rows: all pass ledger.check_obs_row against metrics/climate.csv", rows and not errs)
case("rows: both metrics for each fixture year", len(rows) == 16
     and {r["metric"] for r in rows} == {"co2-emissions-fossil-gcb", "co2-emissions-total-gcb"})
r = rk[("co2-emissions-fossil-gcb", "2024")]
case("rows: GtCO2, seen basis (no stated release date), provenance",
     (r["unit"], r["published"], r["published_basis"], r["retrieved"], r["verification"], r["source"], r["collector"])
     == ("GtCO2", "2026-10-01", "seen", "2026-10-01", "collector", ce.DATA_URL,
         "collectors/climate_emissions.py@2026-10-01"))
case("rows: note cites vintage, file, sheet and derivation",
     all(s in r["note"] for s in ("GCB 2025", "Global_Carbon_Budget_2025_v0.6.xlsx", "'Global Carbon Budget'",
                                  "cement carbonation sink", "x 3.664")))
case("rows: note compares with a differing effective ledger value at its precision",
     "effective ledger value 42.4" in rk[("co2-emissions-total-gcb", "2024")]["note"]
     and "agrees at its precision" in rk[("co2-emissions-total-gcb", "2024")]["note"]
     and "effective ledger" not in r["note"])
case("rows: a real mismatch is flagged", "DIFFERS" in ce.ledger_note("42.36", dict(paper, value="41.9")))
case("rows: deterministic (same inputs -> same rows)",
     rows == ce.collect(FIX, TODAY, "collectors/climate_emissions.py@2026-10-01", [paper]))

# --- wiring into the climate collector ----------------------------------------------
both = climate.collect_all(FIX, TODAY, "collectors/climate.py@2026-10-01")
case("climate.collect_all = NOAA rows + GCB rows, each with its own collector id",
     {r["collector"] for r in both if r["metric"].startswith("co2-emissions")} == {"collectors/climate_emissions.py@2026-10-01"}
     and {r["collector"] for r in both if not r["metric"].startswith("co2-emissions")} == {"collectors/climate.py@2026-10-01"}
     and len(both) == len(climate.collect(FIX, TODAY, "x")) + 16)
case("climate.collect_all rows pass check_obs_row", not common.check(both, common.registry("climate")))

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall ok")
sys.exit(1 if FAILS else 0)
