#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Robots/hardware KPI collector: a series derived from the section's ledger, no fetch.

Usage:  uv run gather/collectors/robots_hardware.py --out FILE [--today YYYY-MM-DD]

gp-deployment-pairs (derived from events)
  The cumulative number of counted deployment cases: (robot maker, customer organization)
  pairs documented by the section's effective events that carry a `deployment` case
  (ledger.deployment_roster: a case counts from its first `working` event's publication, and
  stops counting while its latest event is `disputed`). One row per publication date on which
  the count changed: obs = that date, value = the count after it, source = the first source of
  the date's last changing event, note = the cases added/removed and their event ids.
  The events are staged by gather intake per the metric's registry definition (the counting
  rules) and checked by the verifier; gather.sh re-runs this collector after merging intake,
  so new cases reach the series in the same run.
  Dating: published = the latest publication date of the date's changing events (basis
  source); a first-seen event makes the row first-seen (published = retrieved). An obs date
  whose effective value differs (an earlier-published case added later, a correction) is a
  revision dated first seen; an effective obs the roster no longer produces (its events
  superseded or withdrawn) gets a withdrawal record.
"""
from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal

import common
import ledger

SECTION = "robots-hardware"
M_PAIRS = "gp-deployment-pairs"


def pair_rows(reg: dict, events: list[dict], existing, collector: str, today: dt.date) -> list[dict]:
    eff = ledger.obs_as_of("", rows=list(existing))
    byid = {e["id"]: e for e in events}
    _, timeline = ledger.deployment_roster(ledger.effective_events(events))
    rows, want = [], set()
    for t in timeline:
        obs, value = t["date"], str(t["count"])
        want.add(obs)
        evs = [byid[i] for i in t["events"]]
        note = "; ".join(filter(None, [
            ("+ " + ", + ".join(t["added"])) if t["added"] else "",
            ("- " + ", - ".join(t["removed"]) + " (disputed)") if t["removed"] else ""]))
        note = f"derived from events: {note} ({', '.join(t['events'])})"
        cur = eff.get((M_PAIRS, obs))
        if cur is not None and Decimal(cur["value"]) != Decimal(value):
            published, note = None, note + f"; revises {cur['value']} (the roster changed; published = first seen)"
        elif any(e["published_basis"] == "seen" for e in evs):
            published = None
        else:
            published = min(max(e["published"] for e in evs), str(today))
        rows.append(common.row(reg, M_PAIRS, obs, value, evs[-1]["sources"][0]["url"], note, collector,
                               str(today), published=published))
    for (m, obs), cur in sorted(eff.items()):
        if m == M_PAIRS and obs not in want:
            rows.append(dict(common.row(reg, M_PAIRS, obs, cur["value"], cur["source"],
                                        "withdrawn: the roster no longer changes on this date "
                                        "(its events were superseded or withdrawn)", collector, str(today)),
                             verification="withdrawn"))
    return rows


def collect(fixture: str | None, today: dt.date, collector: str, existing=(), events=None) -> list[dict]:
    reg = common.registry(SECTION)
    return pair_rows(reg, ledger.events(SECTION) if events is None else events, existing, collector, today)


if __name__ == "__main__":
    # no cases yet is a valid result (an empty staged file, nothing to merge)
    sys.exit(common.main(SECTION, __file__, collect, allow_empty=True))
