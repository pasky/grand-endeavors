#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Robots/hardware KPI collector: a series derived from the section's ledger, no fetch.

Usage:  uv run gather/collectors/robots_hardware.py --out FILE [--today YYYY-MM-DD]

gp-deployment-pairs (derived from events)
  The cumulative number of counted deployment cases, (robot maker, customer organization)
  pairs documented by the section's effective events that carry a `deployment` case
  (ledger.deployment_roster: a case counts from its first `working` event's publication, and
  not while it is disputed). Monthly: one row per month from START to the current month (the
  current one in progress), value = the cases counted among the events published by the month's
  end (or today), source = the ledger's events file (the derivation's input), note = the cases
  added/removed that month with their event ids and the total.
  No case ever counted: no rows. Once there is one, every month always has a row, so a change in the roster (a backfilled earlier case, a
  correction, a superseded or withdrawn event) only ever REVISES values, never withdraws one.
  Dating: published by the registry rule (month end + 0 days, capped at retrieval: a month's
  count uses only events published by then); a value that revises the effective one is dated
  first seen (common.mark_revisions), so as-of views keep what the ledger knew then.
  The events are staged by gather intake per the metric's registry definition (the counting
  rules) and checked by the verifier; gather.sh re-runs this collector after merging intake,
  so new cases reach the series in the same run.
"""
from __future__ import annotations

import datetime as dt
import sys

import common
import kpi
import ledger

SECTION = "robots-hardware"
M_PAIRS = "gp-deployment-pairs"
START = "2023-01"   # the series starts here (the KPI's backfill window); earlier cases count from it
SOURCE = "https://github.com/pasky/grand-endeavors-data/blob/main/ledger/events/robots-hardware.jsonl"


def months(start: str, today: dt.date) -> list[str]:
    y, m = int(start[:4]), int(start[5:])
    out = []
    while (y, m) <= (today.year, today.month):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def pair_rows(reg: dict, events: list[dict], collector: str, today: dt.date) -> list[dict]:
    eff = ledger.effective_events(events)
    _, timeline = ledger.deployment_roster(eff)
    if not timeline:   # no case ever counted: no series yet (not a run of zeros to revise later)
        return []
    rows, count = [], 0
    for mo in months(START, today):
        end = str(min(kpi.obs_range(mo)[1], today))
        changes = [t for t in timeline if t["date"][:7] == mo and t["date"] <= end]
        before = count
        count = next((t["count"] for t in reversed(timeline) if t["date"] <= end), 0)
        added = [x for t in changes for x in t["added"]]
        removed = [x for t in changes for x in t["removed"]]
        ids = [x for t in changes for x in t["events"]]
        what = "; ".join(filter(None, [("+ " + ", + ".join(added)) if added else "",
                                       ("- " + ", - ".join(removed)) if removed else ""]))
        note = (f"derived from the ledger's deployment cases: {count} counted by {end}"
                + (f" ({before} before; {what}: {', '.join(ids)})" if changes else ""))
        rows.append(common.row(reg, M_PAIRS, mo, str(count), SOURCE, note, collector, str(today)))
    return rows


def collect(fixture: str | None, today: dt.date, collector: str, existing=(), events=None) -> list[dict]:
    reg = common.registry(SECTION)
    return pair_rows(reg, ledger.events(SECTION) if events is None else events, collector, today)


if __name__ == "__main__":
    sys.exit(common.main(SECTION, __file__, collect, allow_empty=True))
