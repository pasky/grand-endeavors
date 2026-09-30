#!/usr/bin/env python3
"""KPI metrics: registry, time parsing, number matching, and charts rendered
from the ledger (DESIGN.md §2-3). Observations live in ledger/observations/;
this module no longer holds per-period vintage files.

METRIC REGISTRY (the continuity contract; one per section, across periods)
    metrics/<section>.csv   columns: metric,unit,cadence,release_lag_days,required_from,retired_after,definition
    cadence: daily|weekly|monthly|quarterly|annual|irregular. release_lag_days: typical
    days from the end of the observed period to publication (empty = no regular
    release); drives rule-basis publication dates and "expected by" in views.
    definition = the exact measure, basis/station/scope and window, so "same id"
    provably means "same measure". required_from=<period>: from then on bulletins
    must report it (KPI components). retired_after=<period>: not reported after
    that period (a basis change = new id + retire the old one; NEVER redefine).

OBS LABELS  YYYY | YYYY-MM | YYYY-MM-DD | YYYY-Qn | YYYY-Hn
PERIODS     dir name minus "pilot-": 2025, 26H1, 2026-Q2, 2026-06, 2026-W26

COMMANDS
    kpi.py registry <section>        registered metrics with definitions (for agent prompts)
    kpi.py chart <period-dir> <section> <metric>[,<metric>...] [--match GLOB] [--since YYYY]
                 [--label obs|year] [--title T]
        mermaid xychart of the ledger AS OF the period's bulletin cutoff (latest
        known row per obs; obs within the period end). The block carries a
        "%% kpi: ..." marker; validate.py re-renders marked charts and fails on drift.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import fnmatch
import glob
import os
import re
import shlex
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
REG_COLUMNS = ["metric", "unit", "cadence", "release_lag_days", "required_from", "retired_after", "definition"]
CADENCES = {"daily", "weekly", "monthly", "quarterly", "annual", "irregular"}
METRIC_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
VALUE_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
MARKER_RE = re.compile(r"^\s*%%\s*kpi:\s*(.+)$", re.M)


# --- time parsing -------------------------------------------------------------
def _month_end(y: int, m: int) -> dt.date:
    return dt.date(y, m, calendar.monthrange(y, m)[1])


def period_as_of(period: str) -> dt.date:
    """As-of (end) date of a reporting period name (dir name minus 'pilot-')."""
    p = period
    if m := re.fullmatch(r"(\d{4})", p):
        return dt.date(int(m[1]), 12, 31)
    if m := re.fullmatch(r"(\d{2})H([12])", p):
        return _month_end(2000 + int(m[1]), 6 * int(m[2]))
    if m := re.fullmatch(r"(\d{4})-Q([1-4])", p):
        return _month_end(int(m[1]), 3 * int(m[2]))
    if m := re.fullmatch(r"(\d{4})-(\d{2})", p):
        return _month_end(int(m[1]), int(m[2]))
    if m := re.fullmatch(r"(\d{4})-W(\d{2})", p):
        return dt.date.fromisocalendar(int(m[1]), int(m[2]), 7)
    raise ValueError(f"unrecognized period '{period}'")


def obs_range(obs: str) -> tuple[dt.date, dt.date]:
    """(start, end) dates of an observation label; ValueError if malformed."""
    if m := re.fullmatch(r"(\d{4})", obs):
        y = int(m[1]); return dt.date(y, 1, 1), dt.date(y, 12, 31)
    if m := re.fullmatch(r"(\d{4})-(\d{2})", obs):
        y, mo = int(m[1]), int(m[2]); return dt.date(y, mo, 1), _month_end(y, mo)
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", obs):
        d = dt.date(int(m[1]), int(m[2]), int(m[3])); return d, d
    if m := re.fullmatch(r"(\d{4})-([QH])(\d)", obs):
        y, k, n = int(m[1]), m[2], int(m[3])
        span = 3 if k == "Q" else 6
        if not 1 <= n <= 12 // span:
            raise ValueError(obs)
        return dt.date(y, span * (n - 1) + 1, 1), _month_end(y, span * n)
    raise ValueError(f"malformed obs '{obs}'")


def obs_kind(obs: str) -> str:
    return re.sub(r"\d", "9", obs)  # 'YYYY-MM' -> '9999-99': same granularity check


def period_of_dir(period_dir: str) -> str:
    return os.path.basename(os.path.normpath(period_dir)).removeprefix("pilot-")


# --- loading ------------------------------------------------------------------
# --- KPI-specific number matching -------------------------------------------------
# Unlike validate.numbers() (round-up prose), KPI values keep their sign (ASCII
# '-' or U+2212 minus; a hyphen glued to a preceding digit, as in "2016-2025", is
# a range, not a sign) and year-like integers are NOT dropped ($2000/kg is data).
KPI_NUM_RE = re.compile(
    r"(?<![\w.])[-\u2212]?(?:\d{1,3}(?:[,\u2009\u202f ]\d{3})+|\d+)(?:\.\d+)?(?![\d]|[.,]\d)"
)


def kpi_numbers(text: str) -> set[float]:
    text = re.sub(r"https?://\S+", " ", text)  # URLs are not claims
    return {float(re.sub(r"[,\u2009\u202f ]", "", m).replace("\u2212", "-"))
            for m in KPI_NUM_RE.findall(text)}


def kpi_traceable(value: str, pool: set[float]) -> bool:
    """Signed match. A negative value may also match its unsigned magnitude
    (prose says "fell 0.5%"); a positive value never matches a negative."""
    v = float(value)
    return v in pool or (v < 0 and -v in pool)


# --- check --------------------------------------------------------------------
def _period_date(name: str) -> dt.date:
    return period_as_of(name.removeprefix("pilot-"))


def registry_path(section: str) -> str:
    import ledger  # ledger.DATA is the single source of truth for the data repo location
    return os.path.join(ledger.DATA, "metrics", f"{section}.csv")


def load_registry(section: str) -> tuple[dict[str, dict] | None, list[str]]:
    """({metric: row} or None if no registry file, errors). Rows get parsed
    '_req'/'_ret' dates (None when unset or invalid)."""
    path = registry_path(section)
    if not os.path.exists(path):
        return None, [f"no metric registry {os.path.relpath(path, __import__('ledger').DATA)} (create it: one row per metric, see kpi.py docstring)"]
    errs, reg = [], {}
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if r.fieldnames != REG_COLUMNS:
            return {}, [f"{path}: header must be exactly {','.join(REG_COLUMNS)}"]
        for i, row in enumerate(r, 2):
            at = f"metrics/{section}.csv:{i}"
            if None in row or any(v is None for v in row.values()):
                errs.append(f"{at}: wrong number of fields (quote values containing commas)")
                continue
            m = row["metric"] or ""
            if not METRIC_RE.match(m):
                errs.append(f"{at}: bad metric id '{m}'")
            if m in reg:
                errs.append(f"{at}: duplicate metric '{m}'")
            if not (row["unit"] or "").strip():
                errs.append(f"{at}: empty unit")
            if len((row["definition"] or "").split()) < 5:
                errs.append(f"{at}: definition of '{m}' too thin — state the exact measure, basis/station/scope and window")
            if row["cadence"] not in CADENCES:
                errs.append(f"{at}: cadence must be one of {sorted(CADENCES)}")
            if row["release_lag_days"] and not row["release_lag_days"].isdigit():
                errs.append(f"{at}: release_lag_days must be a non-negative integer or empty")
            for col, key in (("required_from", "_req"), ("retired_after", "_ret")):
                row[key] = None
                if row[col]:
                    try:
                        row[key] = _period_date(row[col])
                    except ValueError:
                        errs.append(f"{at}: {col} '{row[col]}' is not a period name")
            if row["_req"] and row["_ret"] and row["_ret"] < row["_req"]:
                errs.append(f"{at}: retired_after precedes required_from")
            reg[m] = row
    return reg, errs


def required_active(row: dict, as_of: dt.date) -> bool:
    """Required KPI component in the period ending as_of (inclusive from
    required_from; not after retired_after)."""
    return bool(row["_req"] and as_of >= row["_req"] and not (row["_ret"] and as_of > row["_ret"]))


def chart_data(period_dir: str, section: str, metrics: list[str], match: str | None,
               label: str, since: str | None = None) -> tuple[list[str], list[list[str]]]:
    """x labels + one value list per metric: the FROZEN series of the period's
    committed snapshot (<period-dir>/snapshot/<section>.json) when it exists,
    else the ledger as of the period's cutoff (obs ending by the period end)."""
    import json
    import ledger
    period = period_of_dir(period_dir)
    end = period_as_of(period)
    snap_p = os.path.join(period_dir, "snapshot", f"{section}.json")
    frozen = None
    if os.path.exists(snap_p):
        frozen = json.load(open(snap_p, encoding="utf-8")).get("series")
        if frozen is None:
            raise ValueError(f"{snap_p} predates frozen series; its charts cannot be verified "
                             "reproducibly (regenerate the bulletin)")
    else:
        table = ledger.obs_as_of(section, ledger.cutoff(period))
        frozen = {}
        for (mm, o), r in table.items():
            if obs_range(o)[1] <= end:
                frozen.setdefault(mm, []).append([o, r["value"]])
    series: list[dict[str, str]] = []
    for m in metrics:
        pts = {o: v for o, v in frozen.get(m, [])
               if (not match or fnmatch.fnmatchcase(o, match)) and (not since or o[:4] >= since)}
        if not pts:
            raise ValueError(f"no ledger points for {section}/{m} (match={match}, since={since})")
        series.append(pts)
    obs = sorted(series[0], key=lambda o: obs_range(o)[0])
    if len({obs_kind(o) for o in obs}) > 1:
        raise ValueError(f"mixed obs granularity in {metrics[0]}: use --match")
    for m, pts in zip(metrics, series):
        if sorted(pts) != sorted(obs):
            raise ValueError(f"metric {m} does not cover the same obs as {metrics[0]}")
    xs = [o[:4] if label == "year" else o for o in obs]
    if len(set(xs)) != len(xs):
        raise ValueError("--label year would produce duplicate x labels")
    return xs, [[pts[o] for o in obs] for pts in series]


def _nice_range(vals: list[float]) -> tuple[str, str]:
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.1 or abs(hi) * 0.05 or 1
    step = 10 ** (len(str(int(pad))) - 1) if pad >= 1 else 0.1
    fmt = (lambda x: f"{x:g}") if step >= 1 else (lambda x: f"{x:.1f}")
    low = (lo - pad) // step * step
    if lo >= 0 > low:
        low = 0  # never push an all-positive series' axis below zero
    return fmt(low), fmt(-((-(hi + pad)) // step) * step)


def marker_args(section: str, metrics: list[str], match: str | None, label: str,
                since: str | None = None) -> str:
    a = [section, ",".join(metrics)]
    if match:
        a += ["--match", match]
    if since:
        a += ["--since", since]
    if label != "obs":
        a += ["--label", label]
    return " ".join(shlex.quote(x) for x in a)


def chart(period_dir: str, section: str, metrics: list[str], match: str | None = None,
          label: str = "obs", title: str | None = None, since: str | None = None) -> str:
    xs, data = chart_data(period_dir, section, metrics, match, label, since)
    unit = (load_registry(section)[0] or {}).get(metrics[0], {}).get("unit", "")
    lo, hi = _nice_range([float(v) for vs in data for v in vs])
    title = title or f"{', '.join(metrics)} ({unit})"
    lines = ["```mermaid", "xychart-beta",
             f"    %% kpi: {marker_args(section, metrics, match, label, since)}",
             f'    title "{title}"',
             f"    x-axis [{', '.join(xs)}]",
             f'    y-axis "{unit}" {lo} --> {hi}']
    for m, vs in zip(metrics, data):
        name = f' "{m}"' if len(metrics) > 1 else ""
        lines.append(f"    line{name} [{', '.join(vs)}]")
    lines.append("```")
    return "\n".join(lines)


def verify_charts(doc_text: str, period_dir: str) -> list[str]:
    """Re-render every '%% kpi:'-marked mermaid block; return drift errors."""
    errs = []
    for block in re.findall(r"```mermaid\n(.*?)```", doc_text, re.DOTALL):
        m = MARKER_RE.search(block)
        if not m:
            continue
        ap = argparse.ArgumentParser(add_help=False, exit_on_error=False)
        ap.add_argument("section"); ap.add_argument("metrics")
        ap.add_argument("--match"); ap.add_argument("--label", default="obs"); ap.add_argument("--since")
        try:
            a = ap.parse_args(shlex.split(m[1]))
            xs, data = chart_data(period_dir, a.section, a.metrics.split(","), a.match, a.label, a.since)
        except (ValueError, argparse.ArgumentError, SystemExit) as e:
            errs.append(f"kpi chart '{m[1]}': cannot render from store: {e}")
            continue
        got_x = re.search(r"x-axis\s+\[([^\]]*)\]", block)
        got_x = [x.strip().strip('"') for x in got_x[1].split(",")] if got_x else []
        named = [(n, [v.strip() for v in arr.split(",")]) for n, arr in
                 re.findall(r"^\s*(?:line|bar)(?:\s+\"([^\"]*)\")?\s+\[([^\]]*)\]", block, re.M)]
        got_series = [vs for _, vs in named]
        if got_x != xs:
            errs.append(f"kpi chart '{m[1]}': x-axis differs from store ({got_x} vs {xs})")
        metrics = a.metrics.split(",")
        for metric, vs in zip(metrics, data):
            if len(metrics) > 1:  # multi-metric: series must be bound by name
                if (metric, vs) not in named:
                    errs.append(f"kpi chart '{m[1]}': no series named \"{metric}\" with the store data")
            elif vs not in got_series:
                errs.append(f"kpi chart '{m[1]}': store series {vs} not present in the chart")
        y = re.search(r"y-axis\s+(?:\"[^\"]*\"\s+)?(-?[\d.]+)\s*-->\s*(-?[\d.]+)", block)
        vals = [float(v) for vs in data for v in vs]
        if y and not float(y[1]) <= min(vals) <= max(vals) <= float(y[2]):
            errs.append(f"kpi chart '{m[1]}': y-axis {y[1]}..{y[2]} clips the data ({min(vals)}..{max(vals)})")
    return errs


# --- CLI ----------------------------------------------------------------------
def registry_text(section: str) -> str:
    reg, errs = load_registry(section)
    if reg is None:
        return f"(no metric registry for '{section}' yet: metrics/{section}.csv)"
    lines = [f"Registered metrics for '{section}' (metrics/{section}.csv); the DEFINITION is binding:"]
    for m, row in reg.items():
        flags = [f"required from {row['required_from']}"] if row["required_from"] else []
        if row["retired_after"]:
            flags.append(f"retired after {row['retired_after']}")
        flags.append(f"{row['cadence']}" + (f", ~{row['release_lag_days']}d release lag" if row["release_lag_days"] else ""))
        lines.append(f"  {m} [{row['unit']}] ({'; '.join(flags)}): {row['definition']}")
    return "\n".join(lines + [f"  ERROR {e}" for e in errs])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("registry"); r.add_argument("section")
    ch = sub.add_parser("chart")
    ch.add_argument("period_dir"); ch.add_argument("section"); ch.add_argument("metrics")
    ch.add_argument("--match"); ch.add_argument("--since")
    ch.add_argument("--label", choices=["obs", "year"], default="obs"); ch.add_argument("--title")
    a = ap.parse_args()
    try:
        if a.cmd == "registry":
            print(registry_text(a.section))
        elif a.cmd == "chart":
            print(chart(a.period_dir, a.section, a.metrics.split(","), a.match, a.label, a.title, a.since))
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
