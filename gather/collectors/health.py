#!/usr/bin/env python3
"""Health KPI collector: WHO Global Health Observatory (GHO) HALE at birth -> staged observations.

Usage:  uv run gather/collectors/health.py --out FILE [--fixture DIR] [--today YYYY-MM-DD]

Source: GHO OData API, indicator WHOSIS_000002 "Healthy life expectancy (HALE) at
birth (years)", https://ghoapi.azureedge.net/api/WHOSIS_000002 (WHO Global Health
Estimates, GHE).  One JSON document {"value": [record, ...]}; each record has
  SpatialDimType  COUNTRY | REGION (WHO regions) | WORLDBANKINCOMEGROUP | GLOBAL
  SpatialDim      ISO3 code / region code / 'GLOBAL'
  Dim1            SEX_BTSX (both sexes) | SEX_MLE | SEX_FMLE
  TimeDim         the year (TimeDimType YEAR)
  Value           display string '73.6 [72.8-74.5]' (point estimate [95% UI], 1 decimal)
  NumericValue    unrounded point estimate
  Date            GHO timestamp of the record's (last) upload, e.g. 2024-08-02T10:11:00+02:00
With --fixture DIR the document is read from DIR/who_hale.json.

Metrics:
  hale-median-country  median of NumericValue over the COUNTRY records, both sexes,
                       per year (unweighted; even count = mean of the two middle
                       values), exact decimal arithmetic on the unrounded estimates,
                       rounded half-up to 1 decimal (WHO's own display precision).
                       The note gives the number of countries.
  hale-global          the GLOBAL both-sexes record (WHO's population-weighted global
                       HALE), the point estimate of its display Value, verbatim.

Choices:
  - published: the record's GHO Date (basis 'source'; for the median, the latest
    Date of the records it uses).  It is when WHO loaded the value into the GHO, an
    upper bound of its release (GHE rounds are published as a batch, often first in
    the World Health Statistics report); a re-upload of an unchanged value dedups
    on merge, a changed value is a revision dated by its own upload.  A record
    without a usable Date falls back to basis 'seen' (published = retrieved).
  - The API does not name the GHE release; notes give the series span
    (e.g. 2000-2021, i.e. the GHE round ending in 2021) and the GHO record date.
  - Data-error guards: a paged/truncated answer (@odata.nextLink) or a duplicated
    (place, sex, year) record is an error; a year whose country count is below
    MIN_COVERAGE_RATIO x the best-covered year is skipped with a warning.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from decimal import Decimal

import common

SECTION = "health"
URL = "https://ghoapi.azureedge.net/api/WHOSIS_000002"
FIXTURE = "who_hale.json"
BOTH_SEXES = "SEX_BTSX"
MIN_COVERAGE_RATIO = 0.7
M_MEDIAN = "hale-median-country"
M_GLOBAL = "hale-global"


def fetch(fixture: str | None) -> str:
    if fixture:
        with open(os.path.join(fixture, FIXTURE), encoding="utf-8") as f:
            return f.read()
    return common.fetch(URL)


def parse(text: str) -> list[dict]:
    """GHO OData answer -> [{kind, place, sex, year, value (Decimal), display, date}]."""
    d = json.loads(text)
    if not isinstance(d, dict) or not isinstance(d.get("value"), list) or not d["value"]:
        raise ValueError("GHO answer without records")
    if d.get("@odata.nextLink"):
        raise ValueError("GHO answer is paged (@odata.nextLink); refusing a partial series")
    out, seen = [], set()
    for r in d["value"]:
        if r.get("IndicatorCode") != "WHOSIS_000002" or r.get("TimeDimType") != "YEAR" \
                or r.get("Dim1Type") != "SEX" or r.get("NumericValue") is None:
            continue
        key = (r["SpatialDimType"], r["SpatialDim"], r["Dim1"], int(r["TimeDim"]))
        if key in seen:
            raise ValueError(f"duplicate GHO record {key}")
        seen.add(key)
        date = (r.get("Date") or "")[:10]
        try:
            dt.date.fromisoformat(date)
        except ValueError:
            date = None
        out.append({"kind": key[0], "place": key[1], "sex": key[2], "year": key[3],
                    "value": Decimal(str(r["NumericValue"])), "display": r.get("Value") or "",
                    "date": date})
    return out


def median(values: list[Decimal]) -> Decimal:
    s = sorted(values)
    n = len(s)
    if not n:
        raise ValueError("median of nothing")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def display_point(rec: dict) -> str:
    """'61.9 [61.0-62.7]' -> '61.9'; falls back to the rounded NumericValue."""
    head = rec["display"].split("[", 1)[0].strip()
    try:
        Decimal(head)
        return head
    except ArithmeticError:
        return common.round_half_up(rec["value"], 1)


def country_medians(recs: list[dict], warnings: list[str]) -> list[tuple[int, Decimal, int, str | None]]:
    """[(year, median, n countries, latest record date)] over COUNTRY both-sexes records."""
    by_year: dict[int, list[dict]] = {}
    for r in recs:
        if r["kind"] == "COUNTRY" and r["sex"] == BOTH_SEXES:
            by_year.setdefault(r["year"], []).append(r)
    if not by_year:
        return []
    best = max(len(v) for v in by_year.values())
    out = []
    for year, rs in sorted(by_year.items()):
        if len(rs) < MIN_COVERAGE_RATIO * best:
            warnings.append(f"{year}: only {len(rs)} countries (best year: {best}); median not emitted")
            continue
        dates = [r["date"] for r in rs if r["date"]]
        out.append((year, median([r["value"] for r in rs]), len(rs),
                    max(dates) if len(dates) == len(rs) else None))
    return out


def collect(fixture: str | None, today: dt.date, collector: str, existing=()) -> list[dict]:
    reg = common.registry(SECTION)
    recs = parse(fetch(fixture))
    years = sorted({r["year"] for r in recs})
    span = f"{years[0]}-{years[-1]}"
    warnings: list[str] = []
    rows: list[dict] = []

    def add(metric, year, value, date, note):
        published = date if date and date <= str(today) else None
        note += f"; published = GHO record date {date}" if published else "; no GHO record date, published = first seen"
        rows.append(common.row(reg, metric, str(year), value, URL, note, collector, str(today), published=published))

    for year, med, n, date in country_medians(recs, warnings):
        add(M_MEDIAN, year, common.round_half_up(med, 1), date,
            f"Derived: median across {n} countries of WHO GHE HALE at birth, both sexes "
            f"(GHO WHOSIS_000002, COUNTRY, {BOTH_SEXES}), unweighted, from the unrounded estimates "
            f"({med.normalize()}), rounded half-up to 1 decimal; GHE series {span}")

    for r in sorted((r for r in recs if r["kind"] == "GLOBAL" and r["sex"] == BOTH_SEXES), key=lambda r: r["year"]):
        add(M_GLOBAL, r["year"], display_point(r), r["date"],
            f"WHO GHE global HALE at birth, both sexes (GHO WHOSIS_000002, GLOBAL, {BOTH_SEXES}; "
            f"'{r['display']}' = estimate [95% UI]); GHE series {span}")

    for w in warnings:
        print(f"  WARNING {w}", file=sys.stderr)
    return rows


if __name__ == "__main__":
    sys.exit(common.main(SECTION, __file__, collect))
