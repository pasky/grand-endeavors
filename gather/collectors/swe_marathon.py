#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""SWE-Marathon per-trial results -> METR-style AI task horizons per agent/model configuration.

Usage:  uv run gather/collectors/swe_marathon.py [--fixture DIR] [--best] [--include-errors]
          prints the per-configuration fits (--best: the best configuration per model)

This module is pure parsing + fitting (no ledger rows); robots_software.py uses it.

SOURCE
  https://www.swe-marathon.org/index.html (SWE-Marathon by Abundant AI; the site footer says
  "Open-source under Apache 2.0", robots.txt allows everything; the tasks are Apache-2.0 at
  github.com/abundant-ai/swe-marathon). The page is a single-page app: the data lives in its
  JS bundle /assets/index-<hash>.js, whose hash changes with every deploy, so the bundle URL is
  read from the page's <script src>. With --fixture DIR the page is DIR/index.html and the
  bundle DIR/<the bundle's own basename> (common.fetch's URL-basename rule, applied to the URL
  the fixture page names).
  The bundle holds, as JS object literals:
    {version:`v1.1`,tasks:JSON.parse(`{"<task>": {task, note, configs: [{agent, model,
      reasoningEffort?, n, binary, partial, ..., trials: [{id, agent, model, reasoningEffort?,
      reward (0/1), partial, status, startedAt "YYYY-MM-DD HH:MM UTC", duration, ...}]}]}}`)}
    {dataset:`abundant/swe-marathon`,tasks:[{id:`<task>`,digest:`sha256:...`,metadata:{...,
      expert_time_estimate_hours:<number>},agent:{timeout_sec},...}, ...]}   (the task.toml
      files, translated; the 20 values equal tasks/<task>/task.toml at the repo's
      v1.1-official tag, checked 2026-10-16)
  The hours are taken from the second structure by parsing the array literal (a small parser
  for the JSON-like JS subset; `tasks:[` arrays that are not this one fail to parse or lack
  id/metadata and are skipped). Exactly one array must cover exactly the result tasks, and
  every task needs a positive hour estimate: anything else fails loudly.

TRIALS
  status "success" = the Harbor trial finished without an exception (agent timeouts included:
  138 such trials at the agent time limit are "success", scored normally). status "error" =
  Harbor recorded an exception_info (harness/provider failure): 188 of 9410 trials, all in
  five configurations of GLM 5.3 / GLM 5.3 Flash (Claude Code) and Gemini 3.7 Flash (OpenCode);
  their rewards (183 x 0, 5 x 1) are whatever the verifier made of the state the crash left,
  and for the CUA-graded clone tasks a grader failure errors the trial instead of scoring it.
  The site counts them in its "k / n" figures, but they are not capability evidence: fit()
  EXCLUDES them (counted in `errors`; include_errors=True keeps them for a sensitivity check).
  Any other status value fails loudly. A trial without reasoningEffort (some configurations
  record none; the site labels them "max") has effort None.

FIT (METR "Measuring AI Ability to Complete Long Tasks", 2025)
  P(success on task t) = 1 / (1 + exp(-beta * (log2 h50 - log2 t))), t = the task's expert
  hours, by maximum likelihood over the configuration's trials (unweighted; each trial one
  Bernoulli outcome; Newton-Raphson with step halving, deterministic). h80 = h50 * 2^(-ln 4 /
  beta). Uncertainty of log2 h80 and log2 h50 by the delta method, from (a) the observed
  (= expected) information and (b) a task-clustered sandwich (trials of one task are
  correlated: task difficulty is not only length), with the G/(G-1) small-sample factor; the
  95% CI uses the larger of the two standard errors (conservative). METR's own CIs come from a
  hierarchical bootstrap; this is the cheap deterministic analogue.
  Degenerate configurations get a `flag` and NO h50/h80/beta (never an extrapolated number):
    no-successes / all-successes   the horizon is below / above every task: no finite MLE
    separated     every success is on tasks no longer than every failure: beta -> infinity
    inverted      success rises with task length (fitted beta <= 0, or separated that way)
    too-few-tasks fewer than two distinct task lengths
    no-convergence
  A fit whose h80 lies outside the task lengths it was fitted on (4-400 h for the full suite)
  is kept but marked `extrapolated` = "below" / "above".
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.parse
from typing import NamedTuple

import common

INDEX_URL = "https://www.swe-marathon.org/index.html"
STATUSES = {"success": True, "error": False}   # status -> usable as capability evidence
Z95 = 1.959963984540054
LN4 = math.log(4)


class Trial(NamedTuple):
    task: str
    agent: str
    model: str
    effort: str | None
    reward: int
    status: str
    started: str   # "YYYY-MM-DD HH:MM UTC"
    id: str


# --- parsing -------------------------------------------------------------------------------------
def bundle_url(index_html: str, base: str = INDEX_URL) -> str:
    """Absolute URL of the page's main JS bundle (/assets/index-<hash>.js)."""
    srcs = re.findall(r'<script\b[^>]*\bsrc="([^"]*/assets/index-[\w-]+\.js)"', index_html)
    if len(srcs) != 1:
        raise ValueError(f"{base}: expected one /assets/index-<hash>.js script, found {srcs}")
    return urllib.parse.urljoin(base, srcs[0])


class Ref(NamedTuple):
    """A bare identifier in a JS literal (a variable reference we do not resolve)."""
    name: str


_ESC = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
_NUM = re.compile(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")


class _JS:
    """Reader for the JSON-like subset of JS literals a minifier emits for static data: objects
    (identifier/string/number keys), arrays, '/"/` strings (templates without ${}) and the
    minifier's string arrays `a.b`.split(`.`), numbers, !0/!1, true/false/null and bare
    identifiers (Ref). Anything else raises ValueError."""

    def __init__(self, s: str, i: int):
        self.s, self.i = s, i

    def fail(self, what: str):
        raise ValueError(f"JS literal at offset {self.i}: {what}: {self.s[self.i:self.i + 40]!r}")

    def peek(self) -> str:
        return self.s[self.i] if self.i < len(self.s) else ""

    def eat(self, c: str) -> None:
        if self.peek() != c:
            self.fail(f"expected {c!r}")
        self.i += 1

    def string(self) -> str:
        s, q = self.s, self.s[self.i]
        out, i = [], self.i + 1
        while True:
            j = i
            while j < len(s) and s[j] not in (q, "\\") and not (q == "`" and s.startswith("${", j)):
                j += 1
            out.append(s[i:j])
            if j >= len(s):
                self.i = j
                self.fail("unterminated string")
            if s[j] == q:
                self.i = j + 1
                return "".join(out)
            if s[j] == "$":
                self.i = j
                self.fail("template interpolation")
            c = s[j + 1]   # an escape
            if c in _ESC and not (c == "0" and s[j + 2:j + 3].isdigit()):
                out.append(_ESC[c])
                i = j + 2
            elif c == "x":
                out.append(chr(int(s[j + 2:j + 4], 16)))
                i = j + 4
            elif c == "u" and s[j + 2] == "{":
                k = s.index("}", j)
                out.append(chr(int(s[j + 3:k], 16)))
                i = k + 1
            elif c == "u":
                out.append(chr(int(s[j + 2:j + 6], 16)))
                i = j + 6
            elif c == "\r":
                i = j + (3 if s[j + 2:j + 3] == "\n" else 2)   # line continuation
            elif c in "\n\u2028\u2029":
                i = j + 2
            else:
                out.append(c)   # \\ \` \' \" \$ and identity escapes
                i = j + 2

    def value(self):
        c = self.peek()
        if c == "{":
            self.i += 1
            out = {}
            while self.peek() != "}":
                if out:
                    self.eat(",")
                k = self.peek()
                if k in "`\"'":
                    key = self.string()
                elif m := (_IDENT.match(self.s, self.i) or _NUM.match(self.s, self.i)):
                    key, self.i = m[0], m.end()
                else:
                    self.fail("bad key")
                self.eat(":")
                out[key] = self.value()
            self.i += 1
            return out
        if c == "[":
            self.i += 1
            arr = []
            while self.peek() != "]":
                if arr:
                    self.eat(",")
                arr.append(self.value())
            self.i += 1
            return arr
        if c and c in "`\"'":
            text = self.string()
            if self.s.startswith(".split(", self.i):   # minified string array: `a.b`.split(`.`)
                self.i += len(".split(")
                if self.peek() not in "`\"'":
                    self.fail("split by a non-literal")
                sep = self.string()
                self.eat(")")
                return text.split(sep)
            return text
        if self.s.startswith(("!0", "!1"), self.i):
            self.i += 2
            return self.s[self.i - 1] == "0"
        if m := _NUM.match(self.s, self.i):
            self.i = m.end()
            return float(m[0]) if any(ch in m[0] for ch in ".eE") else int(m[0])
        if m := _IDENT.match(self.s, self.i):
            self.i = m.end()
            if self.peek() in "(.[`":
                self.fail("expression")
            return {"true": True, "false": False, "null": None}.get(m[0], Ref(m[0]))
        self.fail("unsupported value")


def results_json(bundle: str) -> tuple[str, dict]:
    """(version, {task: {task, configs: [...]}}) of the bundle's `version:..,tasks:JSON.parse(..)`."""
    ms = list(re.finditer(r"version:(?=[`\"'])", bundle))
    hits = []
    for m in ms:
        r = _JS(bundle, m.end())
        version = r.string()
        if bundle.startswith(",tasks:JSON.parse(", r.i):
            r.i += len(",tasks:JSON.parse(")
            if r.peek() not in "`\"'":
                r.fail("JSON.parse of a non-literal")
            text = r.string()
            r.eat(")")
            hits.append((version, text))
    if len(hits) != 1:
        raise ValueError(f"bundle: expected one `version:..,tasks:JSON.parse(..)`, found {len(hits)}")
    version, text = hits[0]
    data = json.loads(text)
    if not isinstance(data, dict) or not data:
        raise ValueError("bundle: the results JSON is not a non-empty object")
    return version, data


def task_hours(bundle: str, names: set[str]) -> dict[str, float]:
    """{task: expert_time_estimate_hours} from the bundle's task.toml array (see module doc)."""
    found = []
    for m in re.finditer(r"tasks:\[", bundle):
        try:
            arr = _JS(bundle, m.end() - 1).value()
        except (ValueError, IndexError):
            continue
        if arr and all(isinstance(t, dict) and isinstance(t.get("id"), str) and isinstance(t.get("metadata"), dict)
                       for t in arr):
            found.append(arr)
    cover = [a for a in found if {t["id"] for t in a} == names]
    if len(cover) != 1:
        raise ValueError(f"bundle: {len(cover)} task-metadata arrays cover exactly the {len(names)} result "
                         f"tasks (candidates: {[sorted(t['id'] for t in a) for a in found]})")
    out = {}
    for t in cover[0]:
        h = t["metadata"].get("expert_time_estimate_hours")
        if isinstance(h, bool) or not isinstance(h, (int, float)) or not 0 < h < math.inf:
            raise ValueError(f"bundle: task {t['id']} has no positive expert_time_estimate_hours ({h!r})")
        if t["id"] in out:
            raise ValueError(f"bundle: task {t['id']} listed twice")
        out[t["id"]] = float(h)
    return out


def parse(index_html: str, bundle: str) -> dict:
    """{version, bundle (URL), tasks {name: hours}, trials [Trial]} of the page and its bundle."""
    url = bundle_url(index_html)
    version, data = results_json(bundle)
    hours = task_hours(bundle, set(data))
    trials, ids = [], set()
    for name in sorted(data):
        t = data[name]
        if t.get("task", name) != name:
            raise ValueError(f"task {name}: inner name {t.get('task')!r}")
        for c in t["configs"]:
            for x in c["trials"]:
                key = (x["agent"], x["model"], x.get("reasoningEffort"))
                if key != (c["agent"], c["model"], c.get("reasoningEffort")):
                    raise ValueError(f"trial {x['id']}: {key} differs from its configuration")
                if x["status"] not in STATUSES:
                    raise ValueError(f"trial {x['id']}: unknown status {x['status']!r}")
                if x["reward"] not in (0, 1) or isinstance(x["reward"], bool):
                    raise ValueError(f"trial {x['id']}: reward {x['reward']!r} is not 0/1")
                if not re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d UTC", x["startedAt"]):
                    raise ValueError(f"trial {x['id']}: startedAt {x['startedAt']!r}")
                if x["id"] in ids:
                    raise ValueError(f"trial {x['id']} listed twice")
                ids.add(x["id"])
                trials.append(Trial(name, x["agent"], x["model"], x.get("reasoningEffort") or None,
                                    int(x["reward"]), x["status"], x["startedAt"], x["id"]))
    return {"version": version, "bundle": url, "tasks": hours, "trials": trials}


def fetch(fixture: str | None = None) -> dict:
    """parse() of the live site (or of a fixture dir: index.html + the bundle it names)."""
    html = common.fetch(INDEX_URL, fixture)
    return parse(html, common.fetch(bundle_url(html), fixture))


# --- fitting -------------------------------------------------------------------------------------
def _sig(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def _logsig(z: float) -> float:
    """log(sigmoid(z)), stable."""
    return -math.log1p(math.exp(-z)) if z >= 0 else z - math.log1p(math.exp(z))


def fit(trials: list[Trial], hours: dict[str, float], include_errors: bool = False) -> dict:
    """METR-style logistic fit of one configuration's trials (see module doc). Returns
    {n, successes, errors, tasks, first, last, flag, beta, h50, h80, se_log2_h50, se_log2_h80,
    se_log2_h80_model, se_log2_h80_cluster, h80_lo, h80_hi, extrapolated}; flag None = a fit."""
    for t in trials:
        if t.task not in hours:
            raise ValueError(f"task {t.task} has no expert hour estimate")
    errors = sum(1 for t in trials if not STATUSES[t.status])
    use = [t for t in trials if include_errors or STATUSES[t.status]]
    agg: dict[str, list[int]] = {}
    for t in use:
        agg.setdefault(t.task, [0, 0])
        agg[t.task][0] += t.reward
        agg[t.task][1] += 1
    k_all = sum(k for k, _ in agg.values())
    n_all = len(use)
    out = {"n": n_all, "successes": k_all, "errors": errors, "tasks": len(agg),
           "first": min((t.started for t in use), default=None), "last": max((t.started for t in use), default=None),
           "flag": None, "beta": None, "h50": None, "h80": None, "se_log2_h50": None, "se_log2_h80": None,
           "se_log2_h80_model": None, "se_log2_h80_cluster": None, "h80_lo": None, "h80_hi": None,
           "extrapolated": None}
    pts = sorted((math.log2(hours[name]), k, n) for name, (k, n) in agg.items())
    xs = {x for x, _, _ in pts}
    if k_all == 0:
        return dict(out, flag="no-successes")
    if k_all == n_all:
        return dict(out, flag="all-successes")
    if len(xs) < 2:
        return dict(out, flag="too-few-tasks")
    win = [x for x, k, _ in pts if k > 0]
    lose = [x for x, k, n in pts if k < n]
    if max(win) <= min(lose):
        return dict(out, flag="separated")
    if max(lose) <= min(win):
        return dict(out, flag="inverted")

    xc = sum(x * n for x, _, n in pts) / n_all   # centre for conditioning; logit p = a + b (x - xc)
    d = [(x - xc, k, n) for x, k, n in pts]

    def loglik(a, b):
        return sum(k * _logsig(a + b * u) + (n - k) * _logsig(-(a + b * u)) for u, k, n in d)

    def info(a, b):
        i00 = i01 = i11 = g0 = g1 = 0.0
        for u, k, n in d:
            p = _sig(a + b * u)
            w = n * p * (1 - p)
            i00, i01, i11 = i00 + w, i01 + w * u, i11 + w * u * u
            g0, g1 = g0 + (k - n * p), g1 + (k - n * p) * u
        return (i00, i01, i11), (g0, g1)

    a, b = math.log(k_all / (n_all - k_all)), 0.0
    ll = loglik(a, b)
    for _ in range(200):
        (i00, i01, i11), (g0, g1) = info(a, b)
        det = i00 * i11 - i01 * i01
        if det <= 0:
            return dict(out, flag="no-convergence")
        s0, s1 = (i11 * g0 - i01 * g1) / det, (i00 * g1 - i01 * g0) / det
        step = 1.0
        while True:
            a2, b2 = a + step * s0, b + step * s1
            ll2 = loglik(a2, b2)
            if ll2 >= ll - 1e-12 or step < 1e-8:
                break
            step /= 2
        a, b, ll = a2, b2, ll2
        if max(abs(step * s0), abs(step * s1)) < 1e-12:
            break
    else:
        return dict(out, flag="no-convergence")
    if b >= 0:
        return dict(out, flag="inverted")

    (i00, i01, i11), _ = info(a, b)
    det = i00 * i11 - i01 * i01
    cov = ((i11 / det, -i01 / det), (-i01 / det, i00 / det))   # inverse information
    # task-clustered meat: each task is one length, i.e. one cluster score (k - n p) (1, u)
    m00 = m01 = m11 = 0.0
    for u, k, n in d:
        r = k - n * _sig(a + b * u)
        m00, m01, m11 = m00 + r * r, m01 + r * r * u, m11 + r * r * u * u
    g = len(d)

    def sandwich():
        c, m = cov, ((m00, m01), (m01, m11))
        cm = [[sum(c[i][k] * m[k][j] for k in range(2)) for j in range(2)] for i in range(2)]
        return [[g / (g - 1) * sum(cm[i][k] * c[k][j] for k in range(2)) for j in range(2)] for i in range(2)]
    rob = sandwich()

    def se(level_logit, v):
        # log2 h_q = xc + (L - a) / b; gradient wrt (a, b)
        ga, gb = -1 / b, -(level_logit - a) / (b * b)
        return math.sqrt(max(0.0, ga * ga * v[0][0] + 2 * ga * gb * v[0][1] + gb * gb * v[1][1]))

    l50, l80 = xc - a / b, xc + (LN4 - a) / b
    se80 = max(se(LN4, cov), se(LN4, rob))
    h80 = 2 ** l80
    lo, hi = min(x for x, _, _ in pts), max(x for x, _, _ in pts)
    return dict(out, beta=-b, h50=2 ** l50, h80=h80,
                se_log2_h50=max(se(0.0, cov), se(0.0, rob)), se_log2_h80=se80,
                se_log2_h80_model=se(LN4, cov), se_log2_h80_cluster=se(LN4, rob),
                h80_lo=2 ** (l80 - Z95 * se80), h80_hi=2 ** (l80 + Z95 * se80),
                extrapolated="below" if l80 < lo else "above" if l80 > hi else None)


def configs(trials: list[Trial], hours: dict[str, float], include_errors: bool = False) -> list[dict]:
    """fit() per (agent, model, effort), each with those keys added; sorted by (model, agent, effort)."""
    groups: dict[tuple, list[Trial]] = {}
    for t in trials:
        groups.setdefault((t.agent, t.model, t.effort), []).append(t)
    key = lambda k: (k[1], k[0], k[2] or "")   # noqa: E731
    return [dict(fit(groups[k], hours, include_errors), agent=k[0], model=k[1], effort=k[2])
            for k in sorted(groups, key=key)]


def best_by_model(fits: list[dict]) -> dict[str, dict]:
    """{model: its fitted (flag None) configuration with the highest h80}; ties go to the larger n,
    then agent and effort in sort order. Models with no fitted configuration are absent."""
    out: dict[str, dict] = {}
    for f in sorted((f for f in fits if f["flag"] is None),
                    key=lambda f: (f["model"], -f["h80"], -f["n"], f["agent"], f["effort"] or "")):
        out.setdefault(f["model"], f)
    return out


# --- CLI -----------------------------------------------------------------------------------------
def table(fits: list[dict]) -> str:
    def h(v):
        return "-" if v is None else f"{v:.3g}"
    lines = [f"{'model':<20} {'agent':<14} {'effort':<7} {'n':>4} {'succ':>4} {'err':>3} {'tasks':>5} "
             f"{'h50 h':>7} {'h80 h':>7} {'beta':>5} {'h80 95% CI':>15}  first..last / flag"]
    for f in fits:
        ci = "-" if f["h80"] is None else f"{h(f['h80_lo'])}-{h(f['h80_hi'])}"
        note = f["flag"] or (f"{f['first'][:10]}..{f['last'][:10]}"
                             + (f" extrapolated {f['extrapolated']}" if f["extrapolated"] else ""))
        lines.append(f"{f['model']:<20} {f['agent']:<14} {f['effort'] or '-':<7} {f['n']:>4} {f['successes']:>4} "
                     f"{f['errors']:>3} {f['tasks']:>5} {h(f['h50']):>7} {h(f['h80']):>7} "
                     f"{'-' if f['beta'] is None else format(f['beta'], '.2f'):>5} {ci:>15}  {note}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture", help="read index.html and its bundle from this directory (offline)")
    ap.add_argument("--best", action="store_true", help="only the best configuration per model")
    ap.add_argument("--include-errors", action="store_true", help="count error-status trials (sensitivity)")
    a = ap.parse_args()
    d = fetch(a.fixture)
    fits = configs(d["trials"], d["tasks"], a.include_errors)
    if a.best:
        fits = sorted(best_by_model(fits).values(), key=lambda f: -f["h80"])
    print(f"SWE-Marathon {d['version']} ({d['bundle']}): {len(d['tasks'])} tasks, {len(d['trials'])} trials, "
          f"{len({(t.agent, t.model, t.effort) for t in d['trials']})} configurations; expert hours "
          + ", ".join(f"{k} {v:g}" for k, v in sorted(d["tasks"].items(), key=lambda kv: kv[1])))
    print(table(fits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
