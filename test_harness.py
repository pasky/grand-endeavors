#!/usr/bin/env python3
"""Regression tests for the deterministic harness checks (kpi.py, validate.py).

Run:  uv run test_harness.py      (no network; builds throwaway period dirs)
Each case pins a behavior that a review found broken or easy to regress.
"""
import csv
import os
import sys
import tempfile
import urllib.error
from unittest import mock

import kpi
import validate

FAILS = []


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def store_env():
    """Temp ROOT with a climate registry + pilot-2025/pilot-26H1 vintages."""
    root = tempfile.mkdtemp()
    kpi.ROOT = root
    write_csv(f"{root}/metrics/climate.csv", kpi.REG_COLUMNS, [
        ["co2-mlo-monthly", "ppm", "pilot-26H1", "", "NOAA Mauna Loa monthly mean CO2 dry-air mole fraction"],
        ["co2-trend-old", "ppm/yr", "", "pilot-2025", "Old basis decadal trend of global annual means (retired)"],
        ["co2-mlo-annual", "ppm", "", "", "NOAA Mauna Loa calendar-year annual mean CO2"],
    ])
    write_csv(f"{root}/pilot-2025/kpis/climate.csv", kpi.COLUMNS, [
        ["co2-mlo-monthly", "2025-11", "426.5", "ppm", "headline", "https://x.org/a", ""],
        ["co2-trend-old", "2020", "2.4", "ppm/yr", "headline", "https://x.org/a", ""],
        ["co2-mlo-annual", "2024", "424.6", "ppm", "series", "https://x.org/a", ""],
    ])
    return root


def check26(rows, evidence_text="432.34 427.35 424.61 426.46"):
    root = kpi.ROOT
    path = f"{root}/pilot-26H1/kpis/climate.csv"
    write_csv(path, kpi.COLUMNS, rows)
    ev = f"{root}/note.md"
    open(ev, "w").write(evidence_text)
    return kpi.check(path, [ev])


def has(errs, needle):
    return any(needle in e for e in errs)


def main():
    # --- number matching -----------------------------------------------------
    nums = kpi.kpi_numbers("fell −0.5% in 2016-2025, $2000/kg, 38,082 Mt, (+1.0%)")
    case("kpi_numbers keeps sign, years-as-data, thousands", {-0.5, 2000.0, 38082.0, 1.0} <= nums and -2025.0 not in nums)
    case("negative value matches unsigned prose", kpi.kpi_traceable("-0.5", {0.5}))
    case("positive value never matches negative evidence", not kpi.kpi_traceable("0.5", {-0.5}))
    case("roundup numbers(): unit suffix + no partial decimals",
         validate.numbers("9% $8.99B 12.5GW in 2025 the") == {"9", "8.99", "12.5"})

    # --- kpi check -----------------------------------------------------------
    store_env()
    ok = [["co2-mlo-monthly", "2026-05", "432.34", "ppm", "headline", "https://x.org/a", ""]]
    errs, _ = check26(ok)
    case("clean 26H1 store passes", errs == [])
    errs, _ = check26([["co2-renamed", "2026-05", "432.34", "ppm", "headline", "https://x.org/a", ""]])
    case("unregistered id is an error", has(errs, "not in metrics/climate.csv"))
    case("missing required component is an error", has(errs, "required KPI component 'co2-mlo-monthly'"))
    errs, _ = check26(ok + [["co2-mlo-annual", "2025", "427.35", "ppb", "series", "https://x.org/a", ""]])
    case("unit drift vs registry is an error", has(errs, "differs from the registry"))
    errs, _ = check26(ok + [["co2-trend-old", "2025", "2.4", "ppm/yr", "headline", "https://x.org/a", ""]])
    case("retired id as headline is an error", has(errs, "was retired after"))
    errs, _ = check26(ok + [["co2-mlo-annual", "2026", "427.35", "ppm", "series", "https://x.org/a", ""]])
    case("full-year obs inside a half-year period is an error", has(errs, "ends after the period"))
    errs, _ = check26(ok + [["co2-mlo-annual", "2025", "999.99", "ppm", "series", "https://x.org/a", ""]])
    case("untraceable value is an error", has(errs, "not found in the evidence"))
    errs, _ = check26([["co2-mlo-monthly", "", "", "ppm", "unavailable", "", "NOAA file not updated"]])
    case("'unavailable' with a reason satisfies a required component", errs == [])
    errs, _ = check26([["co2-mlo-monthly", "", "", "ppm", "unavailable", "", ""]])
    case("'unavailable' without a reason is an error", has(errs, "needs an empty value and a note"))
    with open(f"{kpi.ROOT}/metrics/climate.csv", "w") as f:
        f.write(",".join(kpi.REG_COLUMNS) + "\n")
    errs, _ = check26(ok)
    case("header-only registry still enforces registration", has(errs, "not in metrics/climate.csv"))
    with open(f"{kpi.ROOT}/metrics/climate.csv", "a") as f:
        f.write("co2-mlo-monthly,ppm,,,NOAA monthly mean, unquoted comma here\n")
    case("registry row with an unquoted comma is rejected",
         any("wrong number of fields" in e for e in kpi.load_registry("climate")[1]))

    # --- delta + charts --------------------------------------------------------
    store_env()
    check26(ok + [["co2-mlo-annual", "2025", "427.35", "ppm", "series", "https://x.org/a", ""]])
    d = kpi.delta(f"{kpi.ROOT}/pilot-26H1", "climate")
    case("delta flags a seasonal (different-month) comparison", "+5.84" in d and "seasonal" in d)
    chart = kpi.chart(f"{kpi.ROOT}/pilot-26H1", "climate", ["co2-mlo-annual"], label="year")
    case("store-rendered chart verifies clean", kpi.verify_charts(chart, f"{kpi.ROOT}/pilot-26H1") == [])
    case("tampered chart value is caught",
         kpi.verify_charts(chart.replace("427.35", "427.36"), f"{kpi.ROOT}/pilot-26H1") != [])
    y_line = next(ln for ln in chart.splitlines() if "y-axis" in ln)
    clipped = chart.replace(y_line, '    y-axis "ppm" 425 --> 426')
    case("clipping y-axis is caught", has(kpi.verify_charts(clipped, f"{kpi.ROOT}/pilot-26H1"), "clips"))

    # --- link probe (mocked, no network) ---------------------------------------
    def seq(*codes):
        it = iter(codes)

        def fake(req, timeout=15):
            c = next(it)
            if c == 200:
                m = mock.MagicMock()
                m.__enter__.return_value.status = 200
                return m
            raise urllib.error.HTTPError(req.full_url, c, "x", {}, None)
        return fake

    with mock.patch("time.sleep"):
        for codes, want, name in [
            ((404, 200), "ok", "HEAD 404 then GET 200 is alive"),
            ((404, 404, 200), "ok", "one transient GET 404 is retried"),
            ((404, 404, 404), "404", "two GET 404s are dead"),
            ((403, 403), "403", "403 stays warn-level (not dead)"),
        ]:
            with mock.patch("urllib.request.urlopen", seq(*codes)):
                case(name, validate.probe("https://x.org/p") == want)

    print(f"\n{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
