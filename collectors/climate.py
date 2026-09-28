#!/usr/bin/env python3
"""Climate KPI collector: NOAA GML CO2 trend files -> staged observations.

Usage:  uv run collectors/climate.py --out FILE [--fixture DIR] [--today YYYY-MM-DD]

Sources (https://gml.noaa.gov/webdata/ccgg/trends/co2/), all whitespace-separated
text with '#' comment headers (incl. '# File Creation: <ctime>'):
  co2_mm_mlo.txt      year month decimal average deseason ndays stdev unc -> co2-mlo-monthly
  co2_mm_gl.txt       year month decimal average average_unc trend trend_unc -> co2-global-monthly
  co2_annmean_mlo.txt year mean unc                                -> co2-mlo-annual
  co2_annmean_gl.txt  year mean unc                                -> co2-global-annual
  co2_gr_mlo.txt      year ann_inc unc (Jan 1 -> Dec 31 change)     -> co2-growth-mlo-jan-dec
  co2_gr_gl.txt       year ann_inc unc                             -> co2-growth-global-jan-dec
  co2_daily_mlo.txt   year month day decimal value                 -> co2-mlo-daily

Choices:
  - Values are copied verbatim from the file (e.g. '1.90'), so unchanged
    re-observations dedup on merge; negative values (missing sentinels) are skipped.
  - Full history is emitted, except the daily file: only the last DAILY_DAYS days
    before the file's latest date (volume).
  - Derived KPI trends co2-trend-{10,5}yr-{mlo,global}-jan-dec: mean of the N
    consecutive annual growth rates ending in the obs year (obs = final year of
    the window), for every year with a full window; exact decimal arithmetic,
    rounded half-up to 2 decimals; source = the growth-rate file.
  - published: registry release_lag_days rule (NOAA files are re-issued with a
    file-creation date that applies to the vintage, not to each value).
  - Notes flag Scripps-era months (before May 1974), NOAA-interpolated months
    (negative stdev), Maunakea substitute site months (Dec 2022 - Jul 2023) and
    preliminary values (last 12 months / last year of a file; all daily values).
"""
from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal

import common

SECTION = "climate"
BASE = "https://gml.noaa.gov/webdata/ccgg/trends/co2/"
DAILY_DAYS = 60
TRENDS = [  # (metric, growth-rate file, window years, scope label)
    ("co2-trend-10yr-mlo-jan-dec", "co2_gr_mlo.txt", 10, "MLO"),
    ("co2-trend-5yr-mlo-jan-dec", "co2_gr_mlo.txt", 5, "MLO"),
    ("co2-trend-10yr-global-jan-dec", "co2_gr_gl.txt", 10, "global marine-surface"),
    ("co2-trend-5yr-global-jan-dec", "co2_gr_gl.txt", 5, "global marine-surface"),
]


def data_rows(text: str) -> list[list[str]]:
    """Token lists of the non-comment, non-blank lines."""
    return [ln.split() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def file_created(text: str) -> str | None:
    """'# File Creation: Sat Sep  5 03:55:38 2026' -> '2026-09-05' (None if absent)."""
    for ln in text.splitlines():
        if ln.startswith("#") and "File Creation:" in ln:
            stamp = " ".join(ln.split("File Creation:", 1)[1].split())
            return str(dt.datetime.strptime(stamp, "%a %b %d %H:%M:%S %Y").date())
    return None


def src_note(fname: str, text: str) -> str:
    created = file_created(text)
    return f"{fname}, file created {created}" if created else fname


def parse_monthly(text: str, value_col: int = 3) -> list[tuple[str, str, list[str]]]:
    """[(YYYY-MM, value, tokens)] from a co2_mm_*.txt file."""
    out = []
    for t in data_rows(text):
        if Decimal(t[value_col]) >= 0:
            out.append((f"{int(t[0]):04d}-{int(t[1]):02d}", t[value_col], t))
    return out


def parse_annual(text: str) -> list[tuple[str, str]]:
    """[(YYYY, value)] from a co2_annmean_*.txt or co2_gr_*.txt file."""
    return [(t[0], t[1]) for t in data_rows(text) if Decimal(t[1]) >= 0]


def parse_daily(text: str, days: int = DAILY_DAYS) -> list[tuple[str, str]]:
    """[(YYYY-MM-DD, value)] for the last `days` days up to the file's latest date."""
    rows = [(dt.date(int(t[0]), int(t[1]), int(t[2])), t[4]) for t in data_rows(text) if Decimal(t[4]) >= 0]
    if not rows:
        return []
    last = max(d for d, _ in rows)
    return [(str(d), v) for d, v in rows if d > last - dt.timedelta(days=days)]


def trend(growth: list[tuple[str, str]], n: int) -> list[tuple[str, str, int]]:
    """[(final year, mean of the n consecutive growth rates ending there, first year)]."""
    by_year = {int(y): Decimal(v) for y, v in growth}
    out = []
    for end in sorted(by_year):
        window = range(end - n + 1, end + 1)
        if all(y in by_year for y in window):
            out.append((str(end), common.round_half_up(sum(by_year[y] for y in window) / n, 2), window[0]))
    return out


def monthly_flags(obs: str, tokens: list[str], last_obs: str, station_mlo: bool) -> list[str]:
    y, m = map(int, obs.split("-"))
    ly, lm = map(int, last_obs.split("-"))
    flags = []
    if station_mlo:
        if (y, m) < (1974, 5):
            flags.append("Scripps (SIO) measurements")
        elif Decimal(tokens[6]) < 0:
            flags.append("interpolated missing month")
        if (2022, 12) <= (y, m) <= (2023, 7):
            flags.append("measured at Maunakea during the Mauna Loa eruption outage")
    if (ly * 12 + lm) - (y * 12 + m) < 12:
        flags.append("preliminary (last 12 months, subject to recalibration)")
    return flags


def collect(fixture: str | None, today: dt.date, collector: str) -> list[dict]:
    reg = common.registry(SECTION)
    texts = {f: common.fetch(BASE + f, fixture) for f in (
        "co2_mm_mlo.txt", "co2_mm_gl.txt", "co2_annmean_mlo.txt", "co2_annmean_gl.txt",
        "co2_gr_mlo.txt", "co2_gr_gl.txt", "co2_daily_mlo.txt")}
    rows: list[dict] = []

    def add(metric, obs, value, fname, note):
        rows.append(common.row(reg, metric, obs, value, BASE + fname, note, collector, str(today)))

    for fname, metric, label, mlo in (("co2_mm_mlo.txt", "co2-mlo-monthly", "NOAA MLO monthly mean", True),
                                      ("co2_mm_gl.txt", "co2-global-monthly", "NOAA global marine-surface monthly mean", False)):
        parsed = parse_monthly(texts[fname])
        for obs, value, tokens in parsed:
            flags = monthly_flags(obs, tokens, parsed[-1][0], mlo)
            add(metric, obs, value, fname, "; ".join([f"{label} ({src_note(fname, texts[fname])})"] + flags))

    for fname, metric, label in (
            ("co2_annmean_mlo.txt", "co2-mlo-annual", "NOAA MLO calendar-year annual mean"),
            ("co2_annmean_gl.txt", "co2-global-annual", "NOAA global marine-surface calendar-year annual mean"),
            ("co2_gr_mlo.txt", "co2-growth-mlo-jan-dec", "NOAA MLO annual growth rate, Jan 1 -> Dec 31 change"),
            ("co2_gr_gl.txt", "co2-growth-global-jan-dec", "NOAA global marine-surface annual growth rate, Jan 1 -> Dec 31 change")):
        parsed = parse_annual(texts[fname])
        for obs, value in parsed:
            prelim = "; preliminary (last year of the file, subject to recalibration)" if obs == parsed[-1][0] else ""
            add(metric, obs, value, fname, f"{label} ({src_note(fname, texts[fname])}){prelim}")

    for obs, value in parse_daily(texts["co2_daily_mlo.txt"]):
        add("co2-mlo-daily", obs, value, "co2_daily_mlo.txt",
            f"NOAA MLO daily mean ({src_note('co2_daily_mlo.txt', texts['co2_daily_mlo.txt'])}); preliminary")

    for metric, fname, n, scope in TRENDS:
        for obs, value, first in trend(parse_annual(texts[fname]), n):
            add(metric, obs, value, fname,
                f"Derived by the collector: mean of the NOAA {scope} Jan->Dec annual growth rates "
                f"{first}-{obs} ({src_note(fname, texts[fname])}), rounded half-up to 2 decimals")
    return rows


if __name__ == "__main__":
    sys.exit(common.main(SECTION, __file__, collect))
