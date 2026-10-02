"""Shared plumbing for the deterministic KPI collectors (DESIGN.md §4 step 2).

A collector fetches machine-readable primary sources, parses them without any
LLM, and writes a *staged* observations CSV (header exactly ledger.OBS_COLUMNS)
that `ledger.py merge <section> --obs <file>` admits (verification=collector).

Time semantics (DESIGN.md §2), applied by `row()`:
  - retrieved = today (UTC date, overridable with --today for reproducibility);
  - published = obs end + registry release_lag_days, capped at retrieved
    (ledger.rule_published, basis=rule) when the registry gives a lag;
    otherwise published = retrieved (basis=seen);
  - a collector may pass an explicit source-stated date (basis=source);
  - revisions (`mark_revisions`): each staged value is compared with the
    EFFECTIVE ledger row for its (metric, obs) (ledger.obs_as_of: non-legacy rows
    outrank legacy ones regardless of dates, then the latest known wins), not
    with every historical value:
      * equal to an effective non-legacy row -> unchanged; the rule-basis date is
        kept and `ledger.py merge` dedups the row (no-op);
      * different from an effective non-legacy row -> a source REVISION (including
        a revert to an earlier value): it became known when we first saw it, so a
        rule-basis date (the original release) becomes basis=seen, published=retrieved;
      * the effective row is legacy (only report-extracted rows exist) -> the
        collector value IS the primary-source value, not a revision: it keeps its
        rule/source date (the original release), which is when that number was
        actually public. It outranks the legacy row by tier whatever the dates
        (the legacy value was a report's transcription, not a separate source
        vintage); committed bulletin snapshots are frozen, so this changes no
        published bulletin, only as-of views/re-runs, which then show the
        primary value from its release date. If the legacy value differed, the
        note says so (for the audit trail).
    Only rule-basis dates are re-dated: a source-stated date is the source's own
    (revision) date, and seen-basis rows are already dated first-seen.

CLI shared by all collectors:  <collector>.py --out FILE [--fixture DIR] [--today YYYY-MM-DD]
  --fixture DIR  read each source from DIR/<basename of its URL> instead of the network.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import sys
import urllib.request
from decimal import ROUND_HALF_UP, Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the mechanism repo
sys.path.insert(0, os.path.join(ROOT, "core"))
import kpi  # noqa: E402
import ledger  # noqa: E402

USER_AGENT = "grand-endeavors-collector/1 (python-urllib)"


def fetch(url: str, fixture_dir: str | None = None) -> str:
    """Text of `url`, or of fixture_dir/<basename(url)> when a fixture dir is given."""
    if fixture_dir:
        with open(os.path.join(fixture_dir, url.rsplit("/", 1)[-1]), encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def round_half_up(x: Decimal | float | str, places: int) -> str:
    """Plain-decimal string rounded half-up (not banker's / binary-float rounding)."""
    q = Decimal(1).scaleb(-places)
    return str(Decimal(str(x)).quantize(q, rounding=ROUND_HALF_UP))


def registry(section: str) -> dict[str, dict]:
    reg, errs = kpi.load_registry(section)
    if errs or not reg:
        raise SystemExit(f"metric registry for {section} is broken: {errs}")
    return reg


def row(reg: dict, metric: str, obs: str, value: str, source: str, note: str,
        collector: str, retrieved: str, published: str | None = None) -> dict:
    """One staged observation; publication date per the rules in the module docstring."""
    lag = reg[metric]["release_lag_days"]
    if published:
        basis = "source"
    elif lag:
        published, basis = ledger.rule_published(obs, lag, retrieved), "rule"
    else:
        published, basis = retrieved, "seen"
    return {"metric": metric, "obs": obs, "value": value, "unit": reg[metric]["unit"],
            "source": source, "published": published, "published_basis": basis,
            "retrieved": retrieved, "collector": collector, "verification": "collector",
            "note": note}


def is_revision(r: dict, eff: dict | None) -> bool:
    """Staged row `r` revises the effective ledger row `eff` (see module doc)."""
    return (eff is not None and ledger.tier(eff) > 0
            and Decimal(r["value"]) != Decimal(eff["value"]))


def mark_revisions(rows: list[dict], existing: list[dict]) -> list[dict]:
    """Re-date rule-basis rows that revise the EFFECTIVE ledger value (see module doc).
    `existing` = the section's ledger rows (ledger.observations)."""
    effective = ledger.obs_as_of("", rows=list(existing))
    out = []
    for r in rows:
        eff = effective.get((r["metric"], r["obs"]))
        if is_revision(r, eff) and r["published_basis"] == "rule":
            r = dict(r, published=r["retrieved"], published_basis="seen",
                     note=r["note"] + f"; revises effective ledger value {eff['value']}"
                                      f" ({eff['verification']}, published {eff['published']})"
                                      " (published = first seen)")
        elif eff is not None and ledger.tier(eff) == 0 and Decimal(r["value"]) != Decimal(eff["value"]):
            r = dict(r, note=r["note"] + f"; primary-source value, outranks legacy report value {eff['value']}")
        out.append(r)
    return out


def check(rows: list[dict], reg: dict) -> list[str]:
    """ledger.check_obs_row errors for all rows (empty = mergeable)."""
    errs = []
    for i, r in enumerate(rows, 2):
        errs += ledger.check_obs_row(dict(r, _line=i), reg, staged=True)
    return errs


def write(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ledger.OBS_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(section: str, script: str, collect) -> int:
    """Standard CLI: collect(fixture_dir, today, collector_id, existing_ledger_rows) -> rows;
    mark revisions against the ledger; validate; write."""
    ap = argparse.ArgumentParser(description=sys.modules["__main__"].__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="staged observations CSV to write")
    ap.add_argument("--fixture", help="read sources from this directory (offline)")
    ap.add_argument("--today", default=str(dt.datetime.now(dt.timezone.utc).date()),
                    help="retrieval date (default: today, UTC)")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today)
    existing = ledger.observations(section)
    # collector id "collectors/<script>@<date>" is stored in ledger rows: a stable id, not a path
    rows = collect(a.fixture, today, f"collectors/{os.path.basename(script)}@{today}", existing)
    rows = mark_revisions(rows, existing)
    errs = check(rows, registry(section))
    for e in errs:
        print(f"  ERROR {e}", file=sys.stderr)
    if errs or not rows:
        print(f"{section}: {'no rows' if not rows else f'{len(errs)} error(s)'}; nothing written", file=sys.stderr)
        return 1
    write(a.out, rows)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["metric"]] = counts.get(r["metric"], 0) + 1
    print(f"{section}: wrote {len(rows)} rows to {a.out} "
          + ", ".join(f"{m}={n}" for m, n in counts.items()))
    return 0
