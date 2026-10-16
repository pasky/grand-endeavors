#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Rockets collector: the KPI (cost-to-leo-best-real) and the Deluge series (payload-mass-to-orbit).

Usage:  uv run gather/collectors/rockets.py --out FILE [--fixture DIR] [--today YYYY-MM-DD]

payload-mass-to-orbit
  Source: https://planet4589.org/space/stats/out/msatannual.txt (J. McDowell, JSR).
  Format: one '#' header line naming the columns, then whitespace-separated rows
      # Bin     YDate   USSR   USA   PRC   EUR   OTHER   UNK   Total
           69   2025    61.1  2712.0 315.9  40.9  64.2    0.0  3194.0
           71   Total  11931.9 ...                                (all-time row)
  Values are payload tonnage (metric tonnes) by launching state; the companion
  msatannual.par labels them "Total payload tonnage".
  - value = the 'Total' column, copied verbatim (1 decimal, tonnes).
  - Only complete calendar years are emitted: obs year < the retrieval year,
    and the registry's release lag has passed since Dec 31 (late-catalogued
    launches). The file's current-year row is a running year-to-date total and
    must never become an annual value; the all-time 'Total' row is skipped.
  - published: registry release_lag_days rule (JSR updates continuously; the
    file states no publication date).

cost-to-leo-best-real (THE rockets KPI; owner decisions 2026-10-16)
  The lowest price per kg to LEO of a dedicated launch among the rockets in service
  in the obs year, in constant BASE_YEAR US$ ("can I get my stuff to orbit cheaply").
  No source publishes this series; it is derived from:
  LIST  the ledger's list-price-<rocket> ($M) and list-leo-kg-<rocket> (kg) observations
        (LISTED): the provider's published standard price in force on 1 July of the
        year and the LEO capacity published with it.  SpaceX 2010-2025 was backfilled
        from Wayback captures (one cited capture per row); new prices (or a new rocket's
        first price) enter through verified gather intake like any observation.
  CSIS  https://ourworldindata.org/grapher/cost-space-launches-low-earth-orbit.csv
        CSIS Aerospace Security Project, "Space Launch to Low Earth Orbit: How Much
        Does It Cost?" (https://aerospace.csis.org/data/space-launch-to-low-earth-orbit-how-much-does-it-cost/,
        last updated 2022-09-01), via Our World in Data: one $/kg per rocket (CSIS's
        estimate of a dedicated launch at its first successful orbital launch / full
        LEO payload, FY2021 $), with the year of that first success; 60 rockets,
        1962-2019.  Used for the rockets without list prices (a fixed figure each).
  GCAT  https://planet4589.org/space/gcat/tsv/launch/launch.tsv (J. McDowell, JSR):
        every launch with its LV_Type and LaunchCode; orbital (O*) and deep-space
        (D*) attempts, any outcome, give each rocket's years in service.
  CPI   BLS CPI-U annual averages (common.BLS_CPI).
  Choices:
  - A listed rocket's $/kg in year Y = list price / LEO kg of Y, deflated with
    CPI(Y).  A year without a list row (the price page dropped the rocket: Falcon
    Heavy from 2023, all SpaceX prices from 2026) holds the last listed year's real
    value: SpaceX states its price changes track inflation, and a rocket that keeps
    flying stays buyable.  Dropping it instead would fake a jump (2023: Falcon 9,
    twice Falcon Heavy's $/kg) and end the series when the page went away.
  - The basis is the published one: a dedicated launch, full (from 2016 fully
    expendable) LEO capacity.  Rideshare (a slot, not a rocket) is the side series
    rideshare-price-per-kg-spacex(-real), not a KPI candidate.
  - Rockets without list prices: the CSIS figure, FY2021 $ -> BASE_YEAR $ with CPI
    (CSIS inflated to FY2021 with the GDP deflator; the CPI step only rebases).
  - A rocket is in service from its first successful launch (CSIS's year; GCAT's
    for EXTRA_LV rockets CSIS does not cover) through the last year one of its GCAT
    LV_Types launched; one that launched within ACTIVE_YEARS before the retrieval
    year is still in service (Falcon Heavy flies every year or two).
  - value = min real $/kg over the rockets in service, whole dollars; the note
    names the rocket and its inputs.
  - The mapping is reviewed, so drift fails the run: a CSIS rocket without a
    CSIS_LV entry, a CSIS_LV rocket missing from the CSIS data (a truncated export
    would silently raise the minimum), a mapped LV_Type absent from GCAT, an active
    unmapped GCAT LV_Type named like a mapped one (a rename or new variant; reviewed
    exceptions in GCAT_NOT_CSIS), a list price without its LEO capacity (or vice
    versa).
  - Spans depend on the retrieval year (the ACTIVE_YEARS grace) and inputs get
    revised, so a later run can change a year's value: a revision, dated first seen
    (input dates only date values equal to the effective ledger row).  A ledger
    year the run no longer derives fails the run (withdraw it explicitly).
  - A list-price gap between two listed years fails the run (missed intake, not a
    delisting); only the years after a rocket's last listed one are held.
  - Adding a rocket (Starship, New Glenn, Neutron ... once a provider publishes a
    dedicated-launch price with its LEO capacity): register list-price-<slug> and
    list-leo-kg-<slug> (copy the Falcon definitions), add it to LISTED, and to
    EXTRA_LV with its GCAT LV_Types when CSIS lacks it; intake then stages its rows.
    SpaceX's price PDF is 404 since 2025-08: a successor page would feed the same
    metrics.  A new OWID/CSIS vintage fails the run on any unmapped rocket: extend
    CSIS_LV.
  - Only complete years past the release lag are emitted.  published: the rule date
    (Dec 31 + lag, when CPI(Y) is out), but not before CSIS_UPDATED or the
    publication of the list rows used (basis 'source').  As in fusion.py, the dates
    describe the underlying prices: rebasing to BASE_YEAR $ is not a publication
    input (CPI(BASE_YEAR) itself appears in January of the following year).

rideshare-price-per-kg-spacex: from 2026 spacex.com/rideshare shows no prices; its booking
  app reads them from RIDE_API (pricingMenus: US cents per kg by launch year).  Emits the
  years up to the current one (later years are announced, not yet in force), basis seen;
  2020-2025 were backfilled from page captures (the API's 2023-2025 agree).
rideshare-price-per-kg-spacex-real: each year's nominal rideshare price per kg (ledger,
  or this run's RIDE_API value), deflated with CPI(Y) to BASE_YEAR $ (same publication rule).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import sys
from decimal import Decimal

import common
import ledger  # noqa: E402 (core/ on sys.path via common)

SECTION = "rockets"
URL = "https://planet4589.org/space/stats/out/msatannual.txt"
METRIC = "payload-mass-to-orbit"

M_COST = "cost-to-leo-best-real"
CSIS_URL = "https://ourworldindata.org/grapher/cost-space-launches-low-earth-orbit.csv"
CSIS_COLUMNS = ("Entity", "Year", "Launch cost per kilogram of payload")
CSIS_UPDATED = "2022-09-01"  # CSIS page dateModified (the FY21 $ dataset)
GCAT_URL = "https://planet4589.org/space/gcat/tsv/launch/launch.tsv"
ACTIVE_YEARS = 3
BASE_YEAR = 2025      # constant-$ base of the real series (= the fusion KPI's)
CSIS_DOLLARS = 2021   # CSIS figures are FY2021 $
# Rockets whose published list prices (ledger: list-price-<slug> $M + list-leo-kg-<slug> kg) price them.
LISTED = {"Falcon 9": "falcon-9", "Falcon Heavy": "falcon-heavy"}
# GCAT LV_Types of LISTED rockets CSIS does not cover (in service from their first successful launch).
EXTRA_LV: dict[str, list[str]] = {}
M_RIDE = "rideshare-price-per-kg-spacex"
M_RIDE_REAL = "rideshare-price-per-kg-spacex-real"
RIDE_API = "https://api-rideshare.spacex.com/api/v2/price"

# CSIS rocket (OWID entity) -> the GCAT LV_Types that are that rocket (its variants
# sharing the priced configuration's family).
CSIS_LV = {
    "Angara": ["Angara A5", "Angara A5/Persei", "Angara A5/Orion"],
    "Antares": ["Antares 110", "Antares 120", "Antares 130", "Antares 230", "Antares 230+"],
    "Ariane 44": ["Ariane 40", "Ariane 42L", "Ariane 42P", "Ariane 44L", "Ariane 44LP", "Ariane 44P"],
    "Ariane 5G": ["Ariane 5G", "Ariane 5G+", "Ariane 5GS"],
    "Athena 1": ["Athena-1"],
    "Atlas Centaur": ["Atlas Centaur", "Atlas Centaur D", "Atlas SLV-3C Centaur", "Atlas SLV-3D Centaur",
                      "Atlas G Centaur"],
    "Atlas II": ["Atlas II", "Atlas IIA", "Atlas IIAS"],
    "Atlas III": ["Atlas 3A", "Atlas 3B"],
    "Atlas V": ["Atlas V 401", "Atlas V 411", "Atlas V 421", "Atlas V 431", "Atlas V 501", "Atlas V 511",
                "Atlas V 521", "Atlas V 531", "Atlas V 541", "Atlas V 551", "Atlas V N22"],
    "Delta 3000-Series": ["Delta 3910", "Delta 3910/PAM", "Delta 3913", "Delta 3914", "Delta 3920",
                          "Delta 3920/PAM", "Delta 3920-8", "Delta 3924"],
    "Delta 3910": ["Delta 3910", "Delta 3910/PAM"],
    "Delta E": ["Thor Delta E", "Thor Delta E1"],
    "Delta II": ["Delta 6920-8", "Delta 6920-10", "Delta 6925", "Delta 6925-8", "Delta 7320-10",
                 "Delta 7320-10C", "Delta 7326-9.5", "Delta 7420-10C", "Delta 7920-10", "Delta 7920-10C",
                 "Delta 7920-10L", "Delta 7920H", "Delta 7925", "Delta 7925-8", "Delta 7925-9.5",
                 "Delta 7925-10"],
    "Delta III": ["Delta 8930"],
    "Delta IV": ["Delta 4M", "Delta 4M+(4,2)", "Delta 4M+(5,2)", "Delta 4M+(5,4)"],
    "Delta IV Heavy": ["Delta 4H"],
    "Dnepr": ["Dnepr"],
    "Electron": ["Electron"],
    "Epsilon": ["Epsilon"],
    "Falcon 1": ["Falcon 1"],
    "Falcon 9": ["Falcon 9"],
    "Falcon Heavy": ["Falcon Heavy"],
    "GSLV": ["GSLV Mk I", "GSLV Mk II"],
    "H-II": ["H-II", "H-IIA 202", "H-IIA 2022", "H-IIA 2024", "H-IIA 204", "H-IIB"],  # CSIS counts the family
    "Kosmos": ["Kosmos 63S1", "Kosmos 65S3", "Kosmos 11K63", "Kosmos 11K65", "Kosmos 11K65M"],
    "Kuaizhou": ["Kuaizhou", "Kuaizhou-1A"],
    "LVM3": ["GSLV Mk III", "LVM3"],
    "Long March 11": ["Chang Zheng 11"],
    "Long March 2A": ["Chang Zheng 2"],  # GCAT files the 1976-78 flights as CZ-2C (CSIS: 1982); never the minimum
    "Long March 2C": ["Chang Zheng 2C", "Chang Zheng 2C-III/SD", "Chang Zheng 2C/YZ-1S"],
    "Long March 2D": ["Chang Zheng 2D", "Chang Zheng 2D/YZ-3"],
    "Long March 2E": ["Chang Zheng 2E"],
    "Long March 3A": ["Chang Zheng 3A"],
    "Long March 3B": ["Chang Zheng 3B", "Chang Zheng 3B/YZ-1"],
    "Long March 4B": ["Chang Zheng 4B"],
    "Long March 5": ["Chang Zheng 5", "Chang Zheng 5/YZ-2", "Chang Zheng 5B", "Chang Zheng 5B/YZ-2"],
    "M-V": ["M-V"],
    "Minotaur I": ["Minotaur I"],
    "Minotaur IV": ["Minotaur IV", "Minotaur IV+"],
    "PSLV": ["PSLV", "PSLV-XL", "PSLV-DL", "PSLV-QL"],
    "Pegasus": ["Pegasus", "Pegasus/HAPS", "Pegasus H"],
    "Pegasus XL": ["Pegasus XL", "Pegasus XL/HAPS"],
    "Proton": ["UR-500", "Proton-K", "Proton-K/D", "Proton-K/D-1", "Proton-K/D-2", "Proton-K/DM",
               "Proton-K/DM-2", "Proton-K/DM-2M", "Proton-K/17S40", "Proton-K/Briz-M", "Proton-M",
               "Proton-M/Briz-M", "Proton-M/DM-2", "Proton-M/DM-3"],
    "R-36 / Cyclone": ["R-36O 8K69", "R-36O 8K69M", "Tsiklon-2A", "Tsiklon-2", "Tsiklon-3"],
    "Rokot": ["Rokot"],
    "Saturn V": ["Saturn V"],
    "Scout": ["Scout A", "Scout A-1", "Scout B", "Scout B-1", "Scout D-1", "Scout E-1", "Scout F-1",
              "Scout G-1"],
    "Shavit": ["Shavit", "Shavit 1", "Shavit 2"],
    "Shian Quxian": ["Shuang Quxian 1"],  # CSIS's spelling of Hyperbola-1 (iSpace)
    "Shtil": ["Shtil'-1"],
    "Soyuz": ["Soyuz 11A511", "Soyuz 11A511L", "Soyuz 11A511M", "Soyuz-U", "Soyuz-U-PVB", "Soyuz-U2",
              "Soyuz-FG", "Soyuz-2-1A", "Soyuz-2-1B", "Soyuz-2-1V", "Soyuz-ST-A", "Soyuz-ST-B"],
    "Space Shuttle": ["Space Shuttle"],
    "Start": ["Start", "Start-1", "Start-1.2"],
    "Strela": ["Strela"],
    "Taurus": ["ARPA Taurus", "Taurus 1110", "Taurus 2110", "Taurus 2210", "Taurus 3110", "Taurus 3210"],
    "Titan II": ["Titan II GLV", "Titan II SLV"],
    "Titan III+": ["Titan IIIA", "Titan IIIB", "Titan IIIC", "Titan IIID", "Titan IIIE", "Titan 23B",
                   "Titan 24B", "Titan 33B", "Titan 34B", "Titan 34D", "Titan 34D/IUS", "Titan 34D/Transtage",
                   "Commercial Titan 3"],
    "Titan IV": ["Titan 401A/Centaur", "Titan 401B/Centaur", "Titan 402A/IUS", "Titan 402B/IUS", "Titan 403A",
                 "Titan 403B", "Titan 404A", "Titan 404B", "Titan 405A", "Titan 405B"],
    "Vega": ["Vega"],
    "Zenit 2": ["Zenit-2", "Zenit-2 11K77.05", "Zenit-2M", "Zenit-2SB"],
    "Zenit 3SL": ["Zenit-3SL", "Zenit-3SLB", "Zenit-3SLBF"],
}


# Active GCAT LV_Types named like a mapped one that are NOT that CSIS rocket (reviewed).
GCAT_NOT_CSIS = {
    "Chang Zheng 2F": "crewed Shenzhou launcher, not CZ-2A",
    "Kuaizhou-11": "a larger rocket than Kuaizhou(-1A)",
    "Vega C": "a new rocket (2022) CSIS does not price",
}


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


def parse_csis(text: str) -> dict[str, tuple[int, str]]:
    """{rocket: (year of first successful launch, FY2021 $/kg as published)} from the OWID CSV."""
    rd = csv.DictReader(io.StringIO(text))
    if not set(CSIS_COLUMNS) <= set(rd.fieldnames or ()):
        raise SystemExit(f"{CSIS_URL}: unexpected header {rd.fieldnames} (need {list(CSIS_COLUMNS)})")
    out = {}
    for r in rd:
        name, year, cost = (r[c].strip() for c in CSIS_COLUMNS)
        if not year.isdigit() or not cost.isdigit() or name in out:
            raise SystemExit(f"{CSIS_URL}: bad or duplicate row {r}")
        out[name] = (int(year), cost)
    if not out:
        raise SystemExit(f"{CSIS_URL}: no rows")
    return out


def parse_gcat(text: str) -> dict[str, tuple[int | None, int]]:
    """{LV_Type: (first year of a successful orbital/deep-space launch or None, last year of an
    orbital or deep-space launch attempt)} from GCAT launch.tsv."""
    lines = text.splitlines()
    header = lines[0].lstrip("#").split("\t") if lines else []
    if not {"Launch_Date", "LV_Type", "LaunchCode"} <= set(header):
        raise SystemExit(f"{GCAT_URL}: unexpected header {header[:8]} (need Launch_Date, LV_Type, LaunchCode)")
    idate, ilv, icode = header.index("Launch_Date"), header.index("LV_Type"), header.index("LaunchCode")
    out: dict[str, tuple[int | None, int]] = {}
    for ln in lines[1:]:
        if ln.startswith("#"):
            continue
        f = ln.split("\t")
        if len(f) <= max(idate, ilv, icode):
            raise SystemExit(f"{GCAT_URL}: short row {ln[:80]!r}")
        code = f[icode].strip()
        if code[:1] not in ("O", "D"):
            continue  # suborbital, missile, atmospheric ... (not an orbital-class launch)
        if not f[idate][:4].isdigit():
            raise SystemExit(f"{GCAT_URL}: bad Launch_Date {f[idate]!r}")
        lv, y = f[ilv].strip(), int(f[idate][:4])
        first, last = out.get(lv, (None, y))
        if code[1:2] == "S":
            first = y if first is None else min(first, y)
        out[lv] = (first, max(last, y))
    if not out:
        raise SystemExit(f"{GCAT_URL}: no orbital launches")
    return out


def service_years(csis: dict[str, tuple[int, str]], gcat: dict[str, tuple[int | None, int]],
                  today: dt.date) -> dict[str, tuple[int, int, int]]:
    """{rocket: (first, last year in service, last GCAT launch year)} for the CSIS rockets and EXTRA_LV;
    a rocket that launched within ACTIVE_YEARS before today's year is in service through last year."""
    lvmap = {**CSIS_LV, **EXTRA_LV}
    unmapped = sorted(set(csis) - set(CSIS_LV))
    dropped = sorted(set(CSIS_LV) - set(csis))
    missing = sorted({lv for v in lvmap if v in csis or v in EXTRA_LV for lv in lvmap[v] if lv not in gcat})
    mapped = {lv for lvs in lvmap.values() for lv in lvs}
    variants = sorted(f"{lv} (~{m})" for lv, (_, y) in gcat.items()
                      if y >= today.year - ACTIVE_YEARS and lv not in mapped and lv not in GCAT_NOT_CSIS
                      for m in [next((m for m in sorted(mapped, key=len, reverse=True) if lv.startswith(m)), None)]
                      if m)
    unpriced = sorted(set(EXTRA_LV) - set(LISTED))
    if unmapped or dropped or missing or variants or unpriced:
        raise SystemExit(f"rockets: CSIS rockets without a GCAT mapping (CSIS_LV): {unmapped}; "
                         f"CSIS_LV rockets missing from the CSIS data (truncated export?): {dropped}; "
                         f"mapped LV_Types with no orbital launch in GCAT: {missing}; "
                         f"active unmapped GCAT LV_Types named like a mapped one (a rename or new variant? "
                         f"map it in CSIS_LV or list it in GCAT_NOT_CSIS): {variants}; "
                         f"EXTRA_LV rockets not in LISTED (nothing prices them): {unpriced}")
    spans = {}
    for v in [*csis, *EXTRA_LV]:
        firsts = [gcat[lv][0] for lv in lvmap[v] if gcat[lv][0] is not None]
        if v not in csis and not firsts:
            continue  # a listed newcomer without a successful launch yet: not in service
        first = csis[v][0] if v in csis else min(firsts)
        end = max(gcat[lv][1] for lv in lvmap[v])
        if end < first:
            raise SystemExit(f"rockets: {v}: last GCAT launch {end} precedes its first success {first} (bad mapping?)")
        spans[v] = (first, today.year - 1 if end >= today.year - ACTIVE_YEARS else end, end)
    return spans


def list_prices(effective: dict) -> dict[str, dict[int, dict]]:
    """{rocket: {year: {price ($M), kg, published, source}}} from the effective ledger rows of LISTED."""
    out: dict[str, dict[int, dict]] = {}
    for v, slug in LISTED.items():
        p = {int(o): r for (m, o), r in effective.items() if m == f"list-price-{slug}"}
        k = {int(o): r for (m, o), r in effective.items() if m == f"list-leo-kg-{slug}"}
        if set(p) != set(k):
            raise SystemExit(f"rockets: list-price-{slug} and list-leo-kg-{slug} cover different years: "
                             f"{sorted(set(p) ^ set(k))} (each list price needs its published LEO capacity)")
        gaps = sorted(set(range(min(p), max(p) + 1)) - set(p)) if p else []
        if gaps:
            raise SystemExit(f"rockets: list-price-{slug} has no row for {gaps} between listed years: missed "
                             "intake, not a delisting (only years after the last listed one are held)")
        out[v] = {y: {"price": Decimal(p[y]["value"]), "kg": Decimal(k[y]["value"]),
                      "published": max(p[y]["published"], k[y]["published"]), "source": p[y]["source"]}
                  for y in p}
    return out


def rocket_cost(v: str, year: int, csis: dict, listed: dict, cpis: dict) -> dict | None:
    """Real (BASE_YEAR $) $/kg of rocket v in `year`: {value, note, published, source}, None if unpriced."""
    rows = listed.get(v, {})
    ly = max((y for y in rows if y <= year), default=None)
    if ly is not None:
        r = rows[ly]
        nominal = r["price"] * 1_000_000 / r["kg"]
        real, dnote = common.deflate(nominal, ly, cpis, BASE_YEAR)
        held = f", the {ly} list price held in real terms (not listed in {year})" if ly != year else ""
        return {"value": real, "published": r["published"], "source": r["source"],
                "note": f"{v} list ${r['price']}M / {r['kg']} kg = {common.round_half_up(nominal, 0)} $/kg "
                        f"nominal ({ly}){held}; {dnote}"}
    if v in csis:
        real, dnote = common.deflate(Decimal(csis[v][1]), CSIS_DOLLARS, cpis, BASE_YEAR)
        return {"value": real, "published": CSIS_UPDATED, "source": CSIS_URL,
                "note": f"{v} CSIS {csis[v][1]} $/kg (FY{CSIS_DOLLARS} $, first success {csis[v][0]}); {dnote}"}
    return None


def best_cost(csis: dict, spans: dict, listed: dict, cpis: dict, year: int) -> tuple[dict | None, list[str], str]:
    """(the cheapest rocket's rocket_cost, the rockets at that rounded price, latest input publication date)
    over the rockets in service in `year`."""
    live = {v: c for v, (a, b, _) in spans.items() if a <= year <= b
            for c in [rocket_cost(v, year, csis, listed, cpis)] if c}
    if not live:
        return None, [], ""
    rnd = {v: common.round_half_up(c["value"], 0) for v, c in live.items()}
    best = min(rnd.values(), key=Decimal)
    who = sorted(v for v in live if rnd[v] == best)
    return dict(live[who[0]], value=best), who, max(c["published"] for c in live.values())


def _dated(reg, metric, year, value, source, note, collector, today, inputs_published, effective, withdrawals):
    """A derived row: rule-dated, but not before its inputs were published (basis source); a value
    that revises the effective ledger row is left rule-dated, for common.mark_revisions to date first seen."""
    rule = ledger.rule_published(str(year), reg[metric]["release_lag_days"], str(today))
    late = inputs_published if inputs_published > rule else None
    r = common.row(reg, metric, str(year), value, source, note, collector, str(today), published=late)
    k = (metric, str(year))
    if late and common.is_revision(r, effective.get(k) or withdrawals.get(k)):
        r = common.row(reg, metric, str(year), value, source, note, collector, str(today))
    return r


def parse_ride_api(text: str) -> dict[int, Decimal]:
    """{launch year: US$ per kg} from RIDE_API's pricingMenus (US cents per kg)."""
    try:
        menus = json.loads(text)["content"]["pricingMenus"]
        out = {int(m["year"]): Decimal(int(m["pricePerKilogramUsd"])) / 100 for m in menus}
    except (ValueError, KeyError, TypeError) as e:
        raise SystemExit(f"{RIDE_API}: unexpected format ({e!r})")
    if not out or not all(1000 <= v <= 100000 for v in out.values()):
        raise SystemExit(f"{RIDE_API}: no or implausible $/kg prices {out}")
    return out


def collect_cost(fixture: str | None, today: dt.date, collector: str, reg: dict, existing=()) -> list[dict]:
    csis = parse_csis(common.fetch(CSIS_URL, fixture))
    spans = service_years(csis, parse_gcat(common.fetch(GCAT_URL, fixture)), today)
    cpis = common.parse_bls_cpi(common.fetch(common.BLS_CPI, fixture, {"User-Agent": common.BLS_USER_AGENT}))
    effective = ledger.obs_as_of("", rows=list(existing))
    withdrawals = ledger.obs_withdrawals(list(existing))
    listed = list_prices(effective)
    rows = [common.row(reg, M_RIDE, str(y), common.round_half_up(v, 0), RIDE_API,
                       f"SpaceX rideshare price per kg for {y} launches (booking app price API, pricingMenus)",
                       collector, str(today))
            for y, v in sorted(parse_ride_api(common.fetch(RIDE_API, fixture)).items()) if y <= today.year]
    # inputs of the real series as ledger.prepare would leave them: an unchanged API value keeps the
    # effective row (and its date), a new or changed one is the fresh row, a withdrawn value never counts
    wds = [r for r in existing if r.get("verification") == "withdrawn"]
    ride = {int(o): r for (m, o), r in effective.items() if m == M_RIDE}
    for r in rows:
        eff = ride.get(int(r["obs"]))
        if not ledger.withdrawn(r, wds) and not (eff and Decimal(eff["value"]) == Decimal(r["value"])):
            ride[int(r["obs"])] = r
    for metric, years in ((M_COST, range(min(s[0] for s in spans.values()), today.year)),
                          (M_RIDE_REAL, sorted(ride))):
        lag = dt.timedelta(days=int(reg[metric]["release_lag_days"] or 0))
        for year in years:
            if year >= today.year or dt.date(year, 12, 31) + lag > today:
                continue
            if metric == M_COST:
                c, who, inputs = best_cost(csis, spans, listed, cpis, year)
                if not c:
                    continue
                value, source = c["value"], c["source"]
                note = (f"cheapest dedicated launch per kg to LEO among the rockets in service in {year} "
                        f"(JSR GCAT), constant {BASE_YEAR} $: " + " = ".join(who) + f"; {c['note']}"
                        + f"; inputs as retrieved on {today}")
            else:
                r = ride[year]
                real, dnote = common.deflate(Decimal(r["value"]), year, cpis, BASE_YEAR)
                value, source, inputs = common.round_half_up(real, 0), r["source"], r["published"]
                note = f"SpaceX rideshare {r['value']} $/kg to SSO ({year}), constant {BASE_YEAR} $; {dnote}"
            rows.append(_dated(reg, metric, year, value, source, note, collector, today, inputs,
                               effective, withdrawals))
    derived = {(r["metric"], r["obs"]) for r in rows}
    gone = sorted(f"{m}@{o}" for (m, o), e in effective.items() if m in (M_COST, M_RIDE_REAL)
                  and ledger.tier(e) > 0 and (m, o) not in derived)
    if gone:
        raise SystemExit(f"rockets: ledger years no longer derived: {gone}; "
                         "review, then withdraw them (ledger.py withdraw-obs) or fix the inputs")
    return rows


def collect(fixture: str | None, today: dt.date, collector: str, existing=()) -> list[dict]:
    reg = common.registry(SECTION)
    lag = dt.timedelta(days=int(reg[METRIC]["release_lag_days"] or 0))
    mass = [common.row(reg, METRIC, str(year), value, URL,
                       "JSR msatannual total payload tonnage launched, all launching states (complete calendar year)",
                       collector, str(today))
            for year, value in parse(common.fetch(URL, fixture))
            if year < today.year and dt.date(year, 12, 31) + lag <= today]
    return mass + collect_cost(fixture, today, collector, reg, existing)


if __name__ == "__main__":
    sys.exit(common.main(SECTION, __file__, collect))
