"""Shared ETA drivers (gather/RUBRIC.md §4.1 step 2, rubric v6+).

A driver is a fitted quantity that several milestone ETAs rest on (AI task horizons, the Dyna
failure-rate halving, ...). The data repo's drivers.yaml holds ONE fitted distribution per driver,
and every milestone listed in its `used_by` samples the same deterministic draws
(`ledger.py driver-draws <driver>`), so milestones sharing a driver agree on it draw by draw
(draw i of two drivers is independent; draw i of one driver is the same for every milestone).

drivers.yaml:
  seed: <int>                 canonical seed (assessments use it; --seed only for experiments)
  n: <int>                    canonical number of draws
  as_of: YYYY-MM-DD           default `asof` of derived expressions (the fit date)
  drivers:
    <driver id>:              [a-z0-9-]+
      description: <text>
      used_by: [<section>/<milestone slug>, ...]    milestones whose model samples it (framework.yaml)
      sources: {series: [<section>/<metric>, ...], events: [<event id>, ...]}   (at least one)
      window: <text>          the fit window(s)
      fit: <text>             how the parameters were fitted, and what is measured vs assumed
      params:                 in order; one column each in the draws
        <name>: {dist: fixed, value: V}
        <name>: {dist: lognormal|normal, p10: A, p50: B, p90: C}   split at the median: exact quantiles
        <name>: {dist: lognormal, p50: B, sdlog: S}  /  {dist: normal, p50: B, sd: S}
        <name>: {dist: triangular, min: A, mode: B, max: C}
        <name>: {dist: categorical, weights: {label: w, ...}}       (weights sum to 1)
        <name>: {dist: derived, expr: "<python expression>"}        of earlier params, asof, inf
                                                                    and min/max/exp/log/sqrt
      each random param may have `couple: <earlier random param>` (comonotonic: the same uniform
      draw, e.g. the 50% and 80% doubling times); every param may have a `label` (measured /
      sourced / assumed; quote it in a flow mapping when it contains a comma).
      review_by: YYYY-MM-DD   optional: the fit expires (e.g. a proponent date in it passes);
                              check and driver-draws warn after it
      tripwire:               optional: measured cross-checks that re-open the fit when they agree
        series: [<section>/<metric>, ...]   registered series of (measured - fitted) gaps, e.g. doublings
        threshold: T          > 0: a value beyond +-T counts
        min_series: K         it fires when at least K series (1 <= K <= len(series)) ...
        consecutive: C        ... each have C consecutive observations (contiguous obs periods)
                              ending at the latest obs label among all the series, all beyond T on
                              the same side (the K series on one side); a series whose latest obs
                              is older does not count. check and driver-draws warn while it fires.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import random
import re
from statistics import NormalDist

DRIVERS_FILE = "drivers.yaml"
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
Z90 = NormalDist().inv_cdf(0.9)  # 1.2816: p10/p90 are -/+ Z90 standard deviations
RANDOM = {"lognormal", "normal", "triangular", "categorical"}
KEYS = {"fixed": {"value"}, "lognormal": {"p10", "p50", "p90", "sdlog"}, "normal": {"p10", "p50", "p90", "sd"},
        "triangular": {"min", "mode", "max"}, "categorical": {"weights"}, "derived": {"expr"}}
COMMON_KEYS = {"dist", "label", "couple"}
EXPR_NAMES = {"min": min, "max": max, "exp": math.exp, "log": math.log, "sqrt": math.sqrt, "inf": math.inf}


def load(data_dir: str) -> dict | None:
    """drivers.yaml of the data repo, or None when there is none."""
    import yaml
    p = os.path.join(data_dir, DRIVERS_FILE)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def check_param(at: str, name: str, p, earlier: dict) -> list[str]:
    at = f"{at}: param {name}"
    if not isinstance(p, dict) or p.get("dist") not in RANDOM | {"fixed", "derived"}:
        return [f"{at}: needs dist (one of {sorted(RANDOM | {'fixed', 'derived'})})"]
    d, errs = p["dist"], []
    extra = set(p) - KEYS[d] - COMMON_KEYS
    if extra:  # e.g. a flow-mapping label with an unquoted comma ("label: a, b assumed")
        errs.append(f"{at}: unknown key(s) {sorted(map(str, extra))} for dist {d} (quote labels containing commas)")
    if "label" in p and not isinstance(p["label"], str):
        errs.append(f"{at}: label must be a string")
    if d == "fixed" and not _num(p.get("value")):
        errs.append(f"{at}: fixed needs a numeric value")
    elif d in ("lognormal", "normal"):
        spread = "sdlog" if d == "lognormal" else "sd"
        if set(p) & {"p10", "p90"} and spread in p:
            errs.append(f"{at}: {d} takes p10, p50, p90 OR p50 and {spread}, not both")
        elif {"p10", "p90"} & set(p):
            if not all(_num(p.get(k)) for k in ("p10", "p50", "p90")) or not p["p10"] < p["p50"] < p["p90"]:
                errs.append(f"{at}: needs numeric p10 < p50 < p90")
        elif not (_num(p.get("p50")) and _num(p.get(spread)) and p[spread] > 0):
            errs.append(f"{at}: {d} needs p10, p50, p90 or p50 and {spread} > 0")
        if d == "lognormal" and any(_num(p.get(k)) and p[k] <= 0 for k in ("p10", "p50", "p90")):
            errs.append(f"{at}: lognormal quantiles must be > 0")
    elif d == "triangular" and not (all(_num(p.get(k)) for k in ("min", "mode", "max"))
                                    and p["min"] <= p["mode"] <= p["max"] and p["min"] < p["max"]):
        errs.append(f"{at}: triangular needs min <= mode <= max (min < max)")
    elif d == "categorical":
        w = p.get("weights")
        if not (isinstance(w, dict) and w and all(_num(v) and v >= 0 for v in w.values())
                and abs(sum(w.values()) - 1) < 1e-9):
            errs.append(f"{at}: categorical needs weights {{label: w}} summing to 1")
    elif d == "derived":
        try:
            code = compile(str(p.get("expr") or ""), name, "eval")
            unknown = set(code.co_names) - set(earlier) - set(EXPR_NAMES) - {"asof"}
            if unknown or not p.get("expr"):
                errs.append(f"{at}: expr uses unknown names {sorted(unknown)} (earlier params, asof, "
                            f"{', '.join(sorted(EXPR_NAMES))})")
        except SyntaxError as e:
            errs.append(f"{at}: expr is not a Python expression ({e.msg})")
    if "couple" in p and (d not in RANDOM or p["couple"] not in earlier or earlier[p["couple"]] not in RANDOM):
        errs.append(f"{at}: couple must name an earlier random param (and only a random param couples)")
    return errs


def check(spec: dict | None, series_ok, event_ok, milestone_ok) -> list[str]:
    """Schema errors of drivers.yaml. series_ok(section, metric), event_ok(id) and milestone_ok(section, slug)
    say whether a reference resolves."""
    if spec is None:
        return []
    errs = []
    if not (isinstance(spec.get("seed"), int) and isinstance(spec.get("n"), int) and spec["n"] > 0):
        errs.append(f"{DRIVERS_FILE}: needs integer seed and n > 0")
    try:
        dt.date.fromisoformat(str(spec.get("as_of")))
    except ValueError:
        errs.append(f"{DRIVERS_FILE}: as_of must be YYYY-MM-DD")
    drivers = spec.get("drivers")
    if not isinstance(drivers, dict) or not drivers:
        return errs + [f"{DRIVERS_FILE}: needs a drivers mapping"]
    for did, d in drivers.items():
        at = f"{DRIVERS_FILE}: driver {did}"
        n0 = len(errs)
        if not ID_RE.match(str(did)):
            errs.append(f"{at}: bad driver id")
        if not isinstance(d, dict):
            errs.append(f"{at}: must be a mapping")
            continue
        for k in ("description", "window", "fit"):
            if not str(d.get(k) or "").strip():
                errs.append(f"{at}: needs {k}")
        if "review_by" in d:
            try:
                dt.date.fromisoformat(str(d["review_by"]))
            except ValueError:
                errs.append(f"{at}: review_by must be YYYY-MM-DD")
        if "tripwire" in d:
            errs += check_tripwire(at, d["tripwire"], series_ok)
        for u in d.get("used_by") or []:
            sec, _, slug = str(u).partition("/")
            if not milestone_ok(sec, slug):
                errs.append(f"{at}: used_by {u!r} is not a framework.yaml milestone (<section>/<slug>)")
        if not d.get("used_by"):
            errs.append(f"{at}: needs used_by (the milestones whose ETA samples it)")
        src = d.get("sources") or {}
        if not (src.get("series") or src.get("events")):
            errs.append(f"{at}: needs sources: series and/or events")
        for s in src.get("series") or []:
            sec, _, m = str(s).partition("/")
            if not series_ok(sec, m):
                errs.append(f"{at}: source series {s!r} is not a registered <section>/<metric>")
        for e in src.get("events") or []:
            if not event_ok(str(e)):
                errs.append(f"{at}: source event {e!r} is not an effective ledger event (unknown, superseded or withdrawn)")
        params = d.get("params")
        if not isinstance(params, dict) or not params:
            errs.append(f"{at}: needs params")
            continue
        earlier: dict[str, str] = {}
        for name, p in params.items():
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", str(name)) or name in EXPR_NAMES or name in ("asof", "draw"):
                errs.append(f"{at}: bad param name {name!r} (lower_snake_case, not a reserved name)")
            errs += check_param(at, name, p, earlier)
            # a coupled param is no partner itself (draws() keeps one uniform stream per uncoupled param)
            earlier[name] = ("coupled" if "couple" in p else p.get("dist")) if isinstance(p, dict) else None
        if len(errs) == n0:  # executable check: every param of a sample of draws is a number (inf = never) or a label
            try:
                for row in draws(spec, did, seed=0, n=200, as_of=dt.date(2030, 1, 1))[1]:
                    bad = [k for k, v in zip(params, row) if not (isinstance(v, str) or _num(v) or v == math.inf)]
                    if bad:
                        errs.append(f"{at}: draws give a non-numeric {bad[0]}")
                        break
            except Exception as e:  # a derived expression failing at run time (1 / 0, a str + a number, ...)
                errs.append(f"{at}: draws fail: {type(e).__name__}: {e}")
    return errs


def check_tripwire(at: str, t, series_ok) -> list[str]:
    at = f"{at}: tripwire"
    if not isinstance(t, dict):
        return [f"{at}: must be a mapping"]
    errs = []
    if set(t) - {"series", "threshold", "min_series", "consecutive"}:
        errs.append(f"{at}: unknown key(s) {sorted(map(str, set(t) - {'series', 'threshold', 'min_series', 'consecutive'}))}")
    ser = t.get("series")
    if not (isinstance(ser, list) and ser and len(set(map(str, ser))) == len(ser)):
        errs.append(f"{at}: needs a non-empty list of distinct series")
        ser = []
    for s in ser:
        sec, _, m = str(s).partition("/")
        if not series_ok(sec, m):
            errs.append(f"{at}: series {s!r} is not a registered <section>/<metric>")
    if not (_num(t.get("threshold")) and t["threshold"] > 0):
        errs.append(f"{at}: threshold must be a number > 0")
    k, c = t.get("min_series"), t.get("consecutive")
    if not (isinstance(k, int) and not isinstance(k, bool) and 1 <= k <= max(len(ser), 1)):
        errs.append(f"{at}: min_series must be an integer from 1 to the number of series")
    if not (isinstance(c, int) and not isinstance(c, bool) and c >= 1):
        errs.append(f"{at}: consecutive must be an integer >= 1")
    return errs


def tripwires(spec: dict | None, values) -> list[str]:
    """Warnings of the drivers whose tripwire fires. values(section, metric) -> [(obs, float)] of the
    series' effective observations."""
    import kpi
    out = []
    for did, d in ((spec or {}).get("drivers") or {}).items():
        t = d.get("tripwire") if isinstance(d, dict) else None
        if not t:
            continue
        ser = {s: sorted(values(*str(s).split("/", 1)), key=lambda r: kpi.obs_range(r[0])) for s in t["series"]}
        ends = [kpi.obs_range(v[-1][0])[1] for v in ser.values() if v]
        if not ends:
            continue
        last, sides = max(ends), {1: [], -1: []}
        for s, v in ser.items():
            tail = v[-t["consecutive"]:]
            if len(tail) < t["consecutive"] or kpi.obs_range(tail[-1][0])[1] != last:
                continue
            if any(kpi.obs_range(b[0])[0] != kpi.obs_range(a[0])[1] + dt.timedelta(days=1) for a, b in zip(tail, tail[1:])):
                continue
            for side in (1, -1):
                if all(side * x > t["threshold"] for _, x in tail):
                    sides[side].append(f"{s} ({', '.join(f'{o} {x:+g}' for o, x in tail)})")
        for side, hit in sides.items():
            if len(hit) >= t["min_series"]:
                out.append(f"{DRIVERS_FILE}: driver {did}: tripwire fired: {len(hit)} series {'above' if side > 0 else 'below'} "
                           f"{'+' if side > 0 else '-'}{t['threshold']:g} for {t['consecutive']} consecutive observations "
                           f"({'; '.join(hit)}): re-open the fit (a reviewed edit)")
    return out


def review_due(spec: dict | None, when: dt.date) -> list[str]:
    """Drivers whose review_by date has passed by `when` (a proponent date in the fit has expired, etc.)."""
    return [f"{DRIVERS_FILE}: driver {did}: review_by {d['review_by']} has passed: refit it (a reviewed edit)"
            for did, d in ((spec or {}).get("drivers") or {}).items()
            if isinstance(d, dict) and d.get("review_by") and str(d["review_by"]) < str(when)]


def _quantile(p: dict, u: float):
    d = p["dist"]
    if d == "categorical":
        acc = 0.0
        for label, w in p["weights"].items():
            acc += w
            if u < acc:
                return label
        return label
    if d == "triangular":
        a, c, b = p["min"], p["mode"], p["max"]
        f = (c - a) / (b - a)
        return a + math.sqrt(u * (b - a) * (c - a)) if u < f else b - math.sqrt((1 - u) * (b - a) * (b - c))
    z = NormalDist().inv_cdf(min(max(u, 1e-12), 1 - 1e-12))
    log = d == "lognormal"
    t = (lambda x: math.log(x)) if log else (lambda x: x)
    mid = t(p["p50"])
    if _num(p.get("p10")) and _num(p.get("p90")):
        sd = (mid - t(p["p10"])) / Z90 if z < 0 else (t(p["p90"]) - mid) / Z90
    else:
        sd = p["sdlog" if log else "sd"]
    x = mid + z * sd
    return math.exp(x) if log else x


def decimal_year(d: dt.date) -> float:
    start = dt.date(d.year, 1, 1)
    return d.year + ((d - start).days + 0.5) / (dt.date(d.year + 1, 1, 1) - start).days


def draws(spec: dict, driver: str, seed: int | None = None, n: int | None = None,
          as_of: dt.date | None = None) -> tuple[list[str], list[list]]:
    """(param names, rows) of `n` deterministic draws of `driver`: the same seed, n and as_of give the same
    numbers on any machine (random.Random seeded by a string; draw i does not depend on n)."""
    d = (spec.get("drivers") or {}).get(driver)
    if d is None:
        raise KeyError(f"no driver {driver!r} in {DRIVERS_FILE} (have: {', '.join(spec.get('drivers') or {})})")
    seed = spec["seed"] if seed is None else seed
    n = spec["n"] if n is None else n
    asof = decimal_year(as_of or dt.date.fromisoformat(str(spec["as_of"])))
    params = d["params"]
    streams = {name: random.Random(f"{seed}:{driver}:{name}") for name, p in params.items()
               if p["dist"] in RANDOM and "couple" not in p}
    codes = {name: compile(p["expr"], name, "eval") for name, p in params.items() if p["dist"] == "derived"}
    rows = []
    for _ in range(n):
        us = {name: rng.random() for name, rng in streams.items()}
        vals: dict = {}
        for name, p in params.items():
            if p["dist"] == "fixed":
                vals[name] = p["value"]
            elif p["dist"] == "derived":
                vals[name] = eval(codes[name], {"__builtins__": {}}, {**EXPR_NAMES, **vals, "asof": asof})
            else:
                vals[name] = _quantile(p, us[p.get("couple", name)])
        rows.append([vals[k] for k in params])
    return list(params), rows


def fmt(v) -> str:
    return v if isinstance(v, str) else "inf" if v == math.inf else f"{v:.10g}"
