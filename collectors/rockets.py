#!/usr/bin/env python3
"""Rockets KPI collector: Jonathan's Space Report annual payload tonnage -> payload-mass-to-orbit.

Usage:  uv run collectors/rockets.py --out FILE [--fixture DIR] [--today YYYY-MM-DD]

Source: https://planet4589.org/space/stats/out/msatannual.txt (J. McDowell, JSR).
Format: one '#' header line naming the columns, then whitespace-separated rows
    # Bin     YDate   USSR   USA   PRC   EUR   OTHER   UNK   Total
         69   2025    61.1  2712.0 315.9  40.9  64.2    0.0  3194.0
         71   Total  11931.9 ...                                (all-time row)
Values are payload tonnage (metric tonnes) by launching state; the companion
msatannual.par labels them "Total payload tonnage".

Choices:
  - value = the 'Total' column, copied verbatim (1 decimal, tonnes).
  - Only complete calendar years are emitted: obs year < the retrieval year,
    and the registry's release lag has passed since Dec 31 (late-catalogued
    launches). The file's current-year row is a running year-to-date total and
    must never become an annual value; the all-time 'Total' row is skipped.
  - published: registry release_lag_days rule (JSR updates continuously; the
    file states no publication date).
"""
from __future__ import annotations

import datetime as dt
import sys

import common

SECTION = "rockets"
URL = "https://planet4589.org/space/stats/out/msatannual.txt"
METRIC = "payload-mass-to-orbit"


def parse(text: str) -> list[tuple[int, str]]:
    """[(year, total tonnes)] for every year row of msatannual.txt (incl. a partial current year)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    header = next((ln.lstrip("#").split() for ln in lines if ln.startswith("#") and "YDate" in ln), [])
    if "YDate" not in header or "Total" not in header:
        raise SystemExit(f"{URL}: unexpected header {header} (need YDate and Total columns)")
    iy, it = header.index("YDate"), header.index("Total")
    out = []
    for ln in lines:
        t = ln.split()
        if ln.startswith("#") or not t[iy].isdigit():
            continue  # header / all-time Total row
        if len(t) != len(header):
            raise SystemExit(f"{URL}: row has {len(t)} columns, header has {len(header)}: {ln!r}")
        out.append((int(t[iy]), t[it]))
    return out


def collect(fixture: str | None, today: dt.date, collector: str, existing=()) -> list[dict]:
    reg = common.registry(SECTION)
    lag = dt.timedelta(days=int(reg[METRIC]["release_lag_days"] or 0))
    return [common.row(reg, METRIC, str(year), value, URL,
                       "JSR msatannual total payload tonnage launched, all launching states (complete calendar year)",
                       collector, str(today))
            for year, value in parse(common.fetch(URL, fixture))
            if year < today.year and dt.date(year, 12, 31) + lag <= today]


if __name__ == "__main__":
    sys.exit(common.main(SECTION, __file__, collect))
