#!/usr/bin/env python3
"""Offline regression tests for the deterministic KPI collectors (collectors/*.py).

Run:  uv run test_collectors.py     (no network; sources come from tests/fixtures/,
                                     small verbatim snippets of the real files)
"""
import datetime as dt
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(ROOT, "tests", "fixtures")
sys.path.insert(0, os.path.join(ROOT, "collectors"))

import climate  # noqa: E402
import common  # noqa: E402
import fusion  # noqa: E402
import ledger  # noqa: E402
import robots_software  # noqa: E402
import rockets  # noqa: E402

FAILS = []
TODAY = dt.date(2026, 9, 28)


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def raises_exit(fn, *a):
    try:
        fn(*a)
    except SystemExit:
        return True
    return False


def _raises(fn, *a):
    try:
        fn(*a)
    except ValueError:
        return True
    return False


def fixture(name):
    return common.fetch("https://example.invalid/" + name, FIX)


def by_key(rows):
    return {(r["metric"], r["obs"]): r for r in rows}


def registry_ok(section, rows):
    """Every row passes ledger.check_obs_row against the section registry."""
    errs = common.check(rows, common.registry(section))
    for e in errs[:5]:
        print("     ", e)
    return not errs and bool(rows)


# --- climate -------------------------------------------------------------------
mm = climate.parse_monthly(fixture("co2_mm_mlo.txt"))
case("climate: monthly MLO parses every data row, values verbatim",
     len(mm) == 8 and mm[0][:2] == ("1958-03", "315.71") and ("2026-05", "432.34") in [m[:2] for m in mm])
gl = climate.parse_monthly(fixture("co2_mm_gl.txt"))
case("climate: negative missing-value sentinel is skipped", [m[0] for m in gl] == ["1979-01", "2026-05", "2026-06"])
case("climate: file creation date parsed from header", climate.file_created(fixture("co2_mm_mlo.txt")) == "2026-09-05")
case("climate: growth file keeps source formatting ('1.90')",
     ("2017", "1.90") in climate.parse_annual(fixture("co2_gr_mlo.txt")))

gr_mlo = climate.parse_annual(fixture("co2_gr_mlo.txt"))
gr_gl = climate.parse_annual(fixture("co2_gr_gl.txt"))
t10 = {y: v for y, v, _ in climate.trend(gr_mlo, 10)}
case("climate: 10-yr MLO trend 2025 = mean 2016-2025 = 2.56", t10.get("2025") == "2.56")
case("climate: 10-yr MLO trend 2020 = 2.43 (24.25/10 rounded half-up, not float 2.42)", t10.get("2020") == "2.43")
case("climate: 10-yr trend starts at the first full window (2010-2019)", min(t10) == "2019")
case("climate: 5-yr MLO trend 2025 = 2.61, 2020 = 2.51",
     {y: v for y, v, _ in climate.trend(gr_mlo, 5)}.get("2025") == "2.61"
     and {y: v for y, v, _ in climate.trend(gr_mlo, 5)}.get("2020") == "2.51")
g10 = {y: v for y, v, _ in climate.trend(gr_gl, 10)}
g5 = {y: v for y, v, _ in climate.trend(gr_gl, 5)}
case("climate: global trends match the verified ledger (10yr 2020/2024/2025 = 2.38/2.62/2.53; 5yr 2020/2025 = 2.44/2.63)",
     (g10["2020"], g10["2024"], g10["2025"], g5["2020"], g5["2025"]) == ("2.38", "2.62", "2.53", "2.44", "2.63"))
case("climate: negative growth rates are kept, only <= -99 sentinels are dropped",
     climate.parse_annual("  2025  -0.20  0.10\n  2024  -99.99  -9.99\n") == [("2025", "-0.20")])
case("climate: no trend window across a gap in the years",
     climate.trend([("2000", "1"), ("2001", "1"), ("2003", "1"), ("2004", "1")], 3) == [])

daily = dict(climate.parse_daily(fixture("co2_daily_mlo.txt")))
case("climate: daily keeps only the last 60 days before the file's latest date",
     "2026-09-24" in daily and "2026-07-27" in daily and "2026-07-26" not in daily and "2026-05-01" not in daily)

crow = climate.collect(FIX, TODAY, "collectors/climate.py@2026-09-28")
ck = by_key(crow)
case("climate: all rows pass ledger.check_obs_row against metrics/climate.csv", registry_ok("climate", crow))
case("climate: emits every source metric and the four derived trends",
     {r["metric"] for r in crow} == {"co2-mlo-monthly", "co2-global-monthly", "co2-mlo-annual", "co2-global-annual",
                                     "co2-growth-mlo-jan-dec", "co2-growth-global-jan-dec", "co2-mlo-daily",
                                     "co2-trend-10yr-mlo-jan-dec", "co2-trend-5yr-mlo-jan-dec",
                                     "co2-trend-10yr-global-jan-dec", "co2-trend-5yr-global-jan-dec"})
r = ck[("co2-mlo-monthly", "2026-05")]
case("climate: rule-basis publication (obs end + 7 d), provenance fields",
     (r["published"], r["published_basis"], r["retrieved"], r["verification"], r["collector"])
     == ("2026-06-07", "rule", "2026-09-28", "collector", "collectors/climate.py@2026-09-28"))
case("climate: rule publication is capped at retrieved (daily 2026-09-24 + 2 d vs retrieved 09-25)",
     by_key(climate.collect(FIX, dt.date(2026, 9, 25), "x"))[("co2-mlo-daily", "2026-09-24")]["published"] == "2026-09-25")
case("climate: notes flag Scripps era, interpolated month, Maunakea site, preliminary",
     "Scripps" in ck[("co2-mlo-monthly", "1958-03")]["note"]
     and "interpolated" in ck[("co2-mlo-monthly", "1975-12")]["note"]
     and "Maunakea" in ck[("co2-mlo-monthly", "2023-01")]["note"]
     and "preliminary" in ck[("co2-mlo-monthly", "2025-09")]["note"]
     and "preliminary" not in ck[("co2-mlo-monthly", "2025-08")]["note"]
     and "preliminary" in ck[("co2-mlo-annual", "2025")]["note"]
     and "preliminary" not in ck[("co2-mlo-annual", "2024")]["note"])
tr = ck[("co2-trend-10yr-mlo-jan-dec", "2025")]
case("climate: trend row is marked derived, cites the growth file and window",
     tr["value"] == "2.56" and tr["source"].endswith("/co2_gr_mlo.txt") and "Derived" in tr["note"]
     and "2016-2025" in tr["note"] and "co2_gr_mlo.txt" in tr["note"] and tr["unit"] == "ppm/yr")

# --- robots-software (METR) --------------------------------------------------------
case("metr: yaml_paths reads nested scalars, ignores comments and list items",
     robots_software.yaml_paths("a: # c\n  b:\n    c: 1\n  d: x\n  l:\n  - y: 2\ne: 3\n")
     == {("a", "b", "c"): "1", ("a", "d"): "x", ("e",): "3"})
bench, ms = robots_software.models(fixture("benchmark_results_1_1.yaml"))
case("metr: fixture models parsed (benchmark name, 6 models, release dates, estimates)",
     bench == "METR-Horizon-v1.1" and len(ms) == 6
     and {m["id"]: m["release"] for m in ms}["gpt_4_turbo_inspect"] == "2024-04-09"
     and abs({m["id"]: m for m in ms}["claude_opus_4_6_inspect"]["p50"]["estimate"] - 718.8) < 0.1)
case("metr: p50 frontier = models that beat every earlier release (same-date tie keeps the higher)",
     [m["id"] for m in robots_software.frontier(ms, "p50")] == ["gpt_4", "gpt_4_1106_inspect", "claude_opus_4_6_inspect"])
case("metr: p80 frontier is computed independently of p50",
     [m["id"] for m in robots_software.frontier(ms, "p80")]
     == ["gpt_4", "gpt_4_turbo_inspect", "claude_opus_4_6_inspect", "gemini_3_1_pro"])
mrow = robots_software.collect(FIX, TODAY, "collectors/robots_software.py@2026-09-28")
mk = by_key(mrow)
case("metr: all rows pass ledger.check_obs_row against metrics/robots-software.csv", registry_ok("robots-software", mrow))
case("metr: emits the release-cohort ids only (never the as-publicly-evaluated *-frontier ids)",
     {r["metric"] for r in mrow} == {"metr-50-horizon-by-release", "metr-80-horizon-by-release"})
reg_rs = common.registry("robots-software")
case("metr: registry: by-release ids (min, irregular, no lag); p80 required from 26H1, old p80 frontier retired after 2025",
     all((reg_rs[m]["unit"], reg_rs[m]["cadence"], reg_rs[m]["release_lag_days"]) == ("min", "irregular", "")
         and "RELEASED" in reg_rs[m]["definition"] for m in robots_software.METRICS.values())
     and reg_rs["metr-80-horizon-by-release"]["required_from"] == "pilot-26H1"
     and reg_rs["metr-80-horizon-frontier"]["retired_after"] == "pilot-2025")
case("metr: legacy rows of the old *-frontier ids are NOT re-stated under the new ids",
     not any(r["obs"] == "2025-11" for r in robots_software.collect(
         FIX, TODAY, "x", [{"metric": "metr-80-horizon-frontier", "obs": "2025-11"},
                           {"metric": "metr-50-horizon-frontier", "obs": "2025-11"}])))
r = mk[("metr-80-horizon-by-release", "2026-02-19")]
case("metr: row = release date, 2-dp estimate, basis seen, note names the model",
     r["value"] == "89.80" and r["published"] == r["retrieved"] == "2026-09-28" and r["published_basis"] == "seen"
     and "gemini_3_1_pro" in r["note"] and "release_date" in r["note"] and r["unit"] == "min")
case("metr: frontier series is strictly increasing per metric",
     all(float(a["value"]) < float(b["value"]) for m in robots_software.METRICS.values()
         for a, b in zip([x for x in mrow if x["metric"] == m], [x for x in mrow if x["metric"] == m][1:])))
case("metr: an HTML 404 page is rejected, not silently parsed as empty",
     raises_exit(robots_software.models, "<!DOCTYPE html>\n<title>404 - METR</title>\n"))

# two vintages: METR re-estimates gemini_3_1_pro (a p80 frontier point) far down
with tempfile.TemporaryDirectory() as tmp:
    v2 = fixture("benchmark_results_1_1.yaml").replace("estimate: 89.801503", "estimate: 1.0")
    with open(os.path.join(tmp, "benchmark_results_1_1.yaml"), "w") as f:
        f.write(v2)
    v1_rows = robots_software.collect(FIX, dt.date(2026, 9, 1), "v1")
    v2_rows = robots_software.collect(tmp, TODAY, "v2", v1_rows)
restated = by_key(v2_rows).get(("metr-80-horizon-by-release", "2026-02-19"))
case("metr: a revised-away frontier date is re-stated at the current frontier (69.87, not 89.80)",
     restated is not None and restated["value"] == "69.87" and "claude_opus_4_6_inspect" in restated["note"])
latest = {}
for r in v1_rows + v2_rows:  # ledger as-of rule: per (metric, obs) the latest-known row wins
    latest[(r["metric"], r["obs"])] = r
head = max((r for (m, _), r in latest.items() if m == "metr-80-horizon-by-release"), key=lambda r: r["obs"])
case("metr: after both vintages the latest p80 frontier in the ledger view is 69.87", head["value"] == "69.87")
case("metr: YYYY-MM ledger dates of the metric are re-stated as of the month end",
     by_key(robots_software.collect(FIX, TODAY, "x", [{"metric": "metr-80-horizon-by-release", "obs": "2024-04"}]))
     [("metr-80-horizon-by-release", "2024-04")]["value"] == "0.93")

# --- rockets (JSR) ---------------------------------------------------------------------
parsed = rockets.parse(fixture("msatannual.txt"))
case("jsr: year rows parsed (Total column, verbatim), all-time Total row skipped",
     parsed == [(1956, "0.0"), (2016, "337.4"), (2024, "2625.9"), (2025, "3194.0"), (2026, "2120.6")])
rrow = rockets.collect(FIX, TODAY, "collectors/rockets.py@2026-09-28")
case("jsr: the partial current year (2026) is NOT emitted", [r["obs"] for r in rrow] == ["1956", "2016", "2024", "2025"])
case("jsr: a year is emitted only once its release lag has passed (2025 absent on 2026-01-10)",
     "2025" not in [r["obs"] for r in rockets.collect(FIX, dt.date(2026, 1, 10), "x")]
     and "2025" in [r["obs"] for r in rockets.collect(FIX, dt.date(2026, 1, 15), "x")])
case("jsr: all rows pass ledger.check_obs_row against metrics/rockets.csv", registry_ok("rockets", rrow))
r = by_key(rrow)[("payload-mass-to-orbit", "2025")]
case("jsr: 2025 = 3194.0 t, rule-published 2026-01-15",
     (r["value"], r["unit"], r["published"], r["published_basis"]) == ("3194.0", "t", "2026-01-15", "rule"))
case("jsr: unexpected column layout fails loudly",
     raises_exit(rockets.parse, "# Bin YDate USA Total\n 1 2020 1.0\n"))

# --- fusion (GPP household electricity prices x WB population, US CPI) ------------------------
FFIX = os.path.join(FIX, "fusion")
fsrc = fusion.Sources(FFIX, None)


def ffix(name):
    return fsrc.get(name, "https://example.invalid/", fresh=False)


img = fusion.parse_main(ffix("wayback-main-20190330190208.html"))
case("fusion: 2019 image chart parsed (June 2018 -> 2018-Q2, 2-decimal values, names in chart order)",
     (img["obs"], img["label"], img["fmt"].startswith("graph-img"))
     == ("2018-Q2", "June 2018", True) and img["prices"][:2] == [("China", "0.08"), ("India", "0.08")]
     and ("Germany", "0.33") in img["prices"])
case("fusion: a world average inside an HTML comment is NOT read", img["avg"] is None)
div = fusion.parse_main(ffix("wayback-main-20221201055133.html"))
case("fusion: HTML-bar chart parsed (March 2022 -> 2022-Q1, stated world average 0.143, UK row)",
     (div["obs"], div["avg"], div["fmt"], len(div["prices"])) == ("2022-Q1", "0.143", "graph-div", 7)
     and dict(div["prices"])["UK"] == "0.333" and dict(div["prices"])["Northern Macedonia"] == "0.099")
new = fusion.parse_main(ffix("wayback-main-20250706075208.html"))
case("fusion: 2025+ page: 'Q2 2025 update' average read, multi-year country table ignored",
     (new["obs"], new["avg"], new["prices"]) == ("2025-Q2", "0.167", []))
case("fusion: live main page (Q2 2026, world average 0.176)",
     (lambda p: (p["obs"], p["avg"]))(fusion.parse_main(ffix("live-main.html"))) == ("2026-Q2", "0.176"))
mp = fusion.parse_map(ffix("wayback-map-20250916083542.html"))
case("fusion: map page parsed (collected in 2024 Q4, stated count = listed count, ISO3 codes and prices)",
     (mp["obs"], mp["n_stated"], len(mp["prices"])) == ("2024-Q4", 8, 8) and ("Germany", "DEU", "0.448") in mp["prices"])
case("fusion: month labels map to their quarter",
     [fusion.month_obs(m, "2024") for m in ("January", "March", "April", "June", "September", "December")]
     == ["2024-Q1", "2024-Q1", "2024-Q2", "2024-Q2", "2024-Q3", "2024-Q4"])
bad = ffix("wayback-main-20221201055133.html").replace("'graph_outside_link'>India</a>", "'graph_outside_link'>India</a><a class='graph_outside_link'>Extra</a>")
case("fusion: a chart whose names and values do not pair up fails loudly", _raises(fusion.parse_main, bad))
case("fusion: CDX parse keeps status-200 captures, sorted",
     fusion.parse_cdx('[["timestamp","statuscode"],["20230101000000","200"],["20220101000000","200"],["20220601000000","404"]]')
     == ["20220101000000", "20230101000000"])

pop, wbn = fusion.population(fusion.parse_wb(ffix("wb-pop.json")))
case("fusion: GPP names -> ISO3 (explicit table for mismatches, WB names otherwise; unknown -> None)",
     [fusion.iso3(n, wbn) for n in ("UK", "N. Macedonia", "Czech Rep.", "UAE", "Germany", "united  states", "Taiwan", "Atlantis")]
     == ["GBR", "MKD", "CZE", "ARE", "DEU", "USA", "TWN", None])
case("fusion: name normalisation folds accents/punctuation ('Côte d'Ivoire' = 'cote d ivoire')",
     fusion.norm("Côte d'Ivoire") == "cote d ivoire" and fusion.norm("Bosnia & Herz.") == "bosnia and herz")
P = {"AAA": {2020: 3}, "BBB": {2018: 1, 2022: 5}, "WLD": {2018: 10, 2020: 8}}
w = fusion.weighted({"AAA": common.Decimal("0.1"), "BBB": common.Decimal("0.3"), "ZZZ": common.Decimal("9")}, P, 2020)
case("fusion: weighting = sum(p*pop)/sum(pop), pop of the latest year <= obs year, no-pop countries excluded",
     (w["mean"], w["n"], w["covered"], w["world"], w["pop_years"], w["excluded"])
     == (common.Decimal("0.15"), 2, 4, 8, [2018, 2020], ["ZZZ"]))
cpi = fusion.parse_bls_cpi(ffix("bls-cpi.txt"))
case("fusion: BLS flat file -> CPI-U CUUR0000SA0 official annual averages (M13 only; monthly/SA series ignored)",
     (cpi[2019], cpi[2024], cpi[2025], min(cpi), max(cpi))
     == (common.Decimal("255.657"), common.Decimal("313.689"), common.Decimal("321.943"), 2014, 2025))
case("fusion: a BLS file without the series' annual averages fails loudly (block page, format change)",
     _raises(fusion.parse_bls_cpi, "series_id\tyear\tperiod\tvalue\n<html>Access Denied</html>\n"))
real, dnote = fusion.deflate(common.Decimal(100), 2019, cpi)
case("fusion: deflation = x CPI2025/CPI(obs year) (BLS CPI-U), no provisional flag when both exist",
     abs(real - common.Decimal(100) * cpi[2025] / cpi[2019]) < common.Decimal("1e-20")
     and "2019 -> 2025" in dnote and "CUUR0000SA0" in dnote and "provisional" not in dnote)
real, dnote = fusion.deflate(common.Decimal(100), 2019, {2019: common.Decimal(100), 2024: common.Decimal(120)})
case("fusion: missing base-year CPI -> latest year as base, flagged provisional",
     real == 120 and "base = 2024 CPI (provisional)" in dnote)
real, dnote = fusion.deflate(common.Decimal(100), 2026, {2019: common.Decimal(100), 2025: common.Decimal(125)})
case("fusion: obs year without CPI uses the latest earlier CPI year (flagged); base 2025 when present",
     real == 100 and "2026 CPI not yet published, 2025 CPI used" in dnote and "base =" not in dnote)
real, _ = fusion.deflate(common.Decimal(100), 2020, {2020: common.Decimal(100), 2025: common.Decimal(125)})
case("fusion: 100 nominal in 2020 = 125 constant-2025 USD at CPI 100 -> 125", real == 125)

frows = fusion.collect(FFIX, TODAY, "collectors/fusion.py@2026-09-28")
fk = by_key(frows)
case("fusion: all rows pass ledger.check_obs_row against metrics/fusion.csv", registry_ok("fusion", frows))
case("fusion: one row per metric and GPP period (earliest capture per period, across both pages)",
     sorted(o for m, o in fk if m == fusion.M_REAL) == ["2018-Q2", "2022-Q1", "2022-Q2", "2024-Q4", "2025-Q4"]
     and sorted(o for m, o in fk if m == fusion.M_AVG) == ["2022-Q1", "2022-Q2", "2025-Q2", "2026-Q2"]
     and len(frows) == len(fk))
case("fusion: period dedupe picks the EARLIEST capture (June 2022: 2023-01-06, not 2023-02-05 or the 2023-03-23 map)",
     fk[(fusion.M_NOM, "2022-Q2")]["published"] == "2023-01-06" and "20230106031622" in fk[(fusion.M_NOM, "2022-Q2")]["source"]
     and fk[(fusion.M_AVG, "2022-Q2")]["value"] == "160.0"
     and "20221201055133" in fk[(fusion.M_NOM, "2022-Q1")]["source"]
     and "/map/" in fk[(fusion.M_NOM, "2024-Q4")]["source"])
r = fk[(fusion.M_REAL, "2022-Q1")]
case("fusion: archived capture -> published = capture date, basis source, note says earliest Wayback capture",
     (r["published"], r["published_basis"], r["retrieved"]) == ("2022-12-01", "source", "2026-09-28")
     and "earliest Wayback capture" in r["note"] and r["source"].startswith("https://web.archive.org/web/20221201055133id_/"))
r = fk[(fusion.M_REAL, "2025-Q4")]
case("fusion: live-only period -> basis seen, published = retrieved, live URL",
     (r["published"], r["retrieved"], r["published_basis"], r["source"]) == ("2026-09-28", "2026-09-28", "seen", fusion.MAP)
     and "first seen on the live page" in r["note"]
     and fk[(fusion.M_AVG, "2026-Q2")]["published_basis"] == "seen")


def popw_by_hand(prices, year):
    """Independent float re-implementation over the fixture population JSON."""
    import json
    recs = json.loads(ffix("wb-pop.json"))[1]
    num = den = 0.0
    for iso, p in prices.items():
        ys = [int(x["date"]) for x in recs if x["countryiso3code"] == iso and x["value"] and int(x["date"]) <= year]
        if ys:
            v = next(x["value"] for x in recs if x["countryiso3code"] == iso and int(x["date"]) == max(ys))
            num, den = num + p * v, den + v
    return num / den * 1000


hand = popw_by_hand({"IND": 0.074, "CHN": 0.076, "MKD": 0.099, "USA": 0.162, "GBR": 0.333, "DEU": 0.457}, 2022)
case(f"fusion: 2022-Q1 weighted nominal = hand computation ({hand:.2f}); DEU uses its 2021 population (2022 null)",
     fk[(fusion.M_NOM, "2022-Q1")]["value"] == f"{hand:.1f}"
     and "6 countries" in fk[(fusion.M_NOM, "2022-Q1")]["note"] and "2021/2022" in fk[(fusion.M_NOM, "2022-Q1")]["note"])
case("fusion: real = nominal x CPI2025/CPI2022 (BLS CPI-U), rounded to 0.1; notes say inputs are as retrieved",
     abs(float(fk[(fusion.M_REAL, "2022-Q1")]["value"]) - hand * float(cpi[2025] / cpi[2022])) < 0.051
     and "population weights and CPI as retrieved on 2026-09-28" in fk[(fusion.M_REAL, "2022-Q1")]["note"]
     and "population weights as retrieved on 2026-09-28" in fk[(fusion.M_NOM, "2022-Q1")]["note"])
case("fusion: coverage note (n, % of world pop) and excluded Taiwan (no WB population)",
     "% of world population" in fk[(fusion.M_REAL, "2022-Q1")]["note"] and "excluded" in fk[(fusion.M_REAL, "2022-Q1")]["note"]
     and "TWN" in fk[(fusion.M_REAL, "2022-Q1")]["note"])
hand_map = popw_by_hand({c if c != "CRC" else "CRI": float(v) for _, c, v in mp["prices"]}, 2024)
case(f"fusion: map page Costa Rica code CRC is fixed to ISO3 CRI and weighted ({hand_map:.2f})",
     fk[(fusion.M_NOM, "2024-Q4")]["value"] == f"{hand_map:.1f}" and "CRC" not in fk[(fusion.M_NOM, "2024-Q4")]["note"])
with tempfile.TemporaryDirectory() as tmp:
    for f in os.listdir(FFIX):
        with open(os.path.join(FFIX, f), encoding="utf-8") as a, open(os.path.join(tmp, f), "w", encoding="utf-8") as b:
            b.write(a.read().replace('"code2":"DEU","price":"0.448"', '"code2":"DEU","price":"2.220"'))
    gk = by_key(fusion.collect(tmp, TODAY, "x"))
r = gk[(fusion.M_NOM, "2024-Q4")]
hand_ok = popw_by_hand({c if c != "CRC" else "CRI": float(v) for _, c, v in mp["prices"] if c != "DEU"}, 2024)
case("fusion: a price > 1 USD/kWh (GPP conversion error, e.g. Syria 2.220) is excluded and noted",
     r["value"] == f"{hand_ok:.1f}" and "implausible" in r["note"] and "DEU 2.220" in r["note"])
case("fusion: gpp-avg = stated USD/kWh x 1000 (0.143 -> 143.0)", fk[(fusion.M_AVG, "2022-Q1")]["value"] == "143.0")

old = [dict(fk[(fusion.M_REAL, "2022-Q1")], value="1.0", retrieved="2026-01-01"),
       dict(fk[(fusion.M_REAL, "2025-Q4")], value="2.0", published="2026-08-01", retrieved="2026-08-01")]
rv = by_key(fusion.collect(FFIX, TODAY, "x", old))
r = rv[(fusion.M_REAL, "2022-Q1")]
case("fusion: a changed derived value (e.g. population/CPI revision) is a revision dated first seen",
     (r["published"], r["retrieved"], r["published_basis"]) == ("2026-09-28", "2026-09-28", "seen")
     and "revises effective ledger value 1.0" in r["note"] and "earliest Wayback capture" not in r["note"])
r = rv[(fusion.M_REAL, "2025-Q4")]
case("fusion: a changed live-derived value (e.g. CPI arrived) is re-stated too, dated today",
     (r["published"], r["published_basis"]) == ("2026-09-28", "seen") and "revises effective ledger value 2.0" in r["note"])
case("fusion: a re-run against its own output is a no-op (identical rows)",
     fusion.collect(FFIX, TODAY, "collectors/fusion.py@2026-09-28", frows) == frows)


class _Down(fusion.Sources):
    def _download(self, url, tries=3):
        raise OSError("network down")


with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(tmp, "cdx-main.json"), "w") as f:
        f.write("cached")
    s = _Down(None, tmp)
    got = (s.get("cdx-main.json", "https://x.invalid/", fresh=True), s.get("wb-cpi.json", "https://x.invalid/", fresh=True))
case("fusion: network failure falls back to the cached copy (warned), else None (warned)",
     got == ("cached", None) and len(s.warnings) == 2 and "cached copy" in s.warnings[0])


def fake_net(overrides=None, seen_urls=None):
    """A Sources._download serving the fixture files by URL (cache-mode runs, no network);
    overrides: {fixture name: text | (text, final url)}."""
    import re as _re

    def download(self, url, tries=3):
        (seen_urls if seen_urls is not None else []).append(url)
        if "/cdx/" in url:
            name = "cdx-main.json" if "electricity_prices" in url else "cdx-map.json"
        elif "api.worldbank.org" in url:
            name = "wb-pop.json"
        elif "download.bls.gov" in url:
            name = "bls-cpi.txt"
        elif m := _re.search(r"/web/(\d+)id_/", url):
            name = f"wayback-{'map' if '/map/' in url else 'main'}-{m[1]}.html"
        else:
            name = "live-map.html" if "/map/" in url else "live-main.html"
        got = (overrides or {}).get(name)
        if got is None:
            got = ffix(name)
        if got is None:
            raise OSError(f"404 {url}")
        return got if isinstance(got, tuple) else (got, url)
    return download


def cache_run(cache, today, overrides=None, existing=(), seen_urls=None):
    saved = fusion.Sources._download
    fusion.Sources._download = fake_net(overrides, seen_urls)
    try:
        return by_key(fusion.collect(None, today, "x", list(existing), cache=cache))
    finally:
        fusion.Sources._download = saved


with tempfile.TemporaryDirectory() as cache:
    urls = []
    c1 = cache_run(cache, TODAY, seen_urls=urls)
    case("fusion: cache-mode run = fixture-mode run (same values and dates for archived captures)",
         all(c1[k]["value"] == fk[k]["value"] for k in fk) and c1[(fusion.M_NOM, "2022-Q2")]["published"] == "2023-01-06")
    case("fusion: World Bank query range ends at the run year",
         any("SP.POP.TOTL" in u and "date=2014:2026" in u for u in urls))
    case("fusion: captures are cached, the live page is frozen per period (seen-map-2025-Q4-<date>)",
         os.path.exists(os.path.join(cache, "wayback-main-20230106031622.html"))
         and os.path.exists(os.path.join(cache, "seen-map-2025-Q4-2026-09-28.html")))
    # an incomplete CDX index (20230106 missing) must not hide the cached earlier capture
    import json as _json
    cdx = _json.loads(ffix("cdx-main.json"))
    short = _json.dumps([x for x in cdx if x[0] != "20230106031622"])
    # ... and the live map now renders 2025 Q4 at drifted FX: the frozen first-seen copy is used
    drift = ffix("live-map.html").replace('"code2":"USA","price":"0.', '"code2":"USA","price":"0.9')
    c2 = cache_run(cache, dt.date(2026, 10, 5), {"cdx-main.json": short, "live-map.html": drift}, existing=c1.values())
    case("fusion: an incomplete CDX index does not hide an already-cached earlier capture",
         c2[(fusion.M_NOM, "2022-Q2")]["published"] == "2023-01-06"
         and c2[(fusion.M_NOM, "2022-Q2")]["value"] == c1[(fusion.M_NOM, "2022-Q2")]["value"])
    case("fusion: a live-only period is re-derived from its frozen first-seen copy (no FX churn, same dates)",
         {k: (r["value"], r["published"], r["retrieved"]) for k, r in c2.items() if k[1] == "2025-Q4"}
         == {k: (r["value"], r["published"], r["retrieved"]) for k, r in c1.items() if k[1] == "2025-Q4"})

with tempfile.TemporaryDirectory() as cache:
    junk = "<html><title>Wayback Machine</title>Please wait...</html>"
    redirected = (ffix("wayback-main-20230106031622.html"),
                  "https://web.archive.org/web/20230107000000id_/https://www.globalpetrolprices.com/electricity_prices/")
    c3 = cache_run(cache, TODAY, {"wayback-main-20221201055133.html": junk, "wayback-main-20230106031622.html": redirected})
    case("fusion: an HTTP-200 non-GPP capture or a redirected capture is neither used nor cached (retried next run)",
         not os.path.exists(os.path.join(cache, "wayback-main-20221201055133.html"))
         and not os.path.exists(os.path.join(cache, "wayback-main-20230106031622.html"))
         and "20221203030135" in c3[(fusion.M_NOM, "2022-Q1")]["source"]       # falls to the next capture (map)
         and "20230205071214" in c3[(fusion.M_NOM, "2022-Q2")]["source"])
    good_wb = ffix("wb-pop.json")
    s = fusion.Sources(None, cache)
    s._write("wb-pop.json", good_wb)
    s._download = lambda url, tries=3: ("[{\"message\": \"error\"}]", url)
    case("fusion: a malformed fresh World Bank answer does not overwrite the last good copy",
         s.get("wb-pop.json", "https://x.invalid/", fresh=True, validate=fusion.parse_wb) == good_wb
         and open(os.path.join(cache, "wb-pop.json")).read() == good_wb)

case("fusion: a map listing fewer countries than it states is rejected (truncated capture)",
     _raises(fusion.parse_map, ffix("live-map.html").replace("for 8 countries", "for 143 countries")))
sn = [{"date": d, "ts": d.replace("-", ""), "url": d, "parsed": {"prices": [("x", "0.1")] * n, "avg": "0.2"}}
      for d, n in (("2020-01-01", 100), ("2020-02-01", 140), ("2020-03-01", 104), ("2020-04-01", 105))]
warn = []
kept = [len(x["parsed"]["prices"]) for x in fusion.drop_collapsed(sn, warn)]
case("fusion: a capture with < 75% of the countries of earlier captures loses its prices (avg kept)",
     kept == [100, 140, 0, 105] and len(warn) == 1 and "104" in warn[0])
pr, _, rej = fusion.country_prices({"page": "map", "url": "u", "parsed": {"obs": "2020-Q1", "prices": [
    ("South Korea", "KOR", "0.000"), ("Germany", "DEU", "0.300")]}}, {})
case("fusion: documented GPP errata are excluded with their evidence (KOR 0.00 in 2020-Q1)",
     list(pr) == ["DEU"] and "erratum" in rej[0] and "KOR" in rej[0])

# --- revisions (common.mark_revisions) -------------------------------------------------------
def lrow(obs, value, published, verification="collector", basis="rule", retrieved=None, metric="payload-mass-to-orbit"):
    """A ledger row (only the fields mark_revisions / obs_as_of look at matter)."""
    return {"metric": metric, "obs": obs, "value": value, "unit": "t", "published": published,
            "published_basis": basis, "retrieved": retrieved or published, "verification": verification}


ledger_rows = [lrow("2025", "3141", "2026-01-15"), lrow("2024", "2625.90", "2025-01-15", "verified")]
marked = by_key(common.mark_revisions(rrow, ledger_rows))
r = marked[("payload-mass-to-orbit", "2025")]
case("revisions: a changed value is re-dated to first seen (basis seen, published = retrieved)",
     (r["published"], r["published_basis"]) == ("2026-09-28", "seen") and "3141" in r["note"])
case("revisions: numerically unchanged and brand-new obs keep the rule date",
     marked[("payload-mass-to-orbit", "2024")]["published_basis"] == "rule"
     and marked[("payload-mass-to-orbit", "2016")]["published"] == "2017-01-15")
case("revisions: re-dated rows still pass ledger.check_obs_row", registry_ok("rockets", list(marked.values())))

# effective-row semantics: compare with ledger.obs_as_of's winner, not with every historical value
revert = [lrow("2025", "3194.0", "2026-01-15"),                                     # original release
          lrow("2025", "3200.0", "2026-05-01", basis="seen")]                       # later source revision
r = by_key(common.mark_revisions(rrow, revert))[("payload-mass-to-orbit", "2025")]
case("revisions: a revert to an EARLIER value (3194.0 after 3200.0) is a revision, re-dated to first seen",
     (r["published"], r["published_basis"]) == ("2026-09-28", "seen") and "3200.0" in r["note"])
r = by_key(common.mark_revisions(rrow, revert[::-1] + [lrow("2025", "3194", "2026-06-01", "verified", "source")]))[
    ("payload-mass-to-orbit", "2025")]
case("revisions: equal to the effective row (numerically, 3194 vs 3194.0) -> unchanged, rule date kept",
     (r["published"], r["published_basis"]) == ("2026-01-15", "rule") and "revises" not in r["note"])
legacy_only = [lrow("2025", "3100", "2026-08-01", "legacy", "seen"), lrow("2024", "2625.9", "2026-08-01", "legacy", "seen")]
lm = by_key(common.mark_revisions(rrow, legacy_only))
case("revisions: only a legacy row exists (differing) -> primary-source value keeps its rule date, note flags legacy",
     (lm[("payload-mass-to-orbit", "2025")]["published"], lm[("payload-mass-to-orbit", "2025")]["published_basis"])
     == ("2026-01-15", "rule") and "legacy report value 3100" in lm[("payload-mass-to-orbit", "2025")]["note"])
case("revisions: only a legacy row exists (equal) -> rule date kept (merge admits it: outranks legacy)",
     lm[("payload-mass-to-orbit", "2024")]["published_basis"] == "rule" and "legacy" not in lm[("payload-mass-to-orbit", "2024")]["note"])
mixed = [lrow("2025", "3194.0", "2026-01-15"), lrow("2025", "3300", "2026-08-01", "legacy", "seen")]
r = by_key(common.mark_revisions(rrow, mixed))[("payload-mass-to-orbit", "2025")]
case("revisions: a newer legacy row does not outrank a non-legacy one (equal to the effective collector row)",
     r["published_basis"] == "rule" and "revises" not in r["note"])

# end to end through the real ledger.prepare (merge planning), with a stubbed ledger state
def effective_after(existing, staged, quiet=False):
    """(rows ledger.prepare would admit, obs_as_of of existing + admitted) for a rockets merge."""
    existing = [dict(r, source="https://example.invalid/x", collector="test", note="") for r in existing]
    saved = ledger.observations, ledger.events, ledger.assessments
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "staged.csv")
        common.write(f, staged)
        try:
            ledger.observations, ledger.events, ledger.assessments = (lambda s: list(existing)), (lambda s: []), (lambda s: [])
            errs, _, plan = ledger.prepare("rockets", obs_files=[f])
        finally:
            ledger.observations, ledger.events, ledger.assessments = saved
    for e in [] if quiet else errs[:5]:
        print("     ", e)
    admitted = plan["obs"] if not errs else None
    return admitted, ledger.obs_as_of("", rows=existing + (admitted or []))


adm, eff = effective_after(revert, common.mark_revisions(rrow, revert))
case("revisions: after merging, the reverted value is the effective one",
     adm is not None and eff[("payload-mass-to-orbit", "2025")]["value"] == "3194.0"
     and eff[("payload-mass-to-orbit", "2025")]["collector"] == "collectors/rockets.py@2026-09-28")
case("revisions: without re-dating, the reverted value would NOT become effective (merge refuses the exact "
     "duplicate of the original row, or it stays outranked; regression guard)",
     effective_after(revert, rrow, quiet=True)[1][("payload-mass-to-orbit", "2025")]["value"] == "3200.0")
adm, eff = effective_after(legacy_only, common.mark_revisions(rrow, legacy_only))
case("revisions: legacy-only rows are superseded by the collector value (both the equal and the differing one)",
     adm is not None and eff[("payload-mass-to-orbit", "2025")]["value"] == "3194.0" and eff[("payload-mass-to-orbit", "2024")]["verification"] == "collector")
same = [lrow(r["obs"], r["value"], r["published"]) for r in rrow]
case("revisions: a re-run against its own output is a no-op (all rows dedup)",
     effective_after(same, common.mark_revisions(rrow, same))[0] == [])

# --- CLI: staged file loads with the exact ledger header ------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    ok = True
    for script, section, fix in (("climate.py", "climate", FIX), ("robots_software.py", "robots-software", FIX),
                                 ("rockets.py", "rockets", FIX), ("fusion.py", "fusion", FFIX)):
        out = os.path.join(tmp, f"{section}.csv")
        p = subprocess.run([sys.executable, os.path.join(ROOT, "collectors", script), "--fixture", fix,
                            "--out", out, "--today", "2026-09-28"], capture_output=True, text=True)
        try:
            rows = ledger.load_obs(out)  # raises unless the header is exactly OBS_COLUMNS
            ok &= p.returncode == 0 and bool(rows) and all(r["verification"] == "collector" for r in rows)
        except (OSError, ValueError) as e:
            print("     ", script, e, p.stderr[-500:])
            ok = False
    case("cli: each collector writes a staged CSV with exactly ledger.OBS_COLUMNS", ok)

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall collector tests passed")
sys.exit(1 if FAILS else 0)
