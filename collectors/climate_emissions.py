#!/usr/bin/env python3
"""Climate emissions collector: Global Carbon Budget global budget xlsx -> staged observations.

Usage:  uv run collectors/climate_emissions.py --out FILE [--fixture DIR] [--today YYYY-MM-DD]
(also run by collectors/climate.py, i.e. by `collectors/run.sh climate`).

Source: the Global Carbon Budget's own global budget spreadsheet, linked as
"Global Carbon Budget v<YEAR> [xlsx]" on https://globalcarbonbudget.org/datahub/
(the-latest-gcb-data-<YEAR>/), served by DATA_URL with a Content-Disposition
filename such as Global_Carbon_Budget_2025_v0.6.xlsx (that filename = the vintage,
quoted in every note). Bump DATA_URL when a new budget is released (each November).
The xlsx is parsed with the stdlib only (zipfile + xml.etree); sheet
"Global Carbon Budget", one row per calendar year 1959..last final year, in GtC/yr:
  fossil emissions excluding carbonation (E_FOS gross: fossil fuels + cement process
  emissions, i.e. fossil fuel combustion and industrial processes), land-use change
  emissions (E_LUC, net), cement carbonation sink (S_CEMENT), ...

Metrics (registry metrics/climate.csv, GtCO2, obs = calendar year):
  co2-emissions-fossil-gcb  = (E_FOS_gross - S_CEMENT) * 3.664
      GCB's headline fossil CO2 "includes the cement carbonation sink" (GCB 2025 key
      messages), i.e. net of carbonation = the registry definition.
  co2-emissions-total-gcb   = (E_FOS_gross - S_CEMENT + E_LUC) * 3.664
      GCB's "total anthropogenic CO2 emissions - the sum of fossil and land-use change".
Choices:
  - 3.664 GtCO2/GtC is the factor the sheet itself states; exact decimal arithmetic on the
    file's values, rounded half-up to 2 decimals (GCB headlines round to 0.1 GtCO2; two
    decimals keep consecutive years distinguishable for a peak tracker, far below the
    source's +-5 % (fossil) / +-0.7 GtC (land use) 1-sigma uncertainty).
  - Only final years are in the file; GCB's current-year projection (e.g. 2025 in GCB 2025)
    is published in the paper/key messages only and is not emitted here.
  - published: neither the file nor its download page states a release date -> basis seen
    (published = retrieved, an upper bound).
  - Notes cite the vintage and the inputs; where the ledger's effective value (e.g. a paper's
    rounded figure) differs, the note says whether it agrees at that value's precision.
"""
from __future__ import annotations

import datetime as dt
import glob
import io
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal

import common

SECTION = "climate"
DATA_URL = "https://globalcarbonbudget.org/download/2341/"
SHEET = "Global Carbon Budget"
FILE_RE = re.compile(r"^Global_Carbon_Budget_(\d{4})_v[\w.]+\.xlsx$")
GTC_TO_GTCO2 = Decimal("3.664")
COL_FOS, COL_LUC, COL_CEM = ("fossil emissions excluding carbonation", "land-use change emissions",
                             "cement carbonation sink")
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def fetch_xlsx(fixture: str | None) -> tuple[str, bytes]:
    """(filename, bytes) of the budget xlsx: Content-Disposition name online, or the single
    Global_Carbon_Budget_<year>_v*.xlsx in the fixture dir."""
    if fixture:
        names = [os.path.basename(p) for p in glob.glob(os.path.join(fixture, "Global_Carbon_Budget_*.xlsx"))]
        names = [n for n in names if FILE_RE.match(n)]
        if len(names) != 1:
            raise SystemExit(f"climate_emissions: need exactly one Global_Carbon_Budget_<year>_v*.xlsx in {fixture}, got {names}")
        with open(os.path.join(fixture, names[0]), "rb") as f:
            return names[0], f.read()
    req = urllib.request.Request(DATA_URL, headers={"User-Agent": common.USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r:
        name, data = r.headers.get_filename() or "", r.read()
    if not FILE_RE.match(name):
        raise SystemExit(f"climate_emissions: {DATA_URL} served {name!r}, not a Global_Carbon_Budget_<year>_v*.xlsx")
    return name, data


def col_row(ref: str) -> tuple[str, int]:
    m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    if not m:
        raise SystemExit(f"climate_emissions: bad cell reference {ref!r}")
    return m.group(1), int(m.group(2))


def read_sheet(data: bytes, name: str) -> dict[int, dict[str, str]]:
    """{row number: {column letter: cell text}} of sheet `name` (shared/inline strings resolved)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
    rels = {e.get("Id"): e.get("Target") for e in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    target = None
    for s in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", NS):
        if s.get("name") == name:
            target = rels[s.get(RID)]
    if target is None:
        raise SystemExit(f"climate_emissions: no sheet {name!r} in the workbook")
    path = target.lstrip("/") if target.startswith("/") else "xl/" + target
    out: dict[int, dict[str, str]] = {}
    for c in ET.fromstring(z.read(path)).iter(f"{{{NS['m']}}}c"):
        col, rown = col_row(c.get("r"))
        v, t = c.find("m:v", NS), c.get("t")
        if t == "inlineStr":
            text = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
        elif v is None or v.text is None:
            continue
        else:
            text = shared[int(v.text)] if t == "s" else v.text
        if text.strip():
            out.setdefault(rown, {})[col] = text.strip()
    return out


def parse_budget(data: bytes) -> list[tuple[str, Decimal, Decimal, Decimal]]:
    """[(year, E_FOS gross, E_LUC, S_CEMENT)] in GtC/yr from the 'Global Carbon Budget' sheet.
    Fails loudly if the layout or the stated unit / conversion factor changed."""
    cells = read_sheet(data, SHEET)
    text = " ".join(v for r in cells.values() for v in r.values())
    if "GtC/yr" not in text or "3.664" not in text:
        raise SystemExit("climate_emissions: sheet no longer states GtC/yr and the 3.664 GtCO2/GtC factor")
    hdr = next((n for n in sorted(cells) if cells[n].get("A") == "Year"), None)
    if hdr is None or cells.get(hdr - 1, {}).get("A") != "GtC/yr":
        raise SystemExit("climate_emissions: 'Year' header row (under a 'GtC/yr' unit cell) not found")
    cols = {v: k for k, v in cells[hdr].items()}
    missing = [h for h in (COL_FOS, COL_LUC, COL_CEM) if h not in cols]
    if missing:
        raise SystemExit(f"climate_emissions: header columns missing: {missing}")
    out = []
    for n in sorted(k for k in cells if k > hdr):
        r = cells[n]
        if not re.fullmatch(r"\d{4}", r.get("A", "")):
            continue
        vals = [r.get(cols[h]) for h in (COL_FOS, COL_LUC, COL_CEM)]
        if None in vals:
            raise SystemExit(f"climate_emissions: year {r['A']} lacks a value in {(COL_FOS, COL_LUC, COL_CEM)}")
        out.append((r["A"], *(Decimal(v) for v in vals)))
    if not out:
        raise SystemExit("climate_emissions: no year rows under the header")
    return out


def to_gtco2(gtc: Decimal) -> str:
    return common.round_half_up(gtc * GTC_TO_GTCO2, 2)


def series(budget) -> list[tuple[str, str, str, str]]:
    """[(metric, year, GtCO2 value, derivation)] for the fossil (net of carbonation) and total series."""
    out = []
    for year, fos, luc, cem in budget:
        out.append(("co2-emissions-fossil-gcb", year, to_gtco2(fos - cem),
                    f"({fos:.4f} fossil excl. carbonation - {cem:.4f} cement carbonation sink) GtC x 3.664"))
        out.append(("co2-emissions-total-gcb", year, to_gtco2(fos - cem + luc),
                    f"({fos:.4f} fossil excl. carbonation - {cem:.4f} cement carbonation sink"
                    f" + {luc:.4f} land-use change) GtC x 3.664"))
    return out


def ledger_note(value: str, eff: dict | None) -> str:
    """Audit note vs the effective ledger row (e.g. a paper's 1-decimal headline figure)."""
    if eff is None or Decimal(eff["value"]) == Decimal(value):
        return ""
    prec = Decimal(eff["value"])
    agree = Decimal(value).quantize(Decimal(1).scaleb(prec.as_tuple().exponent)) == prec
    return (f"; effective ledger value {eff['value']} (published {eff['published']}) "
            + ("agrees at its precision" if agree else "DIFFERS beyond rounding"))


def collect(fixture: str | None, today: dt.date, collector: str, existing=()) -> list[dict]:
    reg = common.registry(SECTION)
    fname, data = fetch_xlsx(fixture)
    vintage = f"GCB {FILE_RE.match(fname).group(1)}"
    effective = common.ledger.obs_as_of("", rows=list(existing))
    rows = []
    for metric, year, value, how in series(parse_budget(data)):
        label = "fossil CO2 net of the cement carbonation sink" if metric.endswith("fossil-gcb") \
            else "total anthropogenic CO2 (fossil net of cement carbonation + net land-use change)"
        note = (f"{vintage} global {label}, calendar year ({fname}, sheet '{SHEET}'): {how},"
                f" rounded half-up to 2 decimals" + ledger_note(value, effective.get((metric, year))))
        rows.append(common.row(reg, metric, year, value, DATA_URL, note, collector, str(today)))
    return rows


if __name__ == "__main__":
    sys.exit(common.main(SECTION, __file__, collect))
