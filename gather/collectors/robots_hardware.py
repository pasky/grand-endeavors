#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Robots/hardware KPI collector: a series derived from the section's ledger, no fetch.

Usage:  uv run gather/collectors/robots_hardware.py --out FILE [--today YYYY-MM-DD]

gp-deployments (derived from events)
  The number of deployment cases at work: (robot maker, customer organization) pairs documented
  by the section's effective events that carry a `deployment` case (ledger.deployment_roster: a
  case counts from its first `working` event's publication until an `ended` or `disputed`
  event is published, and again after a later `working` one). One row per complete month from
  START (obs = the month, value = the cases at work by its end) and one per day the series was
  derived on (obs = that day: the current count, so the headline is today's, not last month's;
  each earlier day point is re-derived on every run, so revisions reach it too). source = the
  ledger's events file (the derivation's input); note = the cases added/removed in the month,
  their event ids, the total and a fingerprint of the known event history (roster_state: a
  replay is a no-op, a new history appends even a value seen before).
  Events are taken as of the run (--today): no later correction applies.
  No case ever counted: no rows. Once the series exists, every point always has a row (zeros
  too, if the roster empties), so a change in the roster (a backfilled earlier case, a
  correction, a superseded or withdrawn event) only ever REVISES values, never withdraws one.
  Dating: published by the registry rule (period end + 0 days, capped at retrieval: a point's
  count uses only events published by then); a value that revises the effective one is dated
  first seen (common.mark_revisions), so as-of views keep what the ledger knew then.
  The events are staged by gather intake per the metric's registry definition (the counting
  rules) and checked by the verifier; gather.sh re-runs this collector after merging intake,
  so new cases reach the series in the same run.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys

import common
import kpi
import ledger

SECTION = "robots-hardware"
M_DEPLOY = "gp-deployments"
START = "2023-01"   # the series starts here (the KPI's backfill window); earlier cases count from it
SOURCE = "https://github.com/pasky/grand-endeavors-data/blob/main/ledger/events/robots-hardware.jsonl"


def months(start: str, today: dt.date) -> list[str]:
    y, m = int(start[:4]), int(start[5:])
    out = []
    while (y, m) <= (today.year, today.month):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def roster_state(known: list[dict]) -> str:
    """A fingerprint of the derivation's input HISTORY: the ids of the known events that carry a
    deployment case or supersede one (corrections, withdrawals). The ledger is append-only, so
    the history only grows: rows derived from the same history are identical (a replay is a
    no-op), and any change gives a new note, so a revision equal to an earlier, since displaced
    one is still appended (merge's exact-replay test would otherwise drop it)."""
    dep = {e["id"] for e in known if isinstance(e.get("deployment"), dict)}
    ids = sorted(e["id"] for e in known if e["id"] in dep or set(e.get("supersedes") or ()) & dep)
    return hashlib.sha256(json.dumps(ids).encode()).hexdigest()[:12]


def pair_rows(reg: dict, events: list[dict], collector: str, today: dt.date, existing=()) -> list[dict]:
    """existing: the section's ledger rows; once the series exists, every point keeps a row
    (zeros included) even if the roster empties, so the last count cannot stay effective."""
    known = [e for e in events if ledger.known_at(e) <= today]   # as of the run: no later correction
    eff = ledger.effective_events(known)
    _, timeline = ledger.deployment_roster(eff)
    if not timeline and not any(r["metric"] == M_DEPLOY for r in existing):
        return []   # no case ever counted: no series yet (not a run of zeros to revise later)
    state = roster_state(known)
    count_by = lambda d: next((t["count"] for t in reversed(timeline) if t["date"] <= d), 0)
    rows = []
    for mo in months(START, today):
        end = str(kpi.obs_range(mo)[1])
        if end > str(today):
            break   # the month in progress: today's day point below
        changes = [t for t in timeline if t["date"][:7] == mo]
        added = [x for t in changes for x in t["added"]]
        removed = [x for t in changes for x in t["removed"]]
        ids = [x for t in changes for x in t["events"]]
        what = "; ".join(filter(None, [("+ " + ", + ".join(added)) if added else "",
                                       ("- " + ", - ".join(removed)) if removed else ""]))
        note = (f"derived from the ledger's deployment cases: {count_by(end)} at work by {end}"
                + (f" ({what}: {', '.join(ids)})" if changes else "") + f"; roster {state}")
        rows.append(common.row(reg, M_DEPLOY, mo, str(count_by(end)), SOURCE, note, collector, str(today)))
    days = {r["obs"] for r in existing if r["metric"] == M_DEPLOY and len(r["obs"]) == 10} | {str(today)}
    for d in sorted(x for x in days if x <= str(today)):
        note = f"derived from the ledger's deployment cases: {count_by(d)} at work on {d}; roster {state}"
        rows.append(common.row(reg, M_DEPLOY, d, str(count_by(d)), SOURCE, note, collector, str(today)))
    return rows


def collect(fixture: str | None, today: dt.date, collector: str, existing=(), events=None) -> list[dict]:
    reg = common.registry(SECTION)
    return pair_rows(reg, ledger.events(SECTION) if events is None else events, collector, today, existing)


if __name__ == "__main__":
    sys.exit(common.main(SECTION, __file__, collect, allow_empty=True))
