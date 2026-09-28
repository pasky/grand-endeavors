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

METRIC REGISTRY (the continuity contract; one per section, across periods)
    metrics/<section>.csv   columns: metric,unit,required_from,retired_after,definition
    Every metric id used in a store file MUST be registered, with the registry's
    unit. definition = the exact measure, basis/station/scope and window, so
    "same id" provably means "same measure". required_from=<period>: from then on
    every run must record a headline (or 'unavailable') row for it — the KPI's
    components. retired_after=<period>: no headline rows after that period (a
    basis change = new id + retire the old one; NEVER redefine an existing id).
    Registry edits are part of the section run and are audited (generate.sh).

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
            unavailable = a required component with no reading this period:
                       empty value, note says why (obs/source may be empty)
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
REG_COLUMNS = ["metric", "unit", "required_from", "retired_after", "definition"]
ROLES = {"headline", "series", "unavailable"}
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
        rows = [dict(row, _line=i) for i, row in enumerate(r, 2)]
    for row in rows:
        if None in row or any(v is None for v in row.values()):
            raise ValueError(f"{path}:{row['_line']}: wrong number of fields (quote values containing commas)")
    return rows


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
    return os.path.join(ROOT, "metrics", f"{section}.csv")


def load_registry(section: str) -> tuple[dict[str, dict] | None, list[str]]:
    """({metric: row} or None if no registry file, errors). Rows get parsed
    '_req'/'_ret' dates (None when unset or invalid)."""
    path = registry_path(section)
    if not os.path.exists(path):
        return None, [f"no metric registry {os.path.relpath(path, ROOT)} (create it: one row per metric, see kpi.py docstring)"]
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
    reg, reg_errs = load_registry(section)
    errs += reg_errs
    reg = reg or {}
    registered = not any(e.startswith("no metric registry") for e in reg_errs)
    if evidence:
        pool: set[float] = set()
        for ev in evidence:
            pool |= kpi_numbers(open(ev, encoding="utf-8").read())
    seen_head, seen_key = set(), set()
    for r in rows:
        at = f"{os.path.basename(path)}:{r['_line']}"
        m = r["metric"]
        if not METRIC_RE.match(m or ""):
            errs.append(f"{at}: bad metric id '{m}'")
        elif registered and m not in reg:
            errs.append(f"{at}: metric '{m}' is not in metrics/{section}.csv — use the registered id for "
                        f"that measure, or register a genuinely new measure with a precise definition")
        elif registered and reg[m]["unit"] != r["unit"]:
            errs.append(f"{at}: unit '{r['unit']}' differs from the registry's '{reg[m]['unit']}' for {m}")
        if r["role"] not in ROLES:
            errs.append(f"{at}: role '{r['role']}' not in {sorted(ROLES)}")
        if r["role"] == "unavailable":
            if r["value"] or not (r["note"] or "").strip():
                errs.append(f"{at}: an 'unavailable' row needs an empty value and a note saying why")
            if r["obs"]:
                try:
                    obs_range(r["obs"])
                except ValueError:
                    errs.append(f"{at}: malformed obs '{r['obs']}'")
            if r["source"] and not re.match(r"https?://\S+$", r["source"]):
                errs.append(f"{at}: source must be a single http(s) URL")
        else:
            try:
                _, end = obs_range(r["obs"] or "")
                if as_of and end > as_of:
                    errs.append(f"{at}: obs {r['obs']} ends after the period's as-of date {as_of} (post-period or partial-period data; use a finer obs, e.g. YYYY-H1)")
            except ValueError:
                errs.append(f"{at}: malformed obs '{r['obs']}'")
            if not VALUE_RE.match(r["value"] or ""):
                errs.append(f"{at}: value '{r['value']}' is not a plain decimal")
            elif evidence and not kpi_traceable(r["value"], pool):
                errs.append(f"{at}: value {r['value']} ({m} {r['obs']}) not found in the evidence files")
            if not (r["unit"] or "").strip():
                errs.append(f"{at}: empty unit")
            if not re.match(r"https?://\S+$", r["source"] or ""):
                errs.append(f"{at}: source must be a single http(s) URL")
        key = (m, r["obs"])
        if key in seen_key:
            errs.append(f"{at}: duplicate row for {m} {r['obs']}")
        seen_key.add(key)
        if r["role"] in ("headline", "unavailable"):
            if m in seen_head:
                errs.append(f"{at}: more than one headline/unavailable row for {m}")
            seen_head.add(m)
            ret = reg.get(m, {}).get("_ret")
            if as_of and ret and as_of > ret:
                errs.append(f"{at}: {m} was retired after {reg[m]['retired_after']}; record its successor instead")
    if as_of:
        for m, row in reg.items():
            if required_active(row, as_of) and m not in seen_head:
                errs.append(f"required KPI component '{m}' has no headline row (or an 'unavailable' row with a reason)")
        me = os.path.basename(pdir)
        prior = [v for v in vintages(section) if (v[0], v[1]) < (as_of, me)]
        if prior:  # non-required headlines that silently disappeared
            ids_now = {r["metric"] for r in rows}
            for m in sorted({r["metric"] for r in prior[-1][2] if r["role"] == "headline"} - ids_now):
                if not (reg.get(m, {}).get("_ret") and as_of > reg[m]["_ret"]):
                    warns.append(f"headline metric '{m}' of {prior[-1][1]} is not recorded in this run")
    if not seen_head:
        warns.append(f"{path}: no headline row — OK only if the KPI has no numeric reading this period (say why in the section)")
    return errs, warns


# --- context / delta ----------------------------------------------------------
def context(period_dir: str, section: str) -> str:
    """Registry (definitions!) + each metric's latest reading, for the record stage."""
    as_of = period_as_of(period_of_dir(period_dir))
    me = os.path.basename(os.path.normpath(period_dir))
    prior = [v for v in vintages(section) if (v[0], v[1]) < (as_of, me)]
    last: dict[str, tuple[str, dict]] = {}
    for _, pname, rs in prior:  # ascending: a later vintage replaces an earlier one
        by_metric: dict[str, dict] = {}
        for r in rs:
            cur = by_metric.get(r["metric"])
            if r["role"] == "unavailable":
                continue
            if (cur is None or r["role"] == "headline"
                    or (cur["role"] != "headline" and obs_range(r["obs"])[1] > obs_range(cur["obs"])[1])):
                by_metric[r["metric"]] = r
        for m, r in by_metric.items():
            last[m] = (pname, r)
    reg, errs = load_registry(section)
    if reg is None:
        return f"(no metric registry yet for '{section}': create metrics/{section}.csv — you are defining its metrics)"
    lines = [f"Registered metrics for '{section}' (metrics/{section}.csv). Use these ids; the DEFINITION is binding:"]
    for m, row in reg.items():
        flags = []
        if required_active(row, as_of):
            flags.append("REQUIRED headline")
        if row["retired_after"]:
            flags.append(f"retired after {row['retired_after']}")
        seen = f" | last: {last[m][1]['value']} @ {last[m][1]['obs']} ({last[m][1]['role']}, {last[m][0]})" if m in last else ""
        lines.append(f"  {m} [{row['unit']}]{' (' + ', '.join(flags) + ')' if flags else ''}: {row['definition']}{seen}")
    return "\n".join(lines)


def delta(period_dir: str, section: str) -> str:
    vs = _upto(section, period_dir)
    me = os.path.basename(os.path.normpath(period_dir))
    cur = [v for v in vs if v[1] == me]
    if not cur:
        return f"(no KPI record for {section} in {me})"
    out = []
    for r in (r for r in cur[0][2] if r["role"] == "unavailable"):
        out.append(f"{r['metric']}: UNAVAILABLE this period — {r['note']}")
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
        if p["obs"] == r["obs"]:
            caveat = (" [same observation, unchanged — no new data]" if d == 0
                      else " [same observation REVISED by the source — not a real-world change]")
        elif obs_range(r["obs"])[0] < obs_range(p["obs"])[0]:
            caveat = " [current obs is OLDER than the previous one — stale reading]"
        elif obs_kind(p["obs"]) != obs_kind(r["obs"]):
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
                if (r["metric"] == m and r["role"] != "unavailable"
                        and (not match or fnmatch.fnmatchcase(r["obs"], match))):
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
    unit = (load_registry(section)[0] or {}).get(metrics[0], {}).get("unit") or next(
        (r["unit"] for _, _, rs in _upto(section, period_dir) for r in rs if r["metric"] == metrics[0]), "")
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


def headline_errors(doc_text: str, csv_path: str) -> list[str]:
    """KPI consistency: every headline value of this run appears in the section."""
    # mermaid blocks don't count: a headline must be REPORTED, not just charted
    prose = re.sub(r"```.*?```", "", doc_text, flags=re.DOTALL)
    pool = kpi_numbers(prose)
    rows = read_csv(csv_path)
    errs = [f"kpi headline {r['metric']}={r['value']} {r['unit']} ({r['obs']}) not reported in the section"
            for r in rows if r["role"] == "headline" and not kpi_traceable(r["value"], pool)]
    if any(r["role"] == "unavailable" for r in rows) and not re.search(
            r"\b(unavailable|not available|no (new |current )?(reading|data|value))\b", prose, re.I):
        errs.append("store marks a KPI component 'unavailable' but the section never says a reading is unavailable (and why)")
    return errs


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
