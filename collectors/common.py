"""Shared plumbing for the deterministic KPI collectors (DESIGN.md §4 step 2).

A collector fetches machine-readable primary sources, parses them without any
LLM, and writes a *staged* observations CSV (header exactly ledger.OBS_COLUMNS)
that `ledger.py merge <section> --obs <file>` admits (verification=collector).

Time semantics (DESIGN.md §2), applied by `row()`:
  - retrieved = today (UTC date, overridable with --today for reproducibility);
  - published = obs end + registry release_lag_days, capped at retrieved
    (ledger.rule_published, basis=rule) when the registry gives a lag;
    otherwise published = retrieved (basis=seen);
  - a collector may pass an explicit source-stated date (basis=source).

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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
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
    """Standard CLI: collect(fixture_dir, today, collector_id) -> rows; validate; write."""
    ap = argparse.ArgumentParser(description=sys.modules["__main__"].__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="staged observations CSV to write")
    ap.add_argument("--fixture", help="read sources from this directory (offline)")
    ap.add_argument("--today", default=str(dt.datetime.now(dt.timezone.utc).date()),
                    help="retrieval date (default: today, UTC)")
    a = ap.parse_args()
    today = dt.date.fromisoformat(a.today)
    rows = collect(a.fixture, today, f"collectors/{os.path.basename(script)}@{today}")
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
