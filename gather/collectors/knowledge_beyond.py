#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Knowledge Beyond indicator collector (a supplemental section: tracked, never assessed).

Usage:  uv run gather/collectors/knowledge_beyond.py --out FILE [--fixture DIR] [--today YYYY-MM-DD]

Four machine-readable sources, plus one series derived from the ledger; the section's other
indicators (the Q-Day inputs, connectome, superconducting Tc) have no feed and are staged
by gather intake. Any source failing fails the run (nothing is written), so a broken
source is never silently skipped.

internet-users-world-share
  World Bank WDI API, indicator IT.NET.USER.ZS ("Individuals using the Internet (% of
  population)", World = WLD; the data are ITU's), WB_URL. JSON [meta, [records]]; a paged
  answer (pages > 1), a record count other than the stated total, a repeated year or no
  value at all is an error. value = the record's number verbatim; obs = its year
  (complete years only: a current-year value would be a partial-year estimate).
  published: registry release_lag_days rule (ITU's estimate for year Y appears in its
  November Facts and Figures; WDI carries it during Y+1).

erdos-problems-solved-share
  github.com/teorth/erdosproblems data/statistics_history.csv (ERDOS_URL): one row per
  commit to the problem database, columns commit,date,total_problems,...,total_solved,...
  (later columns were added over time; early rows are shorter). value = total_solved /
  total_problems x 100, rounded half-up to 1 decimal, at the last snapshot dated (UTC)
  by the end of the obs month; complete months only, from FIRST_ERDOS_MONTH (the
  database was imported on its first day, 2025-08-31, with every status still 'solved').
  The note gives the counts and the snapshot commit. published: rule (month end + lag).

top500-top-rmax
  The TOP500 list pages https://top500.org/lists/top500/YYYY/MM/ (June and November
  lists, from 1993-06). value = the rank-1 system's HPL Rmax converted to PFlop/s from
  the table header's unit (GFlop/s until the 2000s, then TFlop/s, PFlop/s), exact decimal
  arithmetic; the Rmax cell is bound to its header column and the page title must name
  the requested edition (year and month's first 3 letters). TOP500_ERRATA overrides a wrong header unit (Nov 2018: "GFlop/s"
  over TFlop/s values). Guard: the #1 Rmax never fell, nor grew 10x, from one list to
  the next (checked against the previous list of this run, else the ledger), so a unit
  error fails the run instead of entering the series. obs = the list month. Fetched:
  every list from the latest one this collector already put in the ledger (re-checked
  for revisions) up to the newest list due by today, or all of them on the first run or
  with TOP500_REFRESH=1 (1 s apart; e.g. after a new erratum, so the old value gets a
  revision row). Only an edition not yet in the ledger may be missing (404), and only in
  its own month (not released yet: the lists come out mid-month). published: rule (list
  month end + lag; the pages state no date, so this is a late upper estimate, capped at
  retrieval).

exoplanets-confirmed
  NASA Exoplanet Archive TAP, Planetary Systems Composite table (pscomppars = one row per
  confirmed planet), EXO_URL: pl_name, disc_year. value = planets with disc_year <= obs
  year, counted in the current archive; complete years only (Dec 31 + lag passed). A
  planet added later with an earlier discovery year, or a retracted one, revises the
  count (appended as a revision). Guards: a row count other than the archive's own
  count(*) (EXO_COUNT_URL), fewer than MIN_PLANETS rows (truncation) or a duplicated
  pl_name is an error. published: rule.

qday-qubit-gap (derived, no fetch)
  From the section's ledger rows of its two intake-staged inputs (effective values):
  at each obs date of either input, needed = the lowest qday-rsa2048-qubits-needed and
  available = the highest qday-largest-device-qubits observed by that date (both are
  record series); value = needed / available to 3 significant digits, emitted once both
  exist. obs = that date; source = the changed input's source; published = the later
  of the two inputs' publication dates (basis source). An input revision re-derives the
  affected dates (revisions append; equal values dedup on merge).

With --fixture DIR each source is read from DIR/<FIXTURES name> (TOP500:
DIR/top500-YYYY-MM.html; a missing list file counts as not found).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import re
import sys
import time
import urllib.error
from decimal import Decimal

import common
import kpi
import ledger

SECTION = "knowledge-beyond"
WB_URL = "https://api.worldbank.org/v2/country/WLD/indicator/IT.NET.USER.ZS?format=json&per_page=200"
ERDOS_URL = "https://raw.githubusercontent.com/teorth/erdosproblems/main/data/statistics_history.csv"
EXO_URL = ("https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
           "?query=select+pl_name,disc_year+from+pscomppars&format=csv")
EXO_COUNT_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync?query=select+count(*)+from+pscomppars&format=csv"
TOP500_URL = "https://top500.org/lists/top500/{y}/{m:02d}/"
FIXTURES = {WB_URL: "wb_internet_users.json", ERDOS_URL: "statistics_history.csv",
            EXO_URL: "exoplanets_pscomppars.csv", EXO_COUNT_URL: "exoplanets_count.csv"}
M_INTERNET, M_ERDOS = "internet-users-world-share", "erdos-problems-solved-share"
M_TOP500, M_EXO = "top500-top-rmax", "exoplanets-confirmed"
M_GAP, M_NEEDED, M_DEVICE = "qday-qubit-gap", "qday-rsa2048-qubits-needed", "qday-largest-device-qubits"
FIRST_ERDOS_MONTH = "2025-09"
FIRST_TOP500 = (1993, 6)
# list pages whose Rmax header unit is wrong: {(year, month): (true unit prefix, why)}
TOP500_ERRATA = {(2018, 11): ("T", "the page's header says GFlop/s but its values are TFlop/s: Summit's "
                              "143,500 = 143.5 PFlop/s, as its TOP500 system page gives")}
MIN_PLANETS = 5000
TO_PFLOPS = {"G": Decimal("1e-6"), "T": Decimal("1e-3"), "P": Decimal(1), "E": Decimal(1000)}


class NotFound(Exception):
    pass


def fetch(url: str, fixture: str | None, name: str | None = None) -> str:
    if fixture:
        path = os.path.join(fixture, name or FIXTURES[url])
        if not os.path.exists(path):
            raise NotFound(path)
        with open(path, encoding="utf-8") as f:
            return f.read()
    try:
        return common.fetch(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise NotFound(url) from e
        raise


def lag_ok(reg: dict, metric: str, obs: str, today: dt.date) -> bool:
    """The obs period has ended and the registry's release lag has passed."""
    return kpi.obs_range(obs)[1] + dt.timedelta(days=int(reg[metric]["release_lag_days"] or 0)) <= today


# --- World Bank / ITU ---------------------------------------------------------------------------
def parse_wb(text: str) -> list[tuple[str, str]]:
    """[(year, value)] of the non-null World records."""
    d = json.loads(text, parse_float=Decimal)
    if not (isinstance(d, list) and len(d) == 2 and isinstance(d[0], dict) and isinstance(d[1], list)):
        raise ValueError(f"{WB_URL}: unexpected answer {str(d)[:200]}")
    if int(d[0].get("pages", 1)) > 1:
        raise ValueError(f"{WB_URL}: paged answer ({d[0]['pages']} pages); refusing a partial series")
    if int(d[0].get("total", -1)) != len(d[1]):
        raise ValueError(f"{WB_URL}: {len(d[1])} records, the answer states total {d[0].get('total')}")
    out, years = [], set()
    for r in d[1]:
        if r["indicator"]["id"] != "IT.NET.USER.ZS" or r["countryiso3code"] != "WLD":
            raise ValueError(f"{WB_URL}: unexpected record {r}")
        year = str(int(r["date"]))
        if year in years:
            raise ValueError(f"{WB_URL}: year {year} twice")
        years.add(year)
        if r["value"] is not None:
            out.append((year, str(r["value"])))
    if not out:
        raise ValueError(f"{WB_URL}: no values")
    return sorted(out)


# --- Erdős problems -----------------------------------------------------------------------------
def parse_erdos(text: str) -> list[dict]:
    """Snapshots in file (commit) order: {at (UTC datetime), commit, total, solved, proved, disproved, other}."""
    rd = csv.DictReader(io.StringIO(text))
    need = {"commit", "date", "total_problems", "total_solved", "proved", "disproved", "solved"}
    if not need <= set(rd.fieldnames or []):
        raise ValueError(f"{ERDOS_URL}: header lacks {sorted(need - set(rd.fieldnames or []))}")
    out = []
    for r in rd:
        at = dt.datetime.strptime(r["date"], "%Y-%m-%d %H:%M:%S %z").astimezone(dt.timezone.utc)
        if out and at < out[-1]["at"]:
            raise ValueError(f"{ERDOS_URL}: snapshot {r['commit']} dated {r['date']} before the previous one")
        out.append({"at": at, "commit": r["commit"], "total": int(r["total_problems"]),
                    "solved": int(r["total_solved"]), "proved": int(r["proved"]),
                    "disproved": int(r["disproved"]), "other": int(r["solved"])})
    if not out:
        raise ValueError(f"{ERDOS_URL}: no snapshots")
    return out


def erdos_months(snaps: list[dict], today: dt.date, reg: dict) -> list[tuple[str, dict]]:
    """[(YYYY-MM, last snapshot by that month's end)] for complete months from FIRST_ERDOS_MONTH."""
    out = []
    y, m = map(int, FIRST_ERDOS_MONTH.split("-"))
    while True:
        obs = f"{y}-{m:02d}"
        if not lag_ok(reg, M_ERDOS, obs, today):
            return out
        end = dt.datetime.combine(kpi.obs_range(obs)[1], dt.time.max, dt.timezone.utc)
        upto = [s for s in snaps if s["at"] <= end]
        if upto:
            out.append((obs, upto[-1]))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# --- TOP500 ---------------------------------------------------------------------------------------
def parse_top500(text: str, url: str, edition: tuple[int, int]) -> tuple[Decimal, str]:
    """(rank-1 Rmax in PFlop/s, system name) of the list page of `edition` (year, month)."""
    title = re.search(r"<title>\s*(\w+) (\d{4}) \| TOP500", text)
    # month by its first 3 letters: the Nov 2015 page says "Novermber"
    if not title or (title[1][:3], int(title[2])) != (dt.date(*edition, 1).strftime("%b"), edition[0]):
        raise ValueError(f"{url}: not the {edition[0]}-{edition[1]:02d} list page (title {title[0] if title else None!r})")
    a = text.find('<table class="table table-condensed table-striped">')
    head = re.findall(r"<th>\s*(.*?)\s*</th>", text[a:text.find("</thead>", a)], re.S) if a >= 0 else []
    col = next((k for k, h in enumerate(head) if re.fullmatch(r"Rmax \([GTPE]Flop/s\)", h)), None)
    i = text.find("<td>1</td>", a)
    if col is None or i < 0 or head[:2] != ["Rank", "System"]:
        raise ValueError(f"{url}: no Rank/System/Rmax header or no rank-1 row (header {head})")
    cells = re.findall(r"<td[^>]*>(.*?)</td>", text[i:text.find("</tr>", i)], re.S)
    if len(cells) != len(head):
        raise ValueError(f"{url}: rank-1 row has {len(cells)} cells, the header {len(head)}")
    value = cells[col].strip().replace(",", "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", value):
        raise ValueError(f"{url}: rank-1 Rmax {cells[col]!r} is not a number")
    unit = TOP500_ERRATA.get(edition, (head[col][6], ""))[0]
    link = re.search(r'<a href="/system/\d+">(.*?)</a>', cells[1], re.S)
    name = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", link[1] if link else "")).strip(" ,")
    return Decimal(value) * TO_PFLOPS[unit], name


def top500_lists(today: dt.date, existing, refresh: bool = False) -> list[tuple[int, int]]:
    """Lists to fetch: from the latest one this collector put in the ledger (else, or with
    refresh, the first list) to the newest due by today."""
    have = sorted(r["obs"] for r in existing if r["metric"] == M_TOP500 and r["verification"] == "collector")
    start = tuple(map(int, have[-1].split("-"))) if have and not refresh else FIRST_TOP500
    return [(y, m) for y in range(start[0], today.year + 1) for m in (6, 11)
            if (y, m) >= start and dt.date(y, m, 1) <= today]


# --- NASA Exoplanet Archive ---------------------------------------------------------------------
def parse_exo(text: str, count_text: str) -> dict[int, int]:
    """{discovery year: planets}; count_text = the archive's own count(*) of the table."""
    rows = list(csv.DictReader(io.StringIO(text)))
    count = count_text.strip().splitlines()
    if len(count) != 2 or count[0] != "count(*)" or not count[1].isdigit():
        raise ValueError(f"{EXO_COUNT_URL}: unexpected answer {count_text[:200]!r}")
    if len(rows) != int(count[1]):
        raise ValueError(f"{EXO_URL}: {len(rows)} planets, the archive counts {count[1]}; truncated answer?")
    if not rows or set(rows[0]) != {"pl_name", "disc_year"}:
        raise ValueError(f"{EXO_URL}: unexpected answer {text[:200]!r}")
    if len(rows) < MIN_PLANETS:
        raise ValueError(f"{EXO_URL}: only {len(rows)} planets (< {MIN_PLANETS}); truncated answer?")
    names = [r["pl_name"] for r in rows]
    if len(set(names)) != len(names):
        raise ValueError(f"{EXO_URL}: duplicated pl_name")
    by_year: dict[int, int] = {}
    for r in rows:
        by_year[int(r["disc_year"])] = by_year.get(int(r["disc_year"]), 0) + 1
    return by_year


# --- Q-Day qubit gap (derived) -------------------------------------------------------------------
def sig3(x: Decimal) -> str:
    """Plain decimal to 3 significant digits, half-up (1020.4 -> '1020', 0.04166 -> '0.0417')."""
    return format(x.quantize(Decimal(1).scaleb(x.adjusted() - 2), rounding="ROUND_HALF_UP").normalize(), "f")


def qday_gap(existing) -> list[tuple[str, Decimal, dict, dict, dict]]:
    """[(obs, gap, changed input row, needed row, device row)] per obs date of either input."""
    eff = ledger.obs_as_of("", rows=list(existing))
    inputs = sorted((kpi.obs_range(r["obs"])[1], r["obs"], r) for (m, _), r in eff.items() if m in (M_NEEDED, M_DEVICE))
    out, best = [], {}
    for end, obs, r in inputs:
        cur = best.get(r["metric"])
        better = min if r["metric"] == M_NEEDED else max
        if cur is None or better(Decimal(r["value"]), Decimal(cur["value"])) != Decimal(cur["value"]):
            best[r["metric"]] = r
        if M_NEEDED in best and M_DEVICE in best:
            n, d = best[M_NEEDED], best[M_DEVICE]
            if Decimal(d["value"]) > 0:
                gap = (r["obs"], Decimal(n["value"]) / Decimal(d["value"]), r, n, d)
                if out and out[-1][0] == obs:
                    out[-1] = gap  # both inputs on one date: one row
                else:
                    out.append(gap)
    return out


def collect(fixture: str | None, today: dt.date, collector: str, existing=()) -> list[dict]:
    reg = common.registry(SECTION)
    rows = []

    def add(metric, obs, value, source, note):
        rows.append(common.row(reg, metric, obs, value, source, note, collector, str(today)))

    for year, value in parse_wb(fetch(WB_URL, fixture)):  # every complete year WDI has (revisions append)
        if int(year) < today.year:
                add(M_INTERNET, year, value, WB_URL,
                "World Bank WDI IT.NET.USER.ZS, World (WLD): individuals using the Internet, % of population (ITU data)")

    for obs, s in erdos_months(parse_erdos(fetch(ERDOS_URL, fixture)), today, reg):
        add(M_ERDOS, obs, common.round_half_up(Decimal(s["solved"]) * 100 / s["total"], 1), ERDOS_URL,
            f"{s['solved']} of {s['total']} problems solved ({s['proved']} proved, {s['disproved']} disproved, "
            f"{s['other']} otherwise solved) at snapshot {s['commit'][:12]} of {s['at']:%Y-%m-%d %H:%M} UTC, "
            f"the last by the end of {obs}")

    lists = top500_lists(today, existing, bool(os.environ.get("TOP500_REFRESH")))
    effective = ledger.obs_as_of("", rows=list(existing))
    prev = None  # (edition, Rmax) of the previous list: from this run, else the ledger
    for k, (y, m) in enumerate(lists):
        url, obs = TOP500_URL.format(y=y, m=m), f"{y}-{m:02d}"
        if k and not fixture:
            time.sleep(1)
        try:
            text = fetch(url, fixture, f"top500-{obs}.html")
        except NotFound:
            # only an edition never collected, due this month, may be missing (not released yet)
            if (M_TOP500, obs) not in effective and today < dt.date(y, m, 1) + dt.timedelta(days=31):
                continue
            raise
        rmax, name = parse_top500(text, url, (y, m))
        if prev is None:
            before = [o for (mt, o) in effective if mt == M_TOP500 and o < obs]
            prev = (max(before), Decimal(effective[(M_TOP500, max(before))]["value"])) if before else None
        if prev and not prev[1] <= rmax < 10 * prev[1]:
            raise ValueError(f"{url}: rank-1 Rmax {rmax} PFlop/s vs {prev[1]} on the {prev[0]} list "
                             "(the #1 never fell, nor grew 10x, between lists): a unit error? see TOP500_ERRATA")
        prev = (obs, rmax)
        erratum = TOP500_ERRATA.get((y, m), (None, ""))[1]
        add(M_TOP500, obs, format(rmax.normalize(), "f"), url,
            f"TOP500 {dt.date(y, m, 1):%B %Y} list, rank 1: {name}; HPL Rmax converted to PFlop/s"
            + (f" ({erratum})" if erratum else ""))

    for obs, gap, r, n, d in qday_gap(existing):
        rows.append(common.row(reg, M_GAP, obs, sig3(gap), r["source"],
                               f"derived: {n['value']} qubits needed ({M_NEEDED}@{n['obs']}, {n['source']}) / "
                               f"{d['value']} available ({M_DEVICE}@{d['obs']}, {d['source']})",
                               collector, str(today), published=max(n["published"], d["published"], obs[:10])))

    by_year = parse_exo(fetch(EXO_URL, fixture), fetch(EXO_COUNT_URL, fixture))
    total = 0
    for year in range(min(by_year), today.year + 1):
        total += by_year.get(year, 0)
        if lag_ok(reg, M_EXO, str(year), today):
            add(M_EXO, str(year), str(total), EXO_URL,
                f"NASA Exoplanet Archive pscomppars: confirmed planets with discovery year <= {year}, "
                f"counted in the archive as retrieved ({sum(by_year.values())} confirmed in all)")
    return rows


if __name__ == "__main__":
    sys.exit(common.main(SECTION, __file__, collect))
