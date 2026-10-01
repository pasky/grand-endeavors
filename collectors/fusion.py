#!/usr/bin/env python3
"""Fusion KPI collector: worldwide household electricity price, built from
GlobalPetrolPrices (GPP) country prices, World Bank population weights and US CPI.

Usage:  uv run collectors/fusion.py --out FILE [--fixture DIR] [--today YYYY-MM-DD]

No source publishes the KPI (a population-weighted, inflation-adjusted world
household price), so it is computed here, deterministically:

Sources (GPP prices are household retail prices incl. all taxes and fees, at the
country's average household consumption, converted to USD at market rates by GPP):
  main  https://www.globalpetrolprices.com/electricity_prices/
        - until ~2024: a bar chart "Electricity prices for households, <Month YYYY>
          (kWh, U.S. Dollar)" with every country's price (2019: an image whose URL
          carries the values, 2 decimals; later: HTML bars, 3 decimals), plus (from
          2020) GPP's stated world average;
        - from 2025: "<Qn YYYY> update: The average electricity price in the world is
          USD x kWh for residential users"; its country table is a multi-year
          (e.g. 2023-2026) average and is NOT used.
  map   https://www.globalpetrolprices.com/map/electricity_average/
        "The data on the map are for N countries and were collected in YYYY Qn",
        per-country USD prices with ISO3 codes (JS array cData).  It lags the paid
        data by ~2 quarters but is the only free per-country per-period table today.
  history: Wayback Machine snapshots of both pages (CDX API, one capture per
        month), fetched raw (id_) and cached under the cache dir
        (default $GE_DATA/ledger/staging/fusion-cache/; immutable, never refetched).
  World Bank API: SP.POP.TOTL (all countries, 2014-2026) and FP.CPI.TOTL (USA).

Choices:
  - obs = the GPP data quarter (YYYY-Qn): GPP collects quarterly; a month label
    ('December 2022') maps to its quarter (2022-Q4); the label is kept in the note.
  - One snapshot per (period, metric): the earliest archived capture stating that
    period (across the main and map page for the country-based metrics);
    published = its capture date, basis 'source' ("first archived").  A period seen
    only on the live page gets basis 'seen' (published = retrieved).
  - Population weights: World Bank SP.POP.TOTL of the latest year <= obs year.
    Countries without an ISO3 mapping or WB population are excluded and reported;
    the note gives n countries and the share of world (WLD) population covered.
  - Real values: x CPI(base) / CPI(obs year), US CPI annual average (World Bank
    FP.CPI.TOTL), base year 2025; while a year is missing the latest available CPI
    year stands in (for the base and/or the obs year) and the note says so.
  - Values in $/MWh (USD/kWh x 1000), rounded half-up to 1 decimal.
  - GPP converts local prices to USD at the exchange rate current when the page is
    rendered, so later captures of the same quarter drift with FX (typically a
    few $/MWh); the first archived capture is the closest to the quarter's own rate.
  - A value that differs from the effective ledger value (population or CPI
    revision, provisional deflator replaced, a live-page value replaced by the
    first archived capture) is a revision dated first seen.  A live-page-only
    value is not re-stated while the ledger already has the quarter (it would
    churn with FX on every run); the first archived capture supersedes it.
"""
from __future__ import annotations

import datetime as dt
import gzip
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
from decimal import Decimal

import common
import ledger

SECTION = "fusion"
MAIN = "https://www.globalpetrolprices.com/electricity_prices/"
MAP = "https://www.globalpetrolprices.com/map/electricity_average/"
PAGES = {"main": MAIN, "map": MAP}
CDX = ("http://web.archive.org/cdx/search/cdx?url={}&output=json&fl=timestamp,statuscode"
       "&filter=statuscode:200&collapse=timestamp:6")
WAYBACK = "https://web.archive.org/web/{}id_/{}"
WB_POP = "https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL?format=json&per_page=20000&date=2014:2026"
WB_CPI = "https://api.worldbank.org/v2/country/USA/indicator/FP.CPI.TOTL?format=json&per_page=200&date=2000:2026"
BASE_YEAR = 2025
M_REAL = "elec-price-household-world-popw-real"
M_NOM = "elec-price-household-world-popw-nominal"
M_AVG = "elec-price-household-gpp-avg"
ARCHIVE_SLEEP = 1.0  # seconds between web.archive.org requests (politeness)
MONTHS = {m: i for i, m in enumerate(("January February March April May June July August September "
                                      "October November December").split(), 1)}

# GPP country names (any vintage) whose World Bank name differs.  Names that match a
# WB country name after normalisation (case, accents, punctuation) need no entry.
GPP_ISO3 = {
    "UK": "GBR", "United Kingdom": "GBR", "USA": "USA", "United States": "USA",
    "Burma": "MMR", "Myanmar": "MMR", "Czech Rep.": "CZE", "Czech Republic": "CZE",
    "Bosnia & Herz.": "BIH", "Bosnia and Herzegovina": "BIH",
    "Domin. Rep.": "DOM", "Dom. Rep.": "DOM", "Dom. Republic": "DOM",
    "Ivory Coast": "CIV", "Russia": "RUS", "Iran": "IRN", "Egypt": "EGY", "Kyrgyzstan": "KGZ",
    "Laos": "LAO", "Slovakia": "SVK", "South Korea": "KOR", "Korea": "KOR", "Venezuela": "VEN",
    "Yemen": "YEM", "Hong Kong": "HKG", "Macao": "MAC", "Macau": "MAC", "Taiwan": "TWN",
    "Cape Verde": "CPV", "DR Congo": "COD", "Congo": "COG", "Bahamas": "BHS", "Gambia": "GMB",
    "Syria": "SYR", "Turkey": "TUR", "Vietnam": "VNM", "Brunei": "BRN", "Micronesia": "FSM",
    "Curacao": "CUW", "Kosovo": "XKX", "Palestine": "PSE", "Macedonia": "MKD",
    "North Macedonia": "MKD", "Moldova": "MDA", "Swaziland": "SWZ", "Eswatini": "SWZ",
    "Saint Lucia": "LCA", "St. Lucia": "LCA", "Sao Tome and Principe": "STP", "Tanzania": "TZA",
    "N. Maced.": "MKD", "N. Macedonia": "MKD", "Northern Macedonia": "MKD", "Eq. Guinea": "GNQ",
    "Tr.& Tobago": "TTO", "Tr.&Tobago": "TTO", "Trinidad & Tobago": "TTO", "UAE": "ARE", "UA Emirates": "ARE",
}
# ISO3 codes on GPP's map page that are not ISO3 (checked against the country names)
GPP_CODE_FIX = {"CRC": "CRI"}  # Costa Rica


# --- fetching (fixture / cache / network) ----------------------------------------------
class Sources:
    """Named source texts.  fixture: read DIR/<name> only.  Otherwise 'immutable'
    names (Wayback captures) are served from the cache dir once fetched, and 'fresh'
    names (live pages, CDX, World Bank) are fetched each run, saved to the cache and
    fall back to the cached copy if the network fails."""

    def __init__(self, fixture: str | None, cache: str | None):
        self.fixture, self.cache = fixture, cache
        self.warnings: list[str] = []
        self._last_archive = 0.0

    def get(self, name: str, url: str, fresh: bool) -> str | None:
        if self.fixture:
            path = os.path.join(self.fixture, name)
            if not os.path.exists(path):
                return None
            with open(path, encoding="utf-8") as f:
                return f.read()
        cached = os.path.join(self.cache, name) if self.cache else None
        if cached and not fresh and os.path.exists(cached):
            with open(cached, encoding="utf-8") as f:
                return f.read()
        try:
            text = self._download(url)
        except Exception as e:  # network/HTTP failure: degrade, never invent data
            if cached and os.path.exists(cached):
                self.warnings.append(f"{url}: {e}; using cached copy {name}")
                with open(cached, encoding="utf-8") as f:
                    return f.read()
            self.warnings.append(f"{url}: {e}; skipped")
            return None
        if cached:
            os.makedirs(self.cache, exist_ok=True)
            with open(cached + ".tmp", "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(cached + ".tmp", cached)
        return text

    def _download(self, url: str, tries: int = 3) -> str:
        archive = "web.archive.org" in url
        for attempt in range(tries):
            if archive:
                time.sleep(max(0.0, self._last_archive + ARCHIVE_SLEEP - time.time()))
            try:
                req = urllib.request.Request(url, headers={"User-Agent": common.USER_AGENT})
                with urllib.request.urlopen(req, timeout=120) as r:
                    raw = r.read()
                if raw[:2] == b"\x1f\x8b":  # Wayback id_ serves the stored (gzipped) bytes
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8", errors="replace")
                if archive and url.startswith("http://web.archive.org/cdx") and not text.lstrip().startswith("["):
                    raise ValueError("CDX answered non-JSON (archive outage?)")
                return text
            except Exception:
                if attempt == tries - 1:
                    raise
                time.sleep(5 * 3 ** attempt)
            finally:
                if archive:
                    self._last_archive = time.time()
        raise AssertionError("unreachable")


# --- parsing -------------------------------------------------------------------------
def month_obs(month: str, year: str) -> str:
    return f"{int(year)}-Q{(MONTHS[month] - 1) // 3 + 1}"


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def parse_main(text: str) -> dict:
    """GPP main page -> {obs, label, avg (USD/kWh str|None), prices [(name, value)], fmt}.
    obs None if no period statement is found."""
    t = _strip_comments(text)
    out = {"obs": None, "label": None, "avg": None, "prices": [], "fmt": None}
    if m := re.search(r"<b>\s*(Q[1-4]) (\d{4}) update\s*</b>", t):
        out["obs"], out["label"] = f"{m[2]}-{m[1]}", f"{m[1]} {m[2]}"
    elif m := re.search(r"Electricity prices(?: for households)?, ([A-Z][a-z]+) (\d{4})", t):
        if m[1] in MONTHS:
            out["obs"], out["label"] = month_obs(m[1], m[2]), f"{m[1]} {m[2]}"
    if m := (re.search(r"world average price is (\d+\.\d+) U\.S\. Dollar per kWh for household", t)
             or re.search(r"average electricity price in the world is USD (\d+\.\d+)\s+(?:USD )?(?:per )?kWh for residential", t)):
        out["avg"] = m[1]
    # the per-period country bar chart (absent from 2025 on)
    title = re.search(r'id="titleGraphic".*?<span[^>]*>\s*Electricity prices(?: for households)?, '
                      r"([A-Z][a-z]+) (\d{4})\s*</span>\s*<br\s*/?>\s*\(kWh, U\.S\. Dollar\)", t, re.S)
    if not title:
        return out
    if out["label"] != f"{title[1]} {title[2]}":
        raise ValueError(f"chart period '{title[1]} {title[2]}' != page period '{out['label']}'")
    i, j = t.find('id="outsideLinks"'), t.find('id="graphic"')
    names = [html.unescape(n).strip() for n in re.findall(r"class='graph_outside_link'>([^<]+)</a>", t[i:j])]
    graphic = t[j:]
    if m := re.search(r"graph\.php\?data=[^&\"']*&(?:amp;)?titles=([0-9.|]+)", graphic[:20000]):
        values, out["fmt"] = m[1].split("|"), "graph-img (2-decimal values)"
    else:
        end = graphic.find('id="', 20)  # the chart is one block of anonymous divs
        values = re.findall(r'color: #000000;">\s*(\d+(?:\.\d+)?)\s*</div>', graphic[:end if end > 0 else None])
        out["fmt"] = "graph-div"
    if not names or len(names) != len(values):
        raise ValueError(f"chart has {len(names)} country names but {len(values)} values")
    out["prices"] = list(zip(names, values))
    return out


def parse_map(text: str) -> dict:
    """GPP household-price world map -> {obs, label, n_stated, prices [(name, iso3, value)]}."""
    out = {"obs": None, "label": None, "n_stated": None, "prices": []}
    m = re.search(r"data on the map are for (\d+) countries and were collected in (\d{4}) Q([1-4])", text)
    if not m or "Electricity prices for households" not in text:
        return out
    out["n_stated"], out["obs"], out["label"] = int(m[1]), f"{m[2]}-Q{m[3]}", f"{m[2]} Q{m[3]}"
    d = re.search(r"var cData = (\[.*?\]);", text, re.S)
    if not d:
        raise ValueError("map page without cData")
    out["prices"] = [(c["country_name"], c["code2"], c["price"]) for c in json.loads(d[1])]
    return out


def parse_cdx(text: str) -> list[str]:
    rows = json.loads(text)
    return sorted(r[0] for r in rows[1:] if r[1] == "200")


def parse_wb(text: str) -> list[dict]:
    d = json.loads(text)
    if not isinstance(d, list) or len(d) < 2 or not d[1]:
        raise ValueError(f"World Bank API returned no data: {text[:200]}")
    return d[1]


def population(records: list[dict]) -> tuple[dict, dict]:
    """({iso3: {year: pop}}, {normalised WB name: iso3}) from SP.POP.TOTL records."""
    pop: dict[str, dict[int, int]] = {}
    names: dict[str, str] = {}
    for r in records:
        iso = r.get("countryiso3code")
        if not iso:
            continue
        names.setdefault(norm(r["country"]["value"]), iso)
        if r["value"] is not None:
            pop.setdefault(iso, {})[int(r["date"])] = int(r["value"])
    return pop, names


def cpi(records: list[dict]) -> dict[int, Decimal]:
    return {int(r["date"]): Decimal(str(r["value"])) for r in records if r["value"] is not None}


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s.replace("&", " and ")).strip()


def iso3(name: str, wb_names: dict[str, str]) -> str | None:
    return GPP_ISO3.get(name) or wb_names.get(norm(name))


# --- the computation -----------------------------------------------------------------
def latest_year(series: dict[int, object], year: int) -> int | None:
    ys = [y for y in series if y <= year]
    return max(ys) if ys else None


def weighted(prices: dict[str, Decimal], pop: dict[str, dict[int, int]], year: int) -> dict:
    """Population-weighted mean of {iso3: USD/kWh} with WB populations of the latest
    year <= `year`.  Returns {mean, n, covered, world, pop_years, excluded}."""
    num = den = Decimal(0)
    n, excluded, years = 0, [], set()
    for iso, p in sorted(prices.items()):
        y = latest_year(pop.get(iso, {}), year)
        if y is None:
            excluded.append(iso)
            continue
        w = pop[iso][y]
        num += p * w
        den += w
        n += 1
        years.add(y)
    wy = latest_year(pop.get("WLD", {}), year)
    if not n:
        raise ValueError("no country with a population weight")
    return {"mean": num / den, "n": n, "covered": den, "world": pop["WLD"][wy] if wy else None,
            "pop_years": sorted(years), "excluded": excluded}


def deflate(nominal: Decimal, year: int, cpis: dict[int, Decimal], base: int = BASE_YEAR) -> tuple[Decimal, str]:
    """(real value in constant `base` USD, note).  Missing CPI years fall back to the
    latest available year (stated in the note)."""
    last = max(cpis)
    by = base if base in cpis else last
    oy = year if year in cpis else latest_year(cpis, year)
    note = f"deflated with US CPI annual averages (World Bank FP.CPI.TOTL) {oy} -> {by}"
    flags = []
    if by != base:
        flags.append(f"{base} CPI not yet published, base = {by} CPI (provisional)")
    if oy != year:
        flags.append(f"{year} CPI not yet published, {oy} CPI used (provisional)")
    return nominal * cpis[by] / cpis[oy], note + ("; " + "; ".join(flags) if flags else "")


def mwh(usd_kwh: Decimal | str) -> str:
    return common.round_half_up(Decimal(str(usd_kwh)) * 1000, 1)


# --- snapshots -----------------------------------------------------------------------
def snapshots(src: Sources) -> list[dict]:
    """Every parsed capture: Wayback (per CDX) + live pages, as
    {page, ts (YYYYMMDDhhmmss|None), date, url, parsed}."""
    out = []
    for page, url in PAGES.items():
        cdx_text = src.get(f"cdx-{page}.json", CDX.format(url.split("//", 1)[1]), fresh=True)
        stamps = []
        if cdx_text is not None:
            try:
                stamps = parse_cdx(cdx_text)
            except ValueError as e:
                src.warnings.append(f"CDX {page}: unparseable ({e})")
        if not stamps and src.cache and os.path.isdir(src.cache):  # archive outage: use what we have
            stamps = sorted(f[len(f"wayback-{page}-"):-5] for f in os.listdir(src.cache)
                            if f.startswith(f"wayback-{page}-") and f.endswith(".html"))
        for ts in stamps:
            text = src.get(f"wayback-{page}-{ts}.html", WAYBACK.format(ts, url), fresh=False)
            if text is None:
                continue
            out.append(_parsed(src, page, ts, f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", WAYBACK.format(ts, url), text))
        live = src.get(f"live-{page}.html", url, fresh=True)
        if live is not None:
            out.append(_parsed(src, page, None, None, url, live))
    return [s for s in out if s["parsed"] and s["parsed"]["obs"]]


def _parsed(src, page, ts, date, url, text) -> dict:
    try:
        parsed = (parse_main if page == "main" else parse_map)(text)
    except ValueError as e:
        src.warnings.append(f"{url}: {e}; capture skipped")
        parsed = None
    return {"page": page, "ts": ts, "date": date, "url": url, "parsed": parsed}


def first_by_period(snaps: list[dict], usable) -> dict[str, dict]:
    """{obs: earliest capture with usable(capture)}; live pages (no ts) come last."""
    out: dict[str, dict] = {}
    for s in sorted(snaps, key=lambda s: (s["ts"] is None, s["ts"] or "", s["page"] != "map")):
        if usable(s):
            out.setdefault(s["parsed"]["obs"], s)
    return out


def country_prices(s: dict, wb_names: dict[str, str]) -> tuple[dict[str, Decimal], list[str]]:
    """({iso3: USD/kWh}, unmapped GPP names) for one capture."""
    prices, unmapped = {}, []
    for item in s["parsed"]["prices"]:
        if s["page"] == "map":
            name, code, value = item
            code = GPP_CODE_FIX.get(code, code)
        else:
            (name, value), code = item, iso3(item[0], wb_names)
        if not code:
            unmapped.append(name)
        elif code in prices:
            raise ValueError(f"{s['url']}: two prices for {code}")
        else:
            prices[code] = Decimal(value)
    return prices, unmapped


def collect(fixture: str | None, today: dt.date, collector: str, existing=(), cache: str | None = None) -> list[dict]:
    reg = common.registry(SECTION)
    if cache is None and not fixture:
        cache = os.path.join(ledger.DATA, "ledger", "staging", "fusion-cache")
    src = Sources(fixture, cache)
    pop_text, cpi_text = src.get("wb-pop.json", WB_POP, fresh=True), src.get("wb-cpi.json", WB_CPI, fresh=True)
    if pop_text is None or cpi_text is None:
        raise SystemExit("fusion: World Bank population/CPI unavailable: " + "; ".join(src.warnings))
    pop, wb_names = population(parse_wb(pop_text))
    cpis = cpi(parse_wb(cpi_text))
    snaps = snapshots(src)
    rows: list[dict] = []
    retrieved = str(today)

    def add(metric, obs, value, s, note):
        if s["ts"]:
            rows.append(common.row(reg, metric, obs, value, s["url"], f"{note}; published = first archived capture",
                                   collector, retrieved, published=s["date"]))
        else:
            rows.append(common.row(reg, metric, obs, value, s["url"], note, collector, retrieved))

    for obs, s in sorted(first_by_period(snaps, lambda s: s["page"] == "main" and s["parsed"]["avg"]).items()):
        add(M_AVG, obs, mwh(s["parsed"]["avg"]), s,
            f"GPP-stated world average household price for '{s['parsed']['label']}' "
            f"(USD {s['parsed']['avg']}/kWh; simple cross-country average, nominal)")

    unmapped_all: set[str] = set()
    for obs, s in sorted(first_by_period(snaps, lambda s: bool(s["parsed"]["prices"])).items()):
        prices, unmapped = country_prices(s, wb_names)
        unmapped_all.update(unmapped)
        year = int(obs[:4])
        w = weighted(prices, pop, year)
        unmapped_all.update(w["excluded"])
        share = common.round_half_up(w["covered"] * 100 / w["world"], 1) if w["world"] else "?"
        what = ("GPP household price world map ('collected in " if s["page"] == "map"
                else "GPP household price chart ('") + s["parsed"]["label"] + "'"
        if s["page"] == "main":
            what += f", {s['parsed']['fmt']}"
        cov = (f"{w['n']} countries, {share}% of world population (World Bank SP.POP.TOTL "
               f"{'/'.join(map(str, w['pop_years']))})")
        if unmapped or w["excluded"]:
            cov += f"; excluded (no ISO3 or WB population): {', '.join(sorted(unmapped + w['excluded']))}"
        nominal = w["mean"] * 1000
        add(M_NOM, obs, common.round_half_up(nominal, 1), s,
            f"Derived: population-weighted mean of {what}) country prices, USD at GPP market rates; {cov}")
        real, dnote = deflate(nominal, year, cpis)
        add(M_REAL, obs, common.round_half_up(real, 1), s,
            f"Derived: population-weighted mean of {what}) country prices, USD at GPP market rates, "
            f"constant {BASE_YEAR} USD; {dnote}; {cov}")

    for wmsg in src.warnings + ([f"unmapped/unweighted GPP countries: {', '.join(sorted(unmapped_all))}"]
                                if unmapped_all else []):
        print(f"  WARNING {wmsg}", file=sys.stderr)
    return revise_derived(rows, existing)


def revise_derived(rows: list[dict], existing) -> list[dict]:
    """A value that differs from the effective non-legacy ledger value (WB population
    or CPI revision, provisional deflator replaced) became known when we computed it:
    re-date it to first seen (common.mark_revisions only re-dates rule-basis rows)."""
    effective = ledger.obs_as_of("", rows=list(existing))
    out = []
    for r in rows:
        eff = effective.get((r["metric"], r["obs"]))
        if r["published_basis"] == "seen" and eff is not None and ledger.tier(eff) > 0:
            continue  # live-page value: keep the first-seen one until an archived capture exists
        if common.is_revision(r, eff) and r["published_basis"] == "source":
            r = dict(r, published=r["retrieved"], published_basis="seen",
                     note=r["note"].replace("; published = first archived capture", "")
                     + f"; revises effective ledger value {eff['value']} (published {eff['published']})"
                       " (published = first seen)")
        out.append(r)
    return out


if __name__ == "__main__":
    sys.exit(common.main(SECTION, __file__, collect))
