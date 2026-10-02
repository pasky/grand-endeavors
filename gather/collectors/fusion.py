#!/usr/bin/env python3
"""Fusion KPI collector: worldwide household electricity price, built from
GlobalPetrolPrices (GPP) country prices, World Bank population weights and US CPI.

Usage:  uv run gather/collectors/fusion.py --out FILE [--fixture DIR] [--today YYYY-MM-DD]

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
  history: Wayback Machine captures of both pages (CDX API, collapsed to the first
        capture per month; united with the already-cached captures), fetched raw
        (id_), validated, and cached under the cache dir
        (default $GE_DATA/ledger/staging/fusion-cache/; immutable, never refetched).
  World Bank API: SP.POP.TOTL (all countries, 2014-<run year>).
  BLS CPI-U, all items, US city average, not seasonally adjusted (series
  CUUR0000SA0), official annual averages (period M13) from the BLS flat file
  https://download.bls.gov/pub/time.series/cu/cu.data.1.AllItems (BLS asks for a
  User-Agent with a contact address).

Choices:
  - obs = the GPP data quarter (YYYY-Qn): GPP collects quarterly; a month label
    ('December 2022') maps to its quarter (2022-Q4); the label is kept in the note.
  - One capture per (period, metric): the earliest capture stating that period
    (across the main and map page for the country-based metrics), by capture date.
    Wayback: published = capture date, basis 'source' (the earliest capture in the
    month-sampled CDX index: an upper bound of GPP's release).  Live page: the
    first live copy seen for a period is frozen in the cache and dated then (basis
    'seen', published = retrieved = first-seen date), so a live-only period does
    not churn with FX on every run.
  - Population weights: World Bank SP.POP.TOTL of the latest year <= obs year.
    Countries without an ISO3 mapping or WB population are excluded and reported;
    the note gives n countries and the share of world (WLD) population covered.
  - Data-error guards: a map listing a different number of countries than it
    states, or a capture with < MIN_COVERAGE_RATIO of the countries of earlier
    captures, is not used for country prices (truncation).  Country prices above
    PLAUSIBLE_MAX (1 USD/kWh) and documented GPP_ERRATA are excluded and noted.
  - Real values: x CPI(base) / CPI(obs year), BLS CPI-U annual average
    (CUUR0000SA0, M13), base year 2025; while a year is missing the latest available CPI
    year stands in (for the base and/or the obs year) and the note says so.
  - Values in $/MWh (USD/kWh x 1000), rounded half-up to 1 decimal.
  - GPP converts local prices to USD at the exchange rate current when the page is
    rendered, so later captures of the same quarter drift with FX (typically a
    few $/MWh; hyperinflation currencies much more); the earliest capture is the
    closest to the quarter's own rate.
  - A value that differs from the effective ledger value (population or CPI
    revision, provisional deflator replaced, a different capture selected) is a
    revision dated first seen (published = retrieved = today).
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
WB_POP = "https://api.worldbank.org/v2/country/all/indicator/SP.POP.TOTL?format=json&per_page=20000&date=2014:{}"
BLS_CPI = "https://download.bls.gov/pub/time.series/cu/cu.data.1.AllItems"
CPI_SERIES = "CUUR0000SA0"  # CPI-U, all items, US city average, NSA
BLS_USER_AGENT = "grand-endeavors-collector/1 (python-urllib; contact: pasky@ucw.cz)"
BASE_YEAR = 2025
# Highest genuine GPP household price seen 2018-2026: Italy 0.783 USD/kWh (Dec 2022).  Larger
# values are GPP currency-conversion errors (Syria 2.220 in 2025 Q2, Croatia 1.227 in 2022 Q2)
# and would dominate a population-weighted mean; they are excluded and listed in the note.
PLAUSIBLE_MAX = Decimal("1.0")
# Documented single-capture GPP errors (obs, ISO3) -> evidence; the price is excluded, not replaced.
GPP_ERRATA = {
    ("2020-Q1", "KOR"): "0.00 in the first capture (2020-10-21), 0.11 in both later captures of March 2020",
}
MIN_COVERAGE_RATIO = 0.75  # a capture with < 75% of the countries of earlier captures is truncated
ARCHIVED = "published = earliest Wayback capture showing this period (CDX index sampled monthly)"
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

    def get(self, name: str, url: str, fresh: bool, validate=None, final_has: str | None = None) -> str | None:
        """validate(text) must not raise for a download to be used and cached (a
        Wayback HTTP-200 interstitial must not poison the immutable cache, a broken
        WB answer must not overwrite the last good copy); final_has: required
        substring of the final (post-redirect) URL."""
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
            text, final = self._download(url)
            if final_has and final_has not in final:
                raise ValueError(f"redirected to {final}")
            if validate:
                validate(text)
        except Exception as e:  # network/HTTP/content failure: degrade, never invent data
            if cached and os.path.exists(cached):
                self.warnings.append(f"{url}: {e}; using cached copy {name}")
                with open(cached, encoding="utf-8") as f:
                    return f.read()
            self.warnings.append(f"{url}: {e}; skipped")
            return None
        if cached:
            self._write(name, text)
        return text

    def _write(self, name: str, text: str) -> None:
        os.makedirs(self.cache, exist_ok=True)
        path = os.path.join(self.cache, name)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(path + ".tmp", path)

    def cached_stamps(self, page: str) -> set[str]:
        pre = f"wayback-{page}-"
        if self.fixture or not self.cache or not os.path.isdir(self.cache):
            return set()
        return {f[len(pre):-5] for f in os.listdir(self.cache) if f.startswith(pre) and f.endswith(".html")}

    def freeze(self, page: str, obs: str, today: dt.date, text: str) -> tuple[str, str]:
        """(first-seen date, text) of the live page for period `obs`: the first live
        copy we saw is kept in the cache, so a live-only period is not re-derived
        from FX-drifted later renderings on every run."""
        if self.fixture or not self.cache:
            return str(today), text
        pre = f"seen-{page}-{obs}-"
        seen = sorted(f for f in os.listdir(self.cache) if f.startswith(pre) and f.endswith(".html")) \
            if os.path.isdir(self.cache) else []
        if seen:
            with open(os.path.join(self.cache, seen[0]), encoding="utf-8") as f:
                return seen[0][len(pre):-5], f.read()
        self._write(f"{pre}{today}.html", text)
        return str(today), text

    def _download(self, url: str, tries: int = 3) -> tuple[str, str]:
        archive = "web.archive.org" in url
        for attempt in range(tries):
            if archive:
                time.sleep(max(0.0, self._last_archive + ARCHIVE_SLEEP - time.time()))
            try:
                ua = BLS_USER_AGENT if "bls.gov" in url else common.USER_AGENT
                req = urllib.request.Request(url, headers={"User-Agent": ua})
                with urllib.request.urlopen(req, timeout=120) as r:
                    raw, final = r.read(), r.geturl()
                if raw[:2] == b"\x1f\x8b":  # Wayback id_ serves the stored (gzipped) bytes
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8", errors="replace")
                if archive and url.startswith("http://web.archive.org/cdx") and not text.lstrip().startswith("["):
                    raise ValueError("CDX answered non-JSON (archive outage?)")
                return text, final
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
    if len(out["prices"]) != out["n_stated"]:
        raise ValueError(f"map lists {len(out['prices'])} countries but states {out['n_stated']}")
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


def parse_bls_cpi(text: str) -> dict[int, Decimal]:
    """{year: annual average} of CPI_SERIES from a BLS cu.data.* flat file (tab-separated
    series_id, year, period, value, footnotes; M13 = BLS's official annual average)."""
    out = {}
    for ln in text.splitlines()[1:]:
        f = [x.strip() for x in ln.split("\t")]
        if len(f) >= 4 and f[0] == CPI_SERIES and f[2] == "M13":
            out[int(f[1])] = Decimal(f[3])
    if not out:
        raise ValueError(f"no {CPI_SERIES} annual averages (M13) in the BLS file")
    return out


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
    note = f"deflated with BLS CPI-U annual averages ({CPI_SERIES}) {oy} -> {by}"
    flags = []
    if by != base:
        flags.append(f"{base} CPI not yet published, base = {by} CPI (provisional)")
    if oy != year:
        flags.append(f"{year} CPI not yet published, {oy} CPI used (provisional)")
    return nominal * cpis[by] / cpis[oy], note + ("; " + "; ".join(flags) if flags else "")


def mwh(usd_kwh: Decimal | str) -> str:
    return common.round_half_up(Decimal(str(usd_kwh)) * 1000, 1)


# --- snapshots -----------------------------------------------------------------------
def _check_capture(page: str):
    """Validator for a downloaded capture: parses, states a period (else not cached)."""
    def check(text: str) -> None:
        if not (parse_main if page == "main" else parse_map)(text)["obs"]:
            raise ValueError("no GPP period statement (not a GPP page?)")
    return check


def snapshots(src: Sources, today: dt.date) -> list[dict]:
    """Every usable capture: Wayback (CDX index UNION already-cached captures, so an
    incomplete index never hides an earlier capture) + the live pages (frozen at first
    sight per period), as {page, ts (YYYYMMDDhhmmss|None), date, url, parsed, seen}."""
    out = []
    for page, url in PAGES.items():
        stamps = src.cached_stamps(page)
        cdx_text = src.get(f"cdx-{page}.json", CDX.format(url.split("//", 1)[1]), fresh=True, validate=parse_cdx)
        if cdx_text is not None:
            try:
                stamps |= set(parse_cdx(cdx_text))
            except ValueError as e:
                src.warnings.append(f"CDX {page}: unparseable ({e})")
        for ts in sorted(stamps):
            wurl = WAYBACK.format(ts, url)
            text = src.get(f"wayback-{page}-{ts}.html", wurl, fresh=False,
                           validate=_check_capture(page), final_has=f"/web/{ts}")
            if text is not None:
                out.append(_parsed(src, page, ts, f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", wurl, text))
        live = src.get(f"live-{page}.html", url, fresh=True)
        if live is not None:
            s = _parsed(src, page, None, str(today), url, live)
            if s["parsed"] and s["parsed"]["obs"]:
                s["date"], text = src.freeze(page, s["parsed"]["obs"], today, live)
                out.append(_parsed(src, page, None, s["date"], url, text))
    return drop_collapsed([s for s in out if s["parsed"] and s["parsed"]["obs"]], src.warnings)


def _parsed(src, page, ts, date, url, text) -> dict:
    try:
        parsed = (parse_main if page == "main" else parse_map)(text)
    except ValueError as e:
        src.warnings.append(f"{url}: {e}; capture skipped")
        parsed = None
    return {"page": page, "ts": ts, "date": date, "url": url, "parsed": parsed, "seen": ts is None}


def drop_collapsed(snaps: list[dict], warnings: list[str]) -> list[dict]:
    """Drop the country prices of a capture listing fewer than MIN_COVERAGE_RATIO x the
    most countries of any earlier capture (a truncated chart/page would otherwise
    become 'the world'); its stated average, if any, is kept."""
    out, most = [], 0
    for s in sorted(snaps, key=lambda s: (s["date"], s["ts"] or "")):
        n = len(s["parsed"]["prices"])
        if n and n < MIN_COVERAGE_RATIO * most:
            warnings.append(f"{s['url']}: only {n} country prices (earlier captures: {most}); prices not used")
            s = dict(s, parsed=dict(s["parsed"], prices=[]))
        most = max(most, n)
        out.append(s)
    return out


def first_by_period(snaps: list[dict], usable) -> dict[str, dict]:
    """{obs: earliest capture (by capture / first-seen date) with usable(capture)}."""
    out: dict[str, dict] = {}
    for s in sorted(snaps, key=lambda s: (s["date"], s["seen"], s["ts"] or "", s["page"] != "map")):
        if usable(s):
            out.setdefault(s["parsed"]["obs"], s)
    return out


def country_prices(s: dict, wb_names: dict[str, str]) -> tuple[dict[str, Decimal], list[str], list[str]]:
    """({iso3: USD/kWh}, unmapped GPP names, rejected 'ISO3 price (why)' entries) for one capture."""
    prices, unmapped, rejected = {}, [], []
    obs = s["parsed"]["obs"]
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
        elif (obs, code) in GPP_ERRATA:
            rejected.append(f"{code} {value} (erratum: {GPP_ERRATA[(obs, code)]})")
        elif Decimal(value) > PLAUSIBLE_MAX:
            rejected.append(f"{code} {value} (> {PLAUSIBLE_MAX} USD/kWh, implausible: a GPP conversion error)")
        else:
            prices[code] = Decimal(value)
    return prices, unmapped, rejected


def collect(fixture: str | None, today: dt.date, collector: str, existing=(), cache: str | None = None) -> list[dict]:
    reg = common.registry(SECTION)
    if cache is None and not fixture:
        cache = os.path.join(ledger.DATA, "ledger", "staging", "fusion-cache")
    src = Sources(fixture, cache)
    pop_text = src.get("wb-pop.json", WB_POP.format(today.year), fresh=True, validate=parse_wb)
    cpi_text = src.get("bls-cpi.txt", BLS_CPI, fresh=True, validate=parse_bls_cpi)
    if pop_text is None or cpi_text is None:
        raise SystemExit("fusion: World Bank population / BLS CPI unavailable: " + "; ".join(src.warnings))
    pop, wb_names = population(parse_wb(pop_text))
    cpis = parse_bls_cpi(cpi_text)
    snaps = snapshots(src, today)
    rows: list[dict] = []

    def add(metric, obs, value, s, note):
        if s["seen"]:  # live page: dated when we first saw (and froze) it
            rows.append(common.row(reg, metric, obs, value, s["url"], note + "; published = first seen on the live page",
                                   collector, s["date"]))
        else:
            rows.append(common.row(reg, metric, obs, value, s["url"], note + "; " + ARCHIVED, collector, str(today),
                                   published=s["date"]))

    for obs, s in sorted(first_by_period(snaps, lambda s: s["page"] == "main" and s["parsed"]["avg"]).items()):
        add(M_AVG, obs, mwh(s["parsed"]["avg"]), s,
            f"GPP-stated world average household price for '{s['parsed']['label']}' "
            f"(USD {s['parsed']['avg']}/kWh; simple cross-country average, nominal)")

    unmapped_all: set[str] = set()
    for obs, s in sorted(first_by_period(snaps, lambda s: bool(s["parsed"]["prices"])).items()):
        prices, unmapped, rejected = country_prices(s, wb_names)
        unmapped_all.update(unmapped)
        if rejected:
            src.warnings.append(f"{s['url']}: country prices excluded: {', '.join(rejected)}")
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
        if rejected:
            cov += "; excluded as GPP data errors: " + ", ".join(rejected)
        nominal = w["mean"] * 1000
        add(M_NOM, obs, common.round_half_up(nominal, 1), s,
            f"Derived: population-weighted mean of {what}) country prices, USD at GPP market rates; {cov}; "
            f"population weights as retrieved on {today} (not as of the capture date)")
        real, dnote = deflate(nominal, year, cpis)
        add(M_REAL, obs, common.round_half_up(real, 1), s,
            f"Derived: population-weighted mean of {what}) country prices, USD at GPP market rates, "
            f"constant {BASE_YEAR} USD; {dnote}; {cov}; population weights and CPI as retrieved on {today} "
            "(not as of the capture date)")

    for wmsg in src.warnings + ([f"unmapped/unweighted GPP countries: {', '.join(sorted(unmapped_all))}"]
                                if unmapped_all else []):
        print(f"  WARNING {wmsg}", file=sys.stderr)
    return revise_derived(rows, existing, today)


def revise_derived(rows: list[dict], existing, today: dt.date) -> list[dict]:
    """A value that differs from the effective non-legacy ledger value (WB population
    or CPI revision, provisional deflator replaced, a live-page value replaced by an
    earlier archived capture) became known when we computed it: re-date it to first
    seen = today (common.mark_revisions only re-dates rule-basis rows)."""
    effective = ledger.obs_as_of("", rows=list(existing))
    out = []
    for r in rows:
        eff = effective.get((r["metric"], r["obs"]))
        if common.is_revision(r, eff):
            note = r["note"].replace("; " + ARCHIVED, "").replace("; published = first seen on the live page", "")
            r = dict(r, published=str(today), retrieved=str(today), published_basis="seen",
                     note=note + f"; revises effective ledger value {eff['value']} (published {eff['published']})"
                                 " (published = first seen)")
        out.append(r)
    return out


if __name__ == "__main__":
    sys.exit(common.main(SECTION, __file__, collect))
