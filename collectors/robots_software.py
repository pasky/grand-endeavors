#!/usr/bin/env python3
"""Robots/software KPI collector: METR time-horizon benchmark -> frontier series.

Usage:  uv run collectors/robots_software.py --out FILE [--fixture DIR] [--today YYYY-MM-DD]

Source: https://metr.org/assets/benchmark_results_1_1.yaml, the data file behind
https://metr.org/time-horizons/ ("Time Horizon 1.1 (Current)"). The older URL
assets/benchmark_results.yaml is gone (404); TH 1.0 lives at benchmark_results_1_0.yaml.
Format (YAML, parsed line-wise by `yaml_paths`, no dependency):
    benchmark_name: METR-Horizon-v1.1
    results:
      <model_id>:
        benchmark_name: METR-Horizon-v1.x   (older models carried over from v1.0)
        metrics:
          p50_horizon_length: {ci_high, ci_low, estimate}   minutes
          p80_horizon_length: {ci_high, ci_low, estimate}   minutes
        release_date: YYYY-MM-DD
        scaffolds: [...]

Output: metr-50-horizon-frontier / metr-80-horizon-frontier, one row per date on
which the frontier (highest point estimate of any model in the file) improved.
Choices:
  - obs = the model's release_date (YYYY-MM-DD). The file has no evaluation or
    publication date, so the series answers "best horizon among models released
    by that date", computed from the current file vintage (METR re-estimates
    earlier models when the task suite changes; re-runs then append revisions).
  - Frontiers are computed independently for p50 and p80 (METR's is_sota flag
    tracks p50 only). Ties on one date keep the higher estimate.
  - value = point estimate rounded half-up to 2 decimals (minutes); the note
    names the model, its per-model benchmark version and the CI.
  - published: registry has no release lag -> basis=seen (published = retrieved).
"""
from __future__ import annotations

import datetime as dt
import re
import sys

import common

SECTION = "robots-software"
URL = "https://metr.org/assets/benchmark_results_1_1.yaml"
METRICS = {"p50": "metr-50-horizon-frontier", "p80": "metr-80-horizon-frontier"}


def yaml_paths(text: str) -> dict[tuple[str, ...], str]:
    """Flat {(key, subkey, ...): scalar} of a block-mapping YAML; list items are ignored."""
    out: dict[tuple[str, ...], str] = {}
    stack: list[tuple[int, str]] = []
    for ln in text.splitlines():
        ln = re.sub(r"(^|\s)#.*$", "", ln).rstrip()
        m = re.match(r"^( *)([^\s:#-][^:]*):(?:\s+(.*))?$", ln)
        if not m:
            continue  # blank, comment or list item
        ind = len(m[1])
        while stack and stack[-1][0] >= ind:
            stack.pop()
        stack.append((ind, m[2].strip()))
        if m[3] is not None:
            out[tuple(k for _, k in stack)] = m[3].strip().strip("'\"")
    return out


def models(text: str) -> tuple[str, list[dict]]:
    """(benchmark name, [{id, release, benchmark, p50: {...}, p80: {...}}])."""
    p = yaml_paths(text)
    if "benchmark_name" not in {k[0] for k in p} or not any(k[0] == "results" for k in p):
        raise SystemExit(f"{URL}: not a METR benchmark results file (missing benchmark_name/results)")
    out = []
    for mid in sorted({k[1] for k in p if k[0] == "results" and len(k) > 2}):
        r = ("results", mid)
        m = {"id": mid, "release": p.get(r + ("release_date",)), "benchmark": p.get(r + ("benchmark_name",), "")}
        for q in METRICS:
            h = r + ("metrics", f"{q}_horizon_length")
            if h + ("estimate",) in p:
                m[q] = {k: float(p[h + (k,)]) for k in ("estimate", "ci_low", "ci_high") if h + (k,) in p}
        if m["release"]:
            dt.date.fromisoformat(m["release"])  # malformed date -> fail loudly
            out.append(m)
    return p[("benchmark_name",)], out


def frontier(ms: list[dict], q: str) -> list[dict]:
    """Models that set a new frontier for quantile q, in release order."""
    best, out = None, []
    for m in sorted((m for m in ms if q in m), key=lambda m: (m["release"], -m[q]["estimate"], m["id"])):
        if best is None or m[q]["estimate"] > best:
            best = m[q]["estimate"]
            out.append(m)
    return out


def collect(fixture: str | None, today: dt.date, collector: str) -> list[dict]:
    reg = common.registry(SECTION)
    bench, ms = models(common.fetch(URL, fixture))
    rows = []
    for q, metric in METRICS.items():
        for m in frontier(ms, q):
            e = m[q]
            ci = f"; CI {e['ci_low']:.2f}-{e['ci_high']:.2f} min" if "ci_low" in e and "ci_high" in e else ""
            note = (f"new {q} frontier: {m['id']} ({m['benchmark'] or bench}{ci}); obs = model release_date "
                    f"in METR's {bench} results file (no evaluation date in the file)")
            rows.append(common.row(reg, metric, m["release"], common.round_half_up(e["estimate"], 2),
                                   URL, note, collector, str(today)))
    return rows


if __name__ == "__main__":
    sys.exit(common.main(SECTION, __file__, collect))
