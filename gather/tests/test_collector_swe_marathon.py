#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Offline tests for gather/collectors/swe_marathon.py (SWE-Marathon trials -> METR-style horizons).

Run:  uv run gather/tests/test_collector_swe_marathon.py     (no network; the source is
      gather/tests/fixtures/swe-marathon/: the real index.html of 2026-10-16 and its bundle
      index-BMEz9I0h.js trimmed to verbatim slices: React's `version:`18.3.1`` object, the
      task.toml array with 4 of its 20 task objects (embedding-eval 4 h, zstd-decoder 12 h,
      kubernetes-rust-rewrite 200 h, excel-clone 380 h), the results object with those tasks
      and 4 of 59 configurations (JSON re-serialized compactly, fields untouched), and the
      page template that mentions expert_time_estimate_hours)
"""
import math
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATHER = os.path.dirname(HERE)
FIXDIR = os.path.join(HERE, "fixtures", "swe-marathon")
sys.path.insert(0, os.path.join(GATHER, "collectors"))

import swe_marathon as sm  # noqa: E402

FAILS = []


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except ValueError:
        return True
    return False


with open(os.path.join(FIXDIR, "index.html"), encoding="utf-8") as f:
    HTML = f.read()
BUNDLE_NAME = sm.bundle_url(HTML).rsplit("/", 1)[-1]
with open(os.path.join(FIXDIR, BUNDLE_NAME), encoding="utf-8") as f:
    BUNDLE = f.read()

# --- parsing the real page ------------------------------------------------------------------
d = sm.fetch(FIXDIR)
case("fetch: the fixture page names its bundle, which is read by its own basename",
     d["bundle"] == "https://www.swe-marathon.org/assets/index-BMEz9I0h.js")
case("parse: version from the results object, not React's version:`18.3.1`", d["version"] == "v1.1")
case("parse: hours mapped to tasks from the task.toml objects",
     d["tasks"] == {"embedding-eval": 4.0, "zstd-decoder": 12.0, "kubernetes-rust-rewrite": 200.0, "excel-clone": 380.0})
tr = d["trials"]
case("parse: every trial of the 4 configurations x 4 tasks x 8", len(tr) == 128)
case("parse: a configuration without reasoningEffort has effort None",
     {t.effort for t in tr if t.model == "Claude Opus 4.8"} == {None})
glm = [t for t in tr if t.model == "GLM 5.3"]
case("parse: error-status trials kept with their reward (some errored trials passed the verifier)",
     sum(t.status == "error" for t in glm) == 13 and any(t.status == "error" and t.reward == 1 for t in glm))
case("parse: deterministic order (task, then source order)", tr == sm.parse(HTML, BUNDLE)["trials"]
     and [t.task for t in tr] == sorted(t.task for t in tr))

# --- failing loudly -------------------------------------------------------------------------
case("parse: a task without an hour estimate is refused",
     raises(sm.parse, HTML, BUNDLE.replace("expert_time_estimate_hours:200", "expert_time_estimate_hourz:200")))
case("parse: a task missing from the task.toml array is refused",
     raises(sm.parse, HTML, BUNDLE.replace("{id:`zstd-decoder`", "{id:`zstd-decoder-v2`")))
tasks_lit = BUNDLE[BUNDLE.index("Ze={"):BUNDLE.index(",Qe={")]
case("parse: an unrelated tasks:[...] array (another suite version) is ignored",
     sm.parse(HTML, BUNDLE.replace(",Qe={", ",Ye=" + tasks_lit[3:].replace("{id:`excel-clone`", "{id:`excel-clone-v0`")
                                   + ",Qe={"))["tasks"] == d["tasks"])
case("parse: two arrays covering the result tasks are ambiguous",
     raises(sm.parse, HTML, BUNDLE.replace(",Qe={", ",Ye=" + tasks_lit[3:] + ",Qe={")))
case("parse: an unknown trial status is refused",
     raises(sm.parse, HTML, BUNDLE.replace('"status":"error"', '"status":"cancelled"', 1)))
case("parse: a non-binary reward is refused",
     raises(sm.parse, HTML, BUNDLE.replace('"reward":1.0', '"reward":0.5', 1)))
case("parse: a page without the bundle script is refused",
     raises(sm.bundle_url, HTML.replace("/assets/index-", "/assets/main-")))
case("JS reader: template escapes are cooked; ${} interpolation is refused",
     sm._JS(r"{a:`x\`y\\z\n\u00e9\x41`,b:[!0,!1,36e3,-1.5,null,Q],c:`p.q`.split(`.`)}", 0).value()
     == {"a": "x`y\\z\néA", "b": [True, False, 36000.0, -1.5, None, sm.Ref("Q")], "c": ["p", "q"]}
     and raises(sm._JS("`a${b}`", 0).value))

# --- fitting --------------------------------------------------------------------------------
HOURS = {f"t{i}": 2 ** (i / 3) for i in range(-6, 31)}   # 0.25 h .. 1024 h, 37 lengths


def synth(h50, beta, n=60, seed=1, task_sd=0.0, model="M", effort="x"):
    """n trials per task from the METR model; task_sd adds a per-task logit offset (heterogeneity)."""
    rnd = random.Random(seed)
    out = []
    for name, h in HOURS.items():
        off = rnd.gauss(0, task_sd) if task_sd else 0.0
        p = 1 / (1 + math.exp(-(beta * (math.log2(h50) - math.log2(h)) + off)))
        out += [sm.Trial(name, "A", model, effort, int(rnd.random() < p), "success",
                         f"2026-08-{1 + k % 28:02d} 12:00 UTC", f"{name}-{k}") for k in range(n)]
    return out


f = sm.fit(synth(16.0, 0.9), HOURS)
true80 = math.log2(16.0) - math.log(4) / 0.9
case("fit: recovers h50 and beta from synthetic trials",
     f["flag"] is None and abs(math.log2(f["h50"]) - 4) < 0.15 and abs(f["beta"] - 0.9) < 0.08)
case("fit: h80 = h50 * 2^(-ln 4 / beta), true h80 inside its 95% CI",
     math.isclose(f["h80"], f["h50"] * 2 ** (-math.log(4) / f["beta"]))
     and f["h80_lo"] < 2 ** true80 < f["h80_hi"])
case("fit: n, successes, tasks, first/last start", f["n"] == 37 * 60 and f["tasks"] == 37
     and f["first"] == "2026-08-01 12:00 UTC" and f["last"] == "2026-08-28 12:00 UTC" and 0 < f["successes"] < f["n"])
het = sm.fit(synth(16.0, 0.9, task_sd=1.5, seed=3), HOURS)
case("fit: task heterogeneity widens the task-clustered SE beyond the model SE, and the CI uses it",
     het["se_log2_h80_cluster"] > 1.5 * het["se_log2_h80_model"] and het["se_log2_h80"] == het["se_log2_h80_cluster"])


def flag(trials):
    r = sm.fit(trials, HOURS)
    return r["flag"] if r["h50"] is None and r["h80"] is None and r["beta"] is None else "HAS-NUMBERS"


T = lambda task, reward, status="success": sm.Trial(task, "A", "M", None, reward, status,  # noqa: E731
                                                     "2026-08-01 00:00 UTC", f"{task}-{reward}")
case("degenerate: no successes -> flagged, no horizon", flag([T("t0", 0), T("t9", 0)]) == "no-successes")
case("degenerate: all successes -> flagged", flag([T("t0", 1), T("t9", 1)]) == "all-successes")
case("degenerate: one task length -> flagged", flag([T("t0", 1), T("t0", 0)]) == "too-few-tasks")
case("degenerate: short tasks all pass, long all fail (also a mixed boundary task) -> separated",
     flag([T("t0", 1), T("t3", 1), T("t6", 0), T("t9", 0)]) == "separated"
     and flag([T("t0", 1), T("t3", 1), T("t3", 0), T("t9", 0)]) == "separated")
case("degenerate: success rising with length -> inverted (separated, or a fitted beta <= 0)",
     flag([T("t0", 0), T("t9", 1)]) == "inverted"
     and flag([T("t0", 0), T("t0", 0), T("t0", 1), T("t9", 1), T("t9", 1), T("t9", 0)]) == "inverted")
low = sm.fit([T("t9", 1), T("t9", 1), T("t9", 0), T("t12", 0), T("t12", 1), T("t12", 0)], HOURS)   # 2/3 at 8 h, 1/3 at 16 h
case("fit: h80 below the fitted task lengths is kept but marked extrapolated",
     low["flag"] is None and low["h80"] < HOURS["t9"] and low["extrapolated"] == "below")
case("fit: a task without hours is refused", raises(sm.fit, [T("nope", 1), T("t0", 0)], HOURS))

errs = [T("t0", 1), T("t3", 0), T("t3", 1), T("t9", 0), T("t9", 1), T("t12", 0), T("t12", 0, "error"), T("t0", 1, "error")]
e1, e2 = sm.fit(errs, HOURS), sm.fit(errs, HOURS, include_errors=True)
case("errors: excluded by default (counted), included on request",
     (e1["n"], e1["errors"], e2["n"], e2["errors"]) == (6, 2, 8, 2) and e1["h80"] != e2["h80"])

# --- grouping, best per model, determinism ----------------------------------------------------
fits = sm.configs(d["trials"], d["tasks"])
case("configs: one fit per (agent, model, effort), errors excluded",
     [(c["model"], c["effort"], c["n"], c["errors"]) for c in fits]
     == [("Claude Opus 4.8", None, 32, 0), ("GLM 5.3", "max", 19, 13), ("GPT-5.6-luna", "low", 32, 0),
         ("Muse Wonder Full", "max", 32, 0)])
shuffled = list(d["trials"])
random.Random(7).shuffle(shuffled)
case("configs: independent of trial order", sm.configs(shuffled, d["tasks"]) == fits)
best = sm.best_by_model(fits)
case("best_by_model: only models with a fitted configuration", set(best) == {"GLM 5.3"})
a, b, c = synth(16.0, 0.9, effort="hi"), synth(16.0, 0.9, effort="lo"), synth(8.0, 0.9, effort="max")
bb = sm.best_by_model(sm.configs(b + a + c, HOURS))["M"]
case("best_by_model: highest h80 (16 h beats 8 h), an exact tie goes to the effort first in sort order",
     bb["effort"] == "hi")

p = subprocess.run([sys.executable, os.path.join(GATHER, "collectors", "swe_marathon.py"), "--fixture", FIXDIR],
                   capture_output=True, text=True, check=False)
case("CLI: --fixture prints the version line and one row per configuration (flags shown)",
     p.returncode == 0 and "SWE-Marathon v1.1" in p.stdout and len(p.stdout.splitlines()) == 2 + 4
     and "no-successes" in p.stdout and "separated" in p.stdout)

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall ok")
sys.exit(1 if FAILS else 0)
