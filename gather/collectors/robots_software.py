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

The KPI (framework.yaml, metrics/kpi-assessment.csv) is horizon-50-blended: the geometric
mean of two 50%-success task horizons in human-hours, both release-cohort series (the best
among models RELEASED by the obs date, from the current file vintages):
  horizon-50-software-eci    METR-equivalent software horizon converted from the Epoch
                             Capabilities Index frontier (eci-frontier-by-release)
  horizon-50-remote-rli      remote-freelance-work horizon converted from the Remote Labor
                             Index automation-rate frontier (rli-automation-by-release)

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
  still collected (cheap; a resumed series would show up) and it is the calibration source.
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
  software: log2(METR p50 minutes) = ECI_A + ECI_B * ECI, an OLS fit over the 21 models in both
    METR's TH1.1 file and Epoch's ECI file (CALIBRATION_PAIRS; fitted 2026-10-16 on the ECI
    vintage of 2026-10-15: 4.415 ECI points per doubling, R^2 0.971, residual sd 0.46
    doublings). Frontier ECI above the top calibration pair (156.76) is an extrapolation.
  remote work: METR's method for benchmarks with only an overall score ("How Does Time
    Horizon Vary Across Domains?", METR 2025-07-14): P(success on a task of human length t)
    = 1 / (1 + exp(-BETA * (log2 h - log2 t))) with METR's average slope BETA = 0.6 per
    doubling; h = the horizon at which the mean predicted success over RLI's projects equals
    the automation rate. RLI's project lengths: the completion-time histogram of the RLI paper
    (arXiv 2510.26787 v1, Fig. 4; RLI_HIST, decoded from the vector figure: 12 equal log bins,
    199 projects, median 11.6 h vs the stated 11.5 h) plus the stated min 0.2 h and max 450 h,
    which lie outside the plotted bins (199 + 2 = 84% of 240 projects have times, as stated).
    Each bin's projects are spread evenly in log time. Far from RLI's median length (low
    automation rates, early 2025) the result is very sensitive to BETA (METR's caveat).
  blend: sqrt(software x remote) as of each date on which either component changed, from the
    first date both exist.

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
  - published: no registry release lag -> basis=seen (published = retrieved).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import math
import re
import sys
import zipfile

import common
import kpi

SECTION = "robots-software"
URL = "https://metr.org/assets/benchmark_results_1_1.yaml"
METRICS = {"p50": "metr-50-horizon-by-release", "p80": "metr-80-horizon-by-release"}
EPOCH_URL = "https://epoch.ai/data/benchmark_data.zip"
ECI_MEMBER = "epoch_capabilities_index/eci_scores.csv"
RLI_MEMBER = "rli_external.csv"
ECI, RLI = "eci-frontier-by-release", "rli-automation-by-release"
SOFTWARE, REMOTE, BLEND = "horizon-50-software-eci", "horizon-50-remote-rli", "horizon-50-blended"
ECI_START = "2023-03-14"

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
ECI_A, ECI_B = -26.366541, 0.226507   # log2(p50 minutes) = ECI_A + ECI_B * ECI (see --calibrate)
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


def eci_models(rows: list[dict]) -> list[dict]:
    """[{id, release, value, ci}] of the ECI file (rows without a score or date are skipped)."""
    out = []
    for r in rows:
        if r["eci"].strip() and r["date"].strip():
            dt.date.fromisoformat(r["date"])  # malformed date -> fail loudly
            ci = (f"; 90% CI {r['eci_ci_low']}-{r['eci_ci_high']}"
                  if r.get("eci_ci_low", "").strip() and r.get("eci_ci_high", "").strip() else "")
            out.append({"id": r["Model"], "release": r["date"], "value": float(r["eci"]), "ci": ci})
    return out


def rli_models(rows: list[dict]) -> list[dict]:
    """[{id, release, value}] of Epoch's RLI mirror; value = automation rate in %."""
    out = []
    for r in rows:
        if r["Score"].strip() and r["Release date"].strip():
            dt.date.fromisoformat(r["Release date"])
            s = float(r["Score"])
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


def eci_hours(eci: float) -> float:
    """METR-equivalent 50% horizon (hours) of an ECI score (frozen calibration)."""
    return 2 ** (ECI_A + ECI_B * eci) / 60


def rli_tasks() -> list[float]:
    """log2 hours of RLI's projects with a completion time (RLI_HIST, see the module doc)."""
    lo, hi, cs = RLI_HIST["log10_lo"], RLI_HIST["log10_hi"], RLI_HIST["counts"]
    w = (hi - lo) / len(cs)
    out = [math.log2(10 ** (lo + w * (i + (k + 0.5) / c))) for i, c in enumerate(cs) for k in range(c)]
    return out + [math.log2(h) for h in RLI_HIST["extremes_h"]]


def rli_hours(rate_pct: float) -> float | None:
    """50% horizon (hours) at which METR's logistic model, averaged over RLI's projects,
    predicts the given automation rate; None at 0% or 100% (no finite horizon)."""
    p = rate_pct / 100
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


def calibrate(metr_models: list[dict], eci: list[dict]) -> dict:
    """OLS of log2(METR p50 minutes) on ECI over CALIBRATION_PAIRS present in both files."""
    by_id = {m["id"]: m for m in metr_models if "p50" in m}
    by_name = {m["id"]: m["value"] for m in eci}
    pts = [(by_name[e], math.log2(by_id[mid]["p50"]["estimate"]))
           for mid, e in CALIBRATION_PAIRS.items() if mid in by_id and e in by_name]
    n = len(pts)
    if n < 10:
        raise SystemExit(f"calibration: only {n} METR/ECI pairs found")
    mx, my = sum(x for x, _ in pts) / n, sum(y for _, y in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    b = sum((x - mx) * (y - my) for x, y in pts) / sxx
    a = my - b * mx
    res = [y - a - b * x for x, y in pts]
    return {"n": n, "a": a, "b": b, "eci_per_doubling": 1 / b,
            "resid_sd": math.sqrt(sum(r * r for r in res) / (n - 2)),
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
    rli = [m for m in steps(rli_models(files[RLI_MEMBER])) if m["value"] > 0]
    if not eci or not rli:
        raise SystemExit(f"{EPOCH_URL}: empty ECI or RLI series")

    def horizon(metric: str, m: dict) -> tuple[float, str]:
        if metric == SOFTWARE:
            return eci_hours(m["value"]), f"ECI {m['value']:.2f} of {m['id']}"
        return rli_hours(m["value"]), f"RLI automation rate {m['value']:.2f}% of {m['id']}"

    def emit(metric: str, obs: str, when: dt.date | None, fresh: bool) -> None:
        """One row of `metric` for `obs`, from the frontier step(s) in force on `when`."""
        tag = "new" if fresh else f"re-stated as of {obs} per the current file:"
        if metric in (ECI, RLI):
            m = at(eci if metric == ECI else rli, when)
            if m:
                add(metric, obs, m["value"], 2, EPOCH_URL,
                    f"{tag} best by release date: {m['id']} (released {m['release']}{m['ci']})")
        elif metric in (SOFTWARE, REMOTE):
            m = at(eci if metric == SOFTWARE else rli, when)
            if m:
                h, what = horizon(metric, m)
                add(metric, obs, h, 3, EPOCH_URL, f"{tag} best by release date: {what} (released {m['release']}) "
                    + ("-> METR-equivalent via the frozen ECI calibration" if metric == SOFTWARE
                       else f"-> METR overall-score method (slope {BETA}, RLI paper's project lengths)"))
        else:  # BLEND
            s, r = at(eci, when), at(rli, when)
            if s and r:
                hs, ws = horizon(SOFTWARE, s)
                hr, wr = horizon(REMOTE, r)
                add(BLEND, obs, math.sqrt(hs * hr), 3, EPOCH_URL,
                    f"{tag} geometric mean of software {hs:.3f} h ({ws}) and remote work {hr:.3f} h ({wr})")

    new = {ECI: [m["release"] for m in eci], RLI: [m["release"] for m in rli]}
    new[SOFTWARE], new[REMOTE] = new[ECI], new[RLI]
    first = max(eci[0]["release"], rli[0]["release"])
    new[BLEND] = sorted({d for d in new[ECI] + new[RLI] if d >= first})
    for metric in (ECI, RLI, SOFTWARE, REMOTE, BLEND):
        for obs in new[metric]:
            emit(metric, obs, dt.date.fromisoformat(obs), True)
        for obs in sorted(held.get(metric, set()) - set(new[metric])):
            emit(metric, obs, kpi.obs_range(obs)[1], False)
    return rows


def main() -> int:
    if "--calibrate" not in sys.argv:
        return common.main(SECTION, __file__, collect)
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--fixture")
    a = ap.parse_args()
    _, ms = models(common.fetch(URL, a.fixture))
    c = calibrate(ms, eci_models(epoch_members(common.fetch_bytes(EPOCH_URL, a.fixture))[ECI_MEMBER]))
    print(f"pairs {c['n']}: a {c['a']:.6f} b {c['b']:.6f} ({c['eci_per_doubling']:.3f} ECI per doubling), "
          f"R^2 {c['r2']:.3f}, residual sd {c['resid_sd']:.3f} doublings, top pair ECI {c['top_eci']:.2f}")
    print(f"frozen: a {ECI_A:.6f} b {ECI_B:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
