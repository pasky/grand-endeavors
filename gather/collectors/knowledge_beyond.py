#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Knowledge Beyond indicator collector (a supplemental section: tracked, never assessed).

Usage:  uv run gather/collectors/knowledge_beyond.py --out FILE [--fixture DIR] [--today YYYY-MM-DD]

Four machine-readable sources; the section's other indicators (Q-Day qubits, connectome,
superconducting Tc) have no feed and are staged by gather intake. Any source failing
fails the run (nothing is written), so a broken source is never silently skipped.

internet-users-world-share
  World Bank WDI API, indicator IT.NET.USER.ZS ("Individuals using the Internet (% of
  population)", World = WLD; the data are ITU's), WB_URL. JSON [meta, [records]]; a paged
  answer (pages > 1) is an error. value = the record's number verbatim; obs = its year.
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
  arithmetic. obs = the list month. Fetched: every list from the latest one already in
  the ledger (re-checked for revisions) up to the newest list due by today, or all of
  them on the first run (1 s apart); only the newest candidate may be missing (404: not
  released yet, e.g. early June). published: rule (list month end + lag; the pages state
  no date, the lists come out mid-month, so this is a late upper estimate, capped at
  retrieval).

exoplanets-confirmed
  NASA Exoplanet Archive TAP, Planetary Systems Composite table (pscomppars = one row per
  confirmed planet), EXO_URL: pl_name, disc_year. value = planets with disc_year <= obs
  year, counted in the current archive; complete years only (Dec 31 + lag passed). A
  planet added later with an earlier discovery year, or a retracted one, revises the
  count (appended as a revision). Guards: fewer than MIN_PLANETS rows (truncation) or a
  duplicated pl_name is an error. published: rule.

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

SECTION = "knowledge-beyond"
WB_URL = "https://api.worldbank.org/v2/country/WLD/indicator/IT.NET.USER.ZS?format=json&per_page=200"
ERDOS_URL = "https://raw.githubusercontent.com/teorth/erdosproblems/main/data/statistics_history.csv"
EXO_URL = ("https://exoplanetarchive.ipac.caltech.edu/TAP/sync"
           "?query=select+pl_name,disc_year+from+pscomppars&format=csv")
TOP500_URL = "https://top500.org/lists/top500/{y}/{m:02d}/"
FIXTURES = {WB_URL: "wb_internet_users.json", ERDOS_URL: "statistics_history.csv",
            EXO_URL: "exoplanets_pscomppars.csv"}
M_INTERNET, M_ERDOS = "internet-users-world-share", "erdos-problems-solved-share"
M_TOP500, M_EXO = "top500-top-rmax", "exoplanets-confirmed"
FIRST_ERDOS_MONTH = "2025-09"
FIRST_TOP500 = (1993, 6)
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
    out = []
    for r in d[1]:
        if r["indicator"]["id"] != "IT.NET.USER.ZS" or r["countryiso3code"] != "WLD":
            raise ValueError(f"{WB_URL}: unexpected record {r}")
        if r["value"] is not None:
            out.append((str(int(r["date"])), str(r["value"])))
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
def parse_top500(text: str, url: str) -> tuple[Decimal, str]:
    """(rank-1 Rmax in PFlop/s, system name) of a list page."""
    unit = re.search(r"<th>\s*Rmax \(([GTPE])Flop/s\)\s*</th>", text)
    i = text.find("<td>1</td>")
    if not unit or i < 0:
        raise ValueError(f"{url}: no Rmax column or no rank-1 row")
    row = text[i:text.find("</tr>", i)]
    nums = re.findall(r'<td style="text-align: right;">\s*([\d,]+(?:\.\d+)?)\s*</td>', row)
    if len(nums) < 3:  # cores, Rmax, Rpeak
        raise ValueError(f"{url}: rank-1 row has {len(nums)} numeric cells, expected cores, Rmax, Rpeak")
    link = re.search(r'<a href="/system/\d+">(.*?)</a>', row, re.S)
    name = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", link[1] if link else "")).strip(" ,")
    return Decimal(nums[1].replace(",", "")) * TO_PFLOPS[unit[1]], name


def top500_lists(today: dt.date, existing) -> list[tuple[int, int]]:
    """Lists to fetch: from the latest one in the ledger (else the first list) to the newest due by today."""
    have = sorted(r["obs"] for r in existing if r["metric"] == M_TOP500 and r["verification"] != "withdrawn")
    start = tuple(map(int, have[-1].split("-"))) if have else FIRST_TOP500
    return [(y, m) for y in range(start[0], today.year + 1) for m in (6, 11)
            if (y, m) >= start and dt.date(y, m, 1) <= today]


# --- NASA Exoplanet Archive ---------------------------------------------------------------------
def parse_exo(text: str) -> dict[int, int]:
    """{discovery year: planets}."""
    rows = list(csv.DictReader(io.StringIO(text)))
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


def collect(fixture: str | None, today: dt.date, collector: str, existing=()) -> list[dict]:
    reg = common.registry(SECTION)
    rows = []

    def add(metric, obs, value, source, note):
        rows.append(common.row(reg, metric, obs, value, source, note, collector, str(today)))

    for year, value in parse_wb(fetch(WB_URL, fixture)):  # every year WDI has (revisions append)
        add(M_INTERNET, year, value, WB_URL,
            "World Bank WDI IT.NET.USER.ZS, World (WLD): individuals using the Internet, % of population (ITU data)")

    for obs, s in erdos_months(parse_erdos(fetch(ERDOS_URL, fixture)), today, reg):
        add(M_ERDOS, obs, common.round_half_up(Decimal(s["solved"]) * 100 / s["total"], 1), ERDOS_URL,
            f"{s['solved']} of {s['total']} problems solved ({s['proved']} proved, {s['disproved']} disproved, "
            f"{s['other']} otherwise solved) at snapshot {s['commit'][:12]} of {s['at']:%Y-%m-%d %H:%M} UTC, "
            f"the last by the end of {obs}")

    lists = top500_lists(today, existing)
    for k, (y, m) in enumerate(lists):
        url = TOP500_URL.format(y=y, m=m)
        if k and not fixture:
            time.sleep(1)
        try:
            text = fetch(url, fixture, f"top500-{y}-{m:02d}.html")
        except NotFound:
            if k == len(lists) - 1:
                continue  # the newest list is not out yet
            raise
        rmax, name = parse_top500(text, url)
        add(M_TOP500, f"{y}-{m:02d}", format(rmax.normalize(), "f"), url,
            f"TOP500 {dt.date(y, m, 1):%B %Y} list, rank 1: {name}; HPL Rmax converted to PFlop/s")

    by_year = parse_exo(fetch(EXO_URL, fixture))
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
