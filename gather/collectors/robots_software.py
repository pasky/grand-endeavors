#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Robots/software KPI collector: AI task horizons (software, remote work, their blend) from
Epoch AI's ECI and the Remote Labor Index, plus the (discontinued) METR horizon series.

Usage:  uv run gather/collectors/robots_software.py --out FILE [--fixture DIR] [--today YYYY-MM-DD]
        uv run gather/collectors/robots_software.py --calibrate [--fixture DIR]
            refit the ECI -> METR calibration from the METR file and the current ECI file and
            print it next to the frozen constants (a changed calibration is a NEW metric id)

The KPI (framework.yaml, metrics/kpi-assessment.csv) is horizon-80-blended: the geometric
mean of two 80%-success task horizons in human-hours, both release-cohort series (the best
among models RELEASED by the obs date, from the current file vintages):
  horizon-80-software-eci    METR-equivalent software horizon converted from the Epoch
                             Capabilities Index frontier (eci-frontier-by-release)
  horizon-80-remote-rli      remote-freelance-work horizon converted from the Remote Labor
                             Index automation-rate frontier (rli-automation-by-release)
The same three at 50% success (horizon-50-*) are collected alongside, and so are directly
measured horizons on SWE-Marathon (swe-marathon-h80/h50-by-release: METR's method on 20 long
software tasks, gather/collectors/swe_marathon.py), the check on the ECI conversion at the
frontier, where METR's calibration models end.

SOURCES
  https://epoch.ai/data/benchmark_data.zip (Epoch AI Benchmarking Hub, CC-BY 4.0; refreshed
  daily). Members read:
    epoch_capabilities_index/eci_scores.csv   Model, eci, eci_ci_low, eci_ci_high, date (release)
    rli_external.csv                          Model version, Score (0-1), Release date
      (Epoch's mirror of Scale AI / CAIS's labs.scale.com/leaderboard/rli; the original page
      has no release dates and no data file)
  https://metr.org/assets/benchmark_results_1_1.yaml, the data file behind
  https://metr.org/time-horizons/ ("Time Horizon 1.1"). METR stopped updating it (page
  changelog 2026-09-08: "no longer actively updated"; last model released 2026-04-07). It is
  still read because it is the (frozen) calibration source.
  Format (YAML, parsed line-wise by `yaml_paths`, no dependency):
    benchmark_name: METR-Horizon-v1.1
    results:
      <model_id>:
        benchmark_name: METR-Horizon-v1.x   (older models carried over from v1.0)
        metrics:
          p50_horizon_length: {ci_high, ci_low, estimate}   minutes
          p80_horizon_length: {ci_high, ci_low, estimate}   minutes
        release_date: YYYY-MM-DD

CONVERSIONS (frozen; changing one changes what the horizon ids mean -> new ids)
  software: log2(METR horizon minutes) = a + b * ECI (ECI_CAL), one OLS fit per success level
    over the 21 models in both METR's TH1.1 file and Epoch's ECI file (CALIBRATION_PAIRS; fitted
    2026-10-16 on the ECI vintage of 2026-10-15): p50 4.415 ECI points per doubling, R^2 0.971,
    residual sd 0.46 doublings; p80 4.492, R^2 0.966, 0.49. Frontier ECI above the top
    calibration pair (156.76) is an extrapolation. METR's series is discontinued, so this
    overlap will not grow; new calibration points must come from our own horizon fits (TODO.md).
  remote work: METR's method for benchmarks with only an overall score ("How Does Time
    Horizon Vary Across Domains?", METR 2025-07-14): P(success on a task of human length t)
    = 1 / (1 + exp(-BETA * (log2 h - log2 t))) with METR's average slope BETA = 0.6 per
    doubling; h = the horizon at which the mean predicted success over RLI's projects equals
    the automation rate; the 80% horizon of the same model is h50 / 2^(ln 4 / BETA) (4.96x
    shorter). RLI's project lengths: the completion-time histogram of the RLI paper
    (arXiv 2510.26787 v1, Fig. 4; RLI_HIST, decoded from the vector figure: 12 equal log bins,
    199 projects, median 11.6 h vs the stated 11.5 h) plus the stated min 0.2 h and max 450 h,
    which lie outside the plotted bins (199 + 2 = 84% of 240 projects have times, as stated).
    Each bin's projects are spread evenly in log time. Far from RLI's median length (low
    automation rates, early 2025) the result is very sensitive to BETA (METR's caveat).
  blend: sqrt(software x remote) at one success level, as of each date on which either
    component changed, from the first date both exist.

CROSS-CHECKS (not KPI inputs; the task-horizon driver's tripwire in data drivers.yaml reads the gaps)
  horizon-80-gap-swe-marathon / -metr: per month (obs YYYY-MM, as of the month end or today), the
    mean over the source's frontier models of log2(measured 80% horizon) - log2(the ECI-converted
    80% horizon of the same model), in doublings. Frontier models = models measured by the source
    (SWE-Marathon: best configuration by h80; METR: its TH1.1 file, models mapped to ECI names in
    CALIBRATION_PAIRS, so they are in-sample residuals) released by then with an ECI score within
    GAP_WINDOW points of the ECI frontier then. No such model: no row; a held month that loses its
    models (an ECI refit moved the window) keeps its last row (a diagnostic, not a KPI series:
    warned, not fatal). A new METR model needs its ECI name in CALIBRATION_PAIRS (that is the
    out-of-sample check if METR resumes); refitting on it is a reviewed change (--calibrate).
  terminal-bench-4-pass-by-release: release-cohort frontier of the Terminal-Bench 4.0 resolution
    rate (%, any agent/effort configuration; terminal_bench.py). Its expert time estimates do not
    predict failures, so it gives no horizon, only an independent (non-ECI) pace signal.
  Calibration lab effects at 80% (recorded, not applied; 2026-10-17): mean residual of the 21
  calibration pairs Anthropic +0.19 +- 0.18 doublings (8 models), OpenAI -0.16 +- 0.14 (11),
  Google +0.13 (2); at 50% Anthropic +0.39 +- 0.12, OpenAI -0.24 +- 0.10 (Epoch, 2025-12-12:
  ECI underpredicted Claude horizons by ~30%).

SERIES CHOICES
  - obs = the model's release date (the files have no evaluation dates): "best among models
    released by that date" per the CURRENT vintage. Epoch refits ECI as benchmarks are added
    and METR re-estimated models between suite versions, so every date the ledger already
    holds for a metric is re-stated against the current vintage (a revised-away peak gets a
    corrected newer row instead of lingering).
  - ECI-derived rows start at ECI_START (GPT-4's release): the ECI file's earlier rows are
    a handful of small models, not the frontier of their time.
  - Ties on one date keep the higher value. value = rounded half-up (ECI, % 2 dp; hours 3 dp);
    notes name the model(s).
  - The METR p50/p80 series are computed independently (METR's is_sota flag tracks p50 only).
  - The metr-*-horizon-frontier ids also date models, but they are frozen: they keep only the
    pilot-2025 values from METR's v1 file, re-verified on 2026-10-16. Later vintages re-score
    old models, so the current file gets its own ids (*-by-release) instead of revising that
    history.
  - published: no registry release lag -> basis=seen (published = retrieved).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import math
import os
import re
import sys
import zipfile
from decimal import Decimal, InvalidOperation

import common
import kpi
import swe_marathon
import terminal_bench

SECTION = "robots-software"
URL = "https://metr.org/assets/benchmark_results_1_1.yaml"
METRICS = {"p50": "metr-50-horizon-by-release", "p80": "metr-80-horizon-by-release"}
EPOCH_URL = "https://epoch.ai/data/benchmark_data.zip"
ECI_MEMBER = "epoch_capabilities_index/eci_scores.csv"
RLI_MEMBER = "rli_external.csv"
ECI, RLI = "eci-frontier-by-release", "rli-automation-by-release"
SOFTWARE, REMOTE, BLEND = "horizon-50-software-eci", "horizon-50-remote-rli", "horizon-50-blended"
SOFTWARE80, REMOTE80, BLEND80 = "horizon-80-software-eci", "horizon-80-remote-rli", "horizon-80-blended"
# horizon metric -> (component kind, success level); the blends combine the two kinds at one level
HORIZONS = {SOFTWARE: ("software", "p50"), REMOTE: ("remote", "p50"), BLEND: ("blend", "p50"),
            SOFTWARE80: ("software", "p80"), REMOTE80: ("remote", "p80"), BLEND80: ("blend", "p80")}
ECI_START = "2023-03-14"
SWE80, SWE50 = "swe-marathon-h80-by-release", "swe-marathon-h50-by-release"
SWE_VERSION = "v1.1"   # the suite the swe-marathon-* ids measure; another version = new ids
# cross-checks of the frozen ECI calibration (the task-horizon driver's tripwire, data drivers.yaml)
GAP_SWE, GAP_METR = "horizon-80-gap-swe-marathon", "horizon-80-gap-metr"
GAP_WINDOW = 5   # ECI points below the month's ECI frontier that still count as frontier (~1 doubling)
TB4 = "terminal-bench-4-pass-by-release"

# METR TH1.1 model id -> Epoch ECI model name (models in both files; Mythos Preview, GPT-5.1
# Codex Max and pre-2023 models have no ECI score).
CALIBRATION_PAIRS = {
    "gpt_4": "GPT-4 (Mar 2023)", "gpt_4_1106_inspect": "GPT-4 Turbo (Nov 2023)",
    "claude_3_opus_inspect": "Claude 3 Opus", "gpt_4_turbo_inspect": "GPT-4 Turbo (Apr 2024)",
    "gpt_4o_inspect": "GPT-4o (May 2024)", "claude_3_5_sonnet_20240620_inspect": "Claude 3.5 Sonnet",
    "o1_preview": "o1-preview", "claude_3_5_sonnet_20241022_inspect": "Claude 3.5 Sonnet (October 2024)",
    "o1_inspect": "o1", "claude_3_7_sonnet_inspect": "Claude 3.7 Sonnet", "o3_inspect": "o3",
    "claude_4_opus_inspect": "Claude Opus 4", "claude_4_1_opus_inspect": "Claude Opus 4.1",
    "gpt_5_2025_08_07_inspect": "GPT-5", "gemini_3_pro": "Gemini 3 Pro", "claude_opus_4_5_inspect": "Claude Opus 4.5",
    "gpt_5_2": "GPT-5.2", "claude_opus_4_6_inspect": "Claude Opus 4.6", "gpt_5_3_codex": "GPT-5.3 Codex",
    "gemini_3_1_pro": "Gemini 3.1 Pro", "gpt_5_4": "GPT-5.4",
}
# log2(METR horizon minutes) = a + b * ECI, per success level (see --calibrate)
ECI_CAL = {"p50": (-26.366541, 0.226507), "p80": (-28.242299, 0.222614)}
BETA = 0.6
RLI_HIST = {"log10_lo": -0.31, "log10_hi": 2.43, "counts": [1, 9, 5, 10, 38, 36, 31, 27, 14, 16, 8, 4],
            "extremes_h": [0.2, 450.0]}


# --- METR ------------------------------------------------------------------------------------------
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


def best_as_of(ms: list[dict], q: str, when: dt.date) -> dict | None:
    """Model with the highest q estimate among those released by `when`."""
    pool = [m for m in ms if q in m and dt.date.fromisoformat(m["release"]) <= when]
    return max(pool, key=lambda m: (m[q]["estimate"], m["release"]), default=None)


# --- Epoch: ECI and RLI ---------------------------------------------------------------------------
def epoch_members(data: bytes) -> dict[str, list[dict]]:
    """{member: csv rows} of the Epoch benchmark zip (ECI scores, RLI)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise SystemExit(f"{EPOCH_URL}: not a zip file")
    out = {}
    for name, need in ((ECI_MEMBER, {"Model", "eci", "date"}), (RLI_MEMBER, {"Model version", "Score", "Release date"})):
        if name not in z.namelist():
            raise SystemExit(f"{EPOCH_URL}: no member {name}")
        rows = list(csv.DictReader(io.TextIOWrapper(z.open(name), encoding="utf-8-sig")))
        if not rows or not need <= set(rows[0]):
            raise SystemExit(f"{EPOCH_URL}: {name} lacks columns {sorted(need)}")
        out[name] = rows
    return out


def number(text: str, what: str) -> Decimal:
    """A finite decimal from the source text (exact, so half-up rounding is honest); else fail loudly."""
    try:
        v = Decimal(text.strip())
    except InvalidOperation:
        v = None
    if v is None or not v.is_finite():
        raise SystemExit(f"{EPOCH_URL}: {what}: '{text}' is not a finite number")
    return v


def eci_models(rows: list[dict]) -> list[dict]:
    """[{id, release, value, ci}] of the ECI file (rows without a score or date are skipped)."""
    out = []
    for r in rows:
        if r["eci"].strip() and r["date"].strip():
            dt.date.fromisoformat(r["date"])  # malformed date -> fail loudly
            ci = (f"; 90% CI {r['eci_ci_low']}-{r['eci_ci_high']}"
                  if r.get("eci_ci_low", "").strip() and r.get("eci_ci_high", "").strip() else "")
            out.append({"id": r["Model"], "release": r["date"], "value": number(r["eci"], f"ECI of {r['Model']}"),
                        "ci": ci})
    return out


def rli_models(rows: list[dict]) -> list[dict]:
    """[{id, release, value}] of Epoch's RLI mirror; value = automation rate in % (score x 100, exact)."""
    out = []
    for r in rows:
        if r["Score"].strip() and r["Release date"].strip():
            dt.date.fromisoformat(r["Release date"])
            s = number(r["Score"], f"RLI score of {r['Model version']}")
            if not 0 <= s <= 1:
                raise SystemExit(f"{EPOCH_URL}: RLI score {s} of {r['Model version']} is not a fraction")
            out.append({"id": r["Model version"], "release": r["Release date"], "value": 100 * s, "ci": ""})
    return out


def steps(ms: list[dict], since: str = "") -> list[dict]:
    """Release-cohort frontier: models that beat every earlier release, in release order
    (a same-date tie keeps the higher value). Only steps dated >= since are returned, but
    earlier models still count towards the running best."""
    best, out = None, []
    for m in sorted(ms, key=lambda m: (m["release"], -m["value"], m["id"])):
        if best is None or m["value"] > best:
            best = m["value"]
            if m["release"] >= since:
                out.append(m)
    return out


def at(step: list[dict], when: dt.date) -> dict | None:
    """The frontier step in force on `when` (the last one released by then)."""
    pool = [m for m in step if dt.date.fromisoformat(m["release"]) <= when]
    return pool[-1] if pool else None


def eci_hours(eci, q: str = "p50") -> float:
    """METR-equivalent 50% (q=p50) or 80% (p80) horizon (hours) of an ECI score (frozen calibration)."""
    a, b = ECI_CAL[q]
    return 2 ** (a + b * float(eci)) / 60


def rli_tasks() -> list[float]:
    """log2 hours of RLI's projects with a completion time (RLI_HIST, see the module doc)."""
    lo, hi, cs = RLI_HIST["log10_lo"], RLI_HIST["log10_hi"], RLI_HIST["counts"]
    w = (hi - lo) / len(cs)
    out = [math.log2(10 ** (lo + w * (i + (k + 0.5) / c))) for i, c in enumerate(cs) for k in range(c)]
    return out + [math.log2(h) for h in RLI_HIST["extremes_h"]]


def rli_hours(rate_pct) -> float | None:
    """50% horizon (hours) at which METR's logistic model, averaged over RLI's projects,
    predicts the given automation rate; None at 0% or 100% (no finite horizon)."""
    p = float(rate_pct) / 100
    if not 0 < p < 1:
        return None
    tasks = rli_tasks()

    def score(lh: float) -> float:
        return sum(1 / (1 + math.exp(-BETA * (lh - t))) for t in tasks) / len(tasks)
    lo, hi = -40.0, 60.0   # log2 hours; score() is increasing in lh
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if score(mid) < p else (lo, mid)
    return 2 ** ((lo + hi) / 2)


def rli_hours80(rate_pct) -> float | None:
    """80% horizon of the same logistic model: success 80% at a task 2^(ln 4 / BETA) times shorter."""
    h = rli_hours(rate_pct)
    return None if h is None else h * 2 ** (-math.log(4) / BETA)


def calibrate(metr_models: list[dict], eci: list[dict], q: str = "p50") -> dict:
    """OLS of log2(METR q-horizon minutes) on ECI over CALIBRATION_PAIRS present in both files;
    pred_se(eci) = the standard error of a new model's log2 horizon at that ECI (doublings)."""
    by_id = {m["id"]: m for m in metr_models if q in m}
    by_name = {m["id"]: float(m["value"]) for m in eci}
    pts = [(by_name[e], math.log2(by_id[mid][q]["estimate"]))
           for mid, e in CALIBRATION_PAIRS.items() if mid in by_id and e in by_name]
    n = len(pts)
    if n < 10:
        raise SystemExit(f"calibration: only {n} METR/ECI pairs found")
    mx, my = sum(x for x, _ in pts) / n, sum(y for _, y in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    b = sum((x - mx) * (y - my) for x, y in pts) / sxx
    a = my - b * mx
    res = [y - a - b * x for x, y in pts]
    sd = math.sqrt(sum(r * r for r in res) / (n - 2))
    return {"n": n, "a": a, "b": b, "eci_per_doubling": 1 / b, "resid_sd": sd,
            "pred_se": lambda e: sd * math.sqrt(1 + 1 / n + (e - mx) ** 2 / sxx),
            "r2": 1 - sum(r * r for r in res) / sum((y - my) ** 2 for _, y in pts),
            "top_eci": max(x for x, _ in pts)}


# --- collection --------------------------------------------------------------------------------------
def collect(fixture: str | None, today: dt.date, collector: str, existing=()) -> list[dict]:
    reg = common.registry(SECTION)
    rows = []
    held = {}   # metric -> obs dates already in the ledger
    for r in existing:
        held.setdefault(r["metric"], set()).add(r["obs"])

    def add(metric, obs, value, places, source, note):
        rows.append(common.row(reg, metric, obs, common.round_half_up(value, places), source, note,
                               collector, str(today)))

    # METR (discontinued; the calibration source)
    bench, ms = models(common.fetch(URL, fixture))
    for q, metric in METRICS.items():
        def add_metr(obs, m, what, q=q, metric=metric):
            e = m[q]
            ci = f"; CI {e['ci_low']:.2f}-{e['ci_high']:.2f} min" if "ci_low" in e and "ci_high" in e else ""
            add(metric, obs, e["estimate"], 2, URL,
                f"{what}: {m['id']} ({m['benchmark'] or bench}{ci}); dated by model release_date "
                f"in METR's {bench} results file (no evaluation date in the file)")
        new = {m["release"]: m for m in frontier(ms, q)}
        for obs, m in new.items():
            add_metr(obs, m, f"new best {q} by release date")
        # Re-state every other date already in the ledger for this metric against the
        # current vintage, so a re-estimated (or removed) model cannot leave a stale peak.
        for obs in sorted(held.get(metric, set()) - set(new)):
            if m := best_as_of(ms, q, kpi.obs_range(obs)[1]):
                add_metr(obs, m, f"best {q} among models released by {obs} per the current file, set by {m['release']}")

    # Epoch: ECI and RLI frontiers, and the horizons
    files = epoch_members(common.fetch_bytes(EPOCH_URL, fixture))
    eci = steps(eci_models(files[ECI_MEMBER]), ECI_START)
    rli = steps(rli_models(files[RLI_MEMBER]))
    rli_h = [m for m in rli if rli_hours(m["value"]) is not None]   # 0% / 100%: no finite horizon
    if not eci or not rli_h:
        raise SystemExit(f"{EPOCH_URL}: empty ECI or RLI series")

    def horizon(kind: str, q: str, m: dict) -> tuple[float, str]:
        if kind == "software":
            return eci_hours(m["value"], q), f"ECI {common.round_half_up(m['value'], 2)} of {m['id']}"
        return ((rli_hours if q == "p50" else rli_hours80)(m["value"]),
                f"RLI automation rate {common.round_half_up(m['value'], 2)}% of {m['id']}")

    # SWE-Marathon: directly measured horizons (METR's method on 20 long tasks; swe_marathon.py)
    sw = swe_marathon.fetch(os.path.join(fixture, "swe-marathon") if fixture else None)
    if sw["version"] != SWE_VERSION:
        raise SystemExit(f"{swe_marathon.INDEX_URL}: suite {sw['version']}, the swe-marathon-* ids measure "
                         f"{SWE_VERSION}: register new ids for the new suite (and retire these)")
    released = {m["id"]: m["release"] for m in eci_models(files[ECI_MEMBER])}
    swm = {SWE80: [], SWE50: []}
    for model, f in swe_marathon.best_by_model(swe_marathon.configs(sw["trials"], sw["tasks"])).items():
        rel = released.get(model) or f["first"][:10]
        how = "its release date (Epoch)" if model in released else "its first SWE-Marathon trial (release date unknown)"
        ci = (f"; {f['agent']}, effort {f['effort'] or 'default'}, {f['successes']}/{f['n']} trials on {f['tasks']} tasks, "
              f"beta {f['beta']:.2f}, h80 95% CI {f['h80_lo']:.2f}-{f['h80_hi']:.2f} h"
              + (f", h80 extrapolated {f['extrapolated']} the task lengths" if f["extrapolated"] else "")
              + f"; dated by {how}")
        for metric, q in ((SWE80, "h80"), (SWE50, "h50")):
            swm[metric].append({"id": model, "release": rel, "value": Decimal(repr(f[q])), "ci": ci})

    # cross-checks of the calibration: monthly gaps (measured - converted), Terminal-Bench 4.0 rates
    eci_all = [(m["release"], float(m["value"])) for m in eci_models(files[ECI_MEMBER])]
    eci_of = {m["id"]: float(m["value"]) for m in eci_models(files[ECI_MEMBER])}
    measured = {
        GAP_SWE: [(m["id"], m["release"], eci_of[m["id"]], float(m["value"])) for m in swm[SWE80] if m["id"] in eci_of],
        GAP_METR: [(mid, m["release"], eci_of[CALIBRATION_PAIRS[mid]], m["p80"]["estimate"] / 60) for m in ms
                   if "p80" in m and (mid := m["id"]) in CALIBRATION_PAIRS and CALIBRATION_PAIRS[mid] in eci_of]}
    src_of = {GAP_SWE: swe_marathon.INDEX_URL, GAP_METR: URL}
    for metric, pts in measured.items():
        gaps = gap_months(pts, eci_all, today)
        for obs, (g, pool) in gaps.items():
            add(metric, obs, g, 2, src_of[metric],
                f"mean of log2(measured / ECI-converted 80% horizon) over {len(pool)} model(s) within {GAP_WINDOW} "
                f"ECI points of the ECI frontier as of {min(kpi.obs_range(obs)[1], today)}: "
                + ", ".join(f"{i} (ECI {e:.2f}, {h:.2f} h vs {eci_hours(e, 'p80'):.2f} h)" for i, e, h in pool))
        for obs in sorted(held.get(metric, set()) - set(gaps)):
            print(f"warning: {metric} {obs}: no frontier model of the current vintages; the held row stays",
                  file=sys.stderr)
    tb = [{"id": f"{r['model']} ({r['agent']}, effort {r['effort']})", "release": r["release"],
           "value": Decimal(repr(r["accuracy"])),
           "ci": f"; {r['n_trials']} trials, 95% CI +-{r['ci95']} pp"} for r in
          terminal_bench.rows(common.fetch(terminal_bench.URL, os.path.join(fixture, "tbench") if fixture else None))]

    series = {ECI: eci, RLI: rli, SWE80: steps(swm[SWE80]), SWE50: steps(swm[SWE50]), TB4: steps(tb)}
    for metric, (kind, q) in HORIZONS.items():
        if kind != "blend":
            series[metric] = eci if kind == "software" else rli_h

    def emit(metric: str, obs: str, when: dt.date, fresh: bool) -> None:
        """One row of `metric` for `obs`, from the frontier step(s) in force on `when`. A date
        already in the ledger that no model in the current vintage covers fails loudly: the
        source dropped or re-dated the models behind it, and a human must withdraw the rows."""
        tag = "new" if fresh else f"re-stated as of {obs} per the current file:"
        kind, q = HORIZONS.get(metric, ("raw", ""))
        parts = [at(eci, when), at(rli_h, when)] if kind == "blend" else [at(series[metric], when)]
        if None in parts:
            src = (swe_marathon.INDEX_URL if metric in (SWE80, SWE50) else terminal_bench.URL if metric == TB4
                   else EPOCH_URL)
            raise SystemExit(f"{metric} {obs}: held in the ledger, but no model of the current "
                             f"{src} vintage covers that date (withdraw the rows by hand)")
        m = parts[0]
        if metric in (ECI, RLI):
            add(metric, obs, m["value"], 2, EPOCH_URL,
                f"{tag} best by release date: {m['id']} (released {m['release']}{m['ci']})")
        elif metric in (SWE80, SWE50):
            add(metric, obs, m["value"], 3, swe_marathon.INDEX_URL,
                f"{tag} best by release date: {m['id']} (best configuration by h80{m['ci']})")
        elif metric == TB4:
            add(metric, obs, m["value"], 2, terminal_bench.URL,
                f"{tag} best Terminal-Bench 4.0 resolution rate by model release date: {m['id']}, released "
                f"{m['release']}{m['ci']}")
        elif kind in ("software", "remote"):
            h, what = horizon(kind, q, m)
            add(metric, obs, h, 3, EPOCH_URL, f"{tag} best by release date: {what} (released {m['release']}) "
                + (f"-> METR-equivalent via the frozen ECI calibration ({q})" if kind == "software"
                   else f"-> METR overall-score method (slope {BETA}, RLI paper's project lengths; {q})"))
        else:  # a blend, from the unrounded components
            (hs, ws), (hr, wr) = horizon("software", q, parts[0]), horizon("remote", q, parts[1])
            add(metric, obs, math.sqrt(hs * hr), 3, EPOCH_URL,
                f"{tag} geometric mean of software {hs:.3f} h ({ws}) and remote work {hr:.3f} h ({wr})")

    new = {k: [m["release"] for m in v] for k, v in series.items()}
    first = max(eci[0]["release"], rli_h[0]["release"])
    for b in (BLEND, BLEND80):
        new[b] = sorted({d for d in new[ECI] + [m["release"] for m in rli_h] if d >= first})
    for metric in (ECI, RLI, *HORIZONS, SWE80, SWE50, TB4):
        for obs in new[metric]:
            emit(metric, obs, dt.date.fromisoformat(obs), True)
        for obs in sorted(held.get(metric, set()) - set(new[metric])):
            emit(metric, obs, kpi.obs_range(obs)[1], False)
    return rows


def gap_months(pts: list[tuple], eci_all: list[tuple[str, float]], today: dt.date) -> dict[str, tuple]:
    """{YYYY-MM: (mean gap in doublings, [(model, eci, measured h80)])} from the month of the first
    measured model to today's: pts [(model, release, eci, measured 80% horizon h)], eci_all
    [(release, eci)] of every ECI model (the frontier). Months without a frontier model are absent."""
    if not pts:
        return {}
    out = {}
    y, mo = map(int, min(p[1] for p in pts)[:7].split("-"))
    while (y, mo) <= (today.year, today.month):
        obs = f"{y:04d}-{mo:02d}"
        end = min(kpi.obs_range(obs)[1], today)
        top = max((e for d, e in eci_all if dt.date.fromisoformat(d) <= end), default=None)
        pool = sorted(((i, e, h) for i, d, e, h in pts if dt.date.fromisoformat(d) <= end and top is not None
                       and e >= top - GAP_WINDOW), key=lambda p: (-p[1], p[0]))
        if pool:
            out[obs] = (sum(math.log2(h / eci_hours(e, "p80")) for _, e, h in pool) / len(pool), pool)
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return out


def main() -> int:
    if "--calibrate" not in sys.argv:
        return common.main(SECTION, __file__, collect)
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--fixture")
    a = ap.parse_args()
    _, ms = models(common.fetch(URL, a.fixture))
    eci = eci_models(epoch_members(common.fetch_bytes(EPOCH_URL, a.fixture))[ECI_MEMBER])
    top = max(eci, key=lambda m: m["value"])
    for q in ECI_CAL:
        c = calibrate(ms, eci, q)
        print(f"{q} pairs {c['n']}: a {c['a']:.6f} b {c['b']:.6f} ({c['eci_per_doubling']:.3f} ECI per doubling), "
              f"R^2 {c['r2']:.3f}, residual sd {c['resid_sd']:.3f} doublings, top pair ECI {c['top_eci']:.2f}; "
              f"prediction se at the frontier ECI {float(top['value']):.2f}: {c['pred_se'](float(top['value'])):.3f} doublings")
        print(f"  frozen: a {ECI_CAL[q][0]:.6f} b {ECI_CAL[q][1]:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
