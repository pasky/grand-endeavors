"""Shared ETA drivers (gather/RUBRIC.md §4.1 step 2, rubric v6+).

A driver is a fitted quantity that several milestone ETAs rest on (METR task horizons, the Dyna
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
      draw, e.g. the 50% and 80% doubling times) and a `label` (measured / sourced / assumed).
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
    if d == "fixed" and not _num(p.get("value")):
        errs.append(f"{at}: fixed needs a numeric value")
    elif d in ("lognormal", "normal"):
        spread = "sdlog" if d == "lognormal" else "sd"
        if all(_num(p.get(k)) for k in ("p10", "p50", "p90")):
            if not p["p10"] < p["p50"] < p["p90"]:
                errs.append(f"{at}: needs p10 < p50 < p90")
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
        if not ID_RE.match(str(did)):
            errs.append(f"{at}: bad driver id")
        if not isinstance(d, dict):
            errs.append(f"{at}: must be a mapping")
            continue
        for k in ("description", "window", "fit"):
            if not str(d.get(k) or "").strip():
                errs.append(f"{at}: needs {k}")
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
    return errs


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
    if "p10" in p and "p90" in p:
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
