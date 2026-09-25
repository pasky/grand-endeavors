#!/usr/bin/env python3
"""KPI time-series store for Grand Endeavors: record, check, chart, delta.

STORE LAYOUT
    <period-dir>/kpis/<section>.csv    one file per section run (owned by that
                                       run, like its research notes)
The store is the union of all those files across period dirs. Period dir name
minus a leading "pilot-" is the period, which fixes its as-of date:
    2025 -> 2025-12-31    26H1 -> 2026-06-30    26H2 -> 2026-12-31
    2026-Q2 -> 2026-06-30 2026-06 -> 2026-06-30 2026-W26 -> Sunday of ISO week 26
Each period's file is a VINTAGE: what that report knew as of its as-of date
(data gets revised, e.g. NOAA recalibration, so vintages are kept, not merged).

CSV COLUMNS (header required, in this order)
    metric  stable id, ^[a-z0-9][a-z0-9-]*$, encodes the exact measure+basis
            (e.g. co2-mlo-monthly, co2-growth-mlo-jan-dec). SAME measure =>
            SAME id across periods (that is what makes deltas work); a
            different basis MUST get a different id.
    obs     observation time: YYYY | YYYY-MM | YYYY-MM-DD | YYYY-Qn | YYYY-Hn
            (for windowed stats like a 10-yr mean: the window's last period)
    value   plain decimal, as written in the source (no units/commas/~)
    unit    e.g. ppm, ppm/yr, min, $/kg
    role    headline = this report's current reading of a KPI component
                       (at most one per metric per file; >=1 per file)
            series   = historical/context datapoint (e.g. for trend charts)
    source  deep-link URL
    note    free text: qualifiers (approx., preliminary), window, basis

COMMANDS
    kpi.py check <csv> [--evidence FILE ...]   schema + traceability (+ continuity warns)
    kpi.py context <period-dir> <section>      previously used metric ids (for the record stage)
    kpi.py delta <period-dir> <section>        headline change vs the previous period's headline
    kpi.py chart <period-dir> <section> <metric>[,<metric>...] [--match GLOB] [--label obs|year] [--title T]
        mermaid xychart from the store as of <period-dir> (latest vintage per
        obs). The block carries a "%% kpi: ..." marker so validate.py --kpis can
        re-render it and fail on drift.
Projections are NOT stored (observed/reported values only).
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
COLUMNS = ["metric", "obs", "value", "unit", "role", "source", "note"]
ROLES = {"headline", "series"}
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
def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if r.fieldnames != COLUMNS:
            raise ValueError(f"{path}: header must be exactly {','.join(COLUMNS)} (got {r.fieldnames})")
        return [dict(row, _line=i) for i, row in enumerate(r, 2)]


def vintages(section: str) -> list[tuple[dt.date, str, list[dict]]]:
    """All stored vintages for a section, sorted by (as_of, dir name)."""
    out = []
    for path in glob.glob(os.path.join(ROOT, "*", "kpis", f"{section}.csv")):
        pdir = os.path.dirname(os.path.dirname(path))
        try:
            as_of = period_as_of(period_of_dir(pdir))
        except ValueError:
            continue  # not a period dir
        out.append((as_of, os.path.basename(pdir), read_csv(path)))
    return sorted(out, key=lambda v: (v[0], v[1]))


def _upto(section: str, period_dir: str) -> list[tuple[dt.date, str, list[dict]]]:
    me = os.path.basename(os.path.normpath(period_dir))
    as_of = period_as_of(period_of_dir(period_dir))
    return [v for v in vintages(section) if (v[0], v[1]) <= (as_of, me)]


# --- check --------------------------------------------------------------------
def check(path: str, evidence: list[str] | None = None) -> tuple[list[str], list[str]]:
    errs: list[str] = []
    warns: list[str] = []
    try:
        rows = read_csv(path)
    except (OSError, ValueError) as e:
        return [str(e)], []
    pdir = os.path.dirname(os.path.dirname(os.path.abspath(path)))
    section = os.path.splitext(os.path.basename(path))[0]
    try:
        as_of = period_as_of(period_of_dir(pdir))
    except ValueError as e:
        errs.append(f"{path}: {e} (file must live at <period-dir>/kpis/<section>.csv)")
        as_of = None
    if evidence:
        from validate import numbers, traceable  # lazy: validate imports us lazily too
        pool: set[str] = set()
        for ev in evidence:
            pool |= numbers(open(ev, encoding="utf-8").read())
    seen_head, seen_key, units = set(), set(), {}
    for r in rows:
        at = f"{os.path.basename(path)}:{r['_line']}"
        if not METRIC_RE.match(r["metric"] or ""):
            errs.append(f"{at}: bad metric id '{r['metric']}'")
        try:
            start, _ = obs_range(r["obs"] or "")
            if as_of and start > as_of:
                errs.append(f"{at}: obs {r['obs']} starts after the period's as-of date {as_of} (post-period data)")
        except ValueError:
            errs.append(f"{at}: malformed obs '{r['obs']}'")
        if not VALUE_RE.match(r["value"] or ""):
            errs.append(f"{at}: value '{r['value']}' is not a plain decimal")
        elif evidence and not traceable(r["value"], pool):
            errs.append(f"{at}: value {r['value']} ({r['metric']} {r['obs']}) not found in the evidence files")
        if not (r["unit"] or "").strip():
            errs.append(f"{at}: empty unit")
        if r["role"] not in ROLES:
            errs.append(f"{at}: role '{r['role']}' not in {sorted(ROLES)}")
        if not re.match(r"https?://\S+$", r["source"] or ""):
            errs.append(f"{at}: source must be a single http(s) URL")
        if units.setdefault(r["metric"], r["unit"]) != r["unit"]:
            errs.append(f"{at}: metric {r['metric']} has mixed units ({units[r['metric']]} vs {r['unit']})")
        key = (r["metric"], r["obs"])
        if key in seen_key:
            errs.append(f"{at}: duplicate row for {r['metric']} {r['obs']}")
        seen_key.add(key)
        if r["role"] == "headline":
            if r["metric"] in seen_head:
                errs.append(f"{at}: more than one headline row for {r['metric']}")
            seen_head.add(r["metric"])
    if not seen_head:
        errs.append(f"{path}: no headline row (every run must record its current KPI reading)")
    # Continuity: earlier vintages exist but none shares a headline metric id.
    if as_of:
        me = os.path.basename(pdir)
        prior = [v for v in vintages(section) if (v[0], v[1]) < (as_of, me)]
        prior_ids = {r["metric"] for _, _, rs in prior for r in rs}
        for m in sorted(seen_head - prior_ids):
            if prior:
                warns.append(f"headline metric '{m}' is new (not in any earlier period) — no delta possible; reuse an existing id if it is the same measure")
        for _, _, rs in prior:
            for r in rs:
                if r["metric"] in units and units[r["metric"]] != r["unit"]:
                    errs.append(f"metric {r['metric']}: unit {units[r['metric']]} differs from earlier period's {r['unit']} (same id must mean same measure)")
                    units[r["metric"]] = r["unit"]  # report once
    return errs, warns


# --- context / delta ----------------------------------------------------------
def context(period_dir: str, section: str) -> str:
    as_of = period_as_of(period_of_dir(period_dir))
    me = os.path.basename(os.path.normpath(period_dir))
    prior = [v for v in vintages(section) if (v[0], v[1]) < (as_of, me)]
    if not prior:
        return f"(no earlier KPI records for section '{section}' — you are defining its metric ids)"
    last: dict[str, tuple[str, dict]] = {}
    for _, pname, rs in prior:
        for r in rs:
            last[r["metric"]] = (pname, r)  # later vintage wins
    lines = [f"Metric ids already used for '{section}' (reuse the SAME id for the SAME measure/basis):"]
    for m, (pname, r) in sorted(last.items()):
        note = f" — {r['note']}" if r["note"] else ""
        lines.append(f"  {m} [{r['unit']}] last: {r['value']} @ {r['obs']} ({r['role']}, {pname}){note}")
    return "\n".join(lines)


def delta(period_dir: str, section: str) -> str:
    vs = _upto(section, period_dir)
    me = os.path.basename(os.path.normpath(period_dir))
    cur = [v for v in vs if v[1] == me]
    if not cur:
        return f"(no KPI record for {section} in {me})"
    out = []
    for r in (r for r in cur[0][2] if r["role"] == "headline"):
        prev = None
        for _, pname, rs in vs:
            if pname == me:
                continue
            for p in rs:
                if p["metric"] == r["metric"] and p["role"] == "headline":
                    prev = (pname, p)
        head = f"{r['metric']}: {r['value']} {r['unit']} @ {r['obs']}"
        if not prev:
            out.append(f"{head} — no previous headline for this metric")
            continue
        pname, p = prev
        d = float(r["value"]) - float(p["value"])
        nd = max(len(x.split(".")[1]) if "." in x else 0 for x in (r["value"], p["value"]))
        if obs_kind(p["obs"]) != obs_kind(r["obs"]):
            caveat = " [different obs granularity — not comparable]"
        elif obs_kind(r["obs"]).startswith("9999-99") and p["obs"][5:7] != r["obs"][5:7]:
            caveat = " [different calendar month — seasonal cycle not removed]"
        else:
            caveat = ""
        out.append(f"{head} — prev {p['value']} @ {p['obs']} ({pname}); change {d:+.{nd}f} {r['unit']}{caveat}")
    return "\n".join(out) if out else "(no headline rows)"


# --- chart --------------------------------------------------------------------
def chart_data(period_dir: str, section: str, metrics: list[str], match: str | None,
               label: str) -> tuple[list[str], list[list[str]]]:
    """x labels + one value list per metric, latest vintage per obs, as of period."""
    series: list[dict[str, str]] = []
    for m in metrics:
        pts: dict[str, str] = {}
        for _, _, rs in _upto(section, period_dir):  # ascending: later vintage overwrites
            for r in rs:
                if r["metric"] == m and (not match or fnmatch.fnmatchcase(r["obs"], match)):
                    pts[r["obs"]] = r["value"]
        if not pts:
            raise ValueError(f"no stored points for {section}/{m} (match={match})")
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


def marker_args(section: str, metrics: list[str], match: str | None, label: str) -> str:
    a = [section, ",".join(metrics)]
    if match:
        a += ["--match", match]
    if label != "obs":
        a += ["--label", label]
    return " ".join(shlex.quote(x) for x in a)


def chart(period_dir: str, section: str, metrics: list[str], match: str | None = None,
          label: str = "obs", title: str | None = None) -> str:
    xs, data = chart_data(period_dir, section, metrics, match, label)
    unit = next((r["unit"] for _, _, rs in _upto(section, period_dir) for r in rs if r["metric"] == metrics[0]), "")
    lo, hi = _nice_range([float(v) for vs in data for v in vs])
    title = title or f"{', '.join(metrics)} ({unit})"
    lines = ["```mermaid", "xychart-beta",
             f"    %% kpi: {marker_args(section, metrics, match, label)}",
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
        ap.add_argument("--match"); ap.add_argument("--label", default="obs")
        try:
            a = ap.parse_args(shlex.split(m[1]))
            xs, data = chart_data(period_dir, a.section, a.metrics.split(","), a.match, a.label)
        except (ValueError, argparse.ArgumentError, SystemExit) as e:
            errs.append(f"kpi chart '{m[1]}': cannot render from store: {e}")
            continue
        got_x = re.search(r"x-axis\s+\[([^\]]*)\]", block)
        got_x = [x.strip().strip('"') for x in got_x[1].split(",")] if got_x else []
        got_series = [[v.strip() for v in s.split(",")]
                      for s in re.findall(r"^\s*(?:line|bar)(?:\s+\"[^\"]*\")?\s+\[([^\]]*)\]", block, re.M)]
        if got_x != xs:
            errs.append(f"kpi chart '{m[1]}': x-axis differs from store ({got_x} vs {xs})")
        for vs in data:
            if vs not in got_series:
                errs.append(f"kpi chart '{m[1]}': store series {vs} not present in the chart")
    return errs


def headline_errors(doc_text: str, csv_path: str) -> list[str]:
    """KPI consistency: every headline value of this run appears in the section."""
    from validate import numbers, traceable
    pool = numbers(doc_text)
    return [f"kpi headline {r['metric']}={r['value']} {r['unit']} ({r['obs']}) not reported in the section"
            for r in read_csv(csv_path) if r["role"] == "headline" and not traceable(r["value"], pool)]


# --- CLI ----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("csv"); c.add_argument("--evidence", nargs="*")
    for name in ("context", "delta"):
        p = sub.add_parser(name); p.add_argument("period_dir"); p.add_argument("section")
    ch = sub.add_parser("chart")
    ch.add_argument("period_dir"); ch.add_argument("section"); ch.add_argument("metrics")
    ch.add_argument("--match"); ch.add_argument("--label", choices=["obs", "year"], default="obs")
    ch.add_argument("--title")
    a = ap.parse_args()
    try:
        if a.cmd == "check":
            errs, warns = check(a.csv, a.evidence)
            for w in warns:
                print(f"  WARN  {w}")
            for e in errs:
                print(f"  ERROR {e}")
            print(f"\nkpi check: {len(errs)} error(s), {len(warns)} warning(s) — {a.csv}")
            return 1 if errs else 0
        if a.cmd == "context":
            print(context(a.period_dir, a.section))
        elif a.cmd == "delta":
            print(delta(a.period_dir, a.section))
        elif a.cmd == "chart":
            print(chart(a.period_dir, a.section, a.metrics.split(","), a.match, a.label, a.title))
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
