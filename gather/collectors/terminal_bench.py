"""Terminal-Bench 4.0 leaderboard (tbench.ai) -> per-configuration resolution rates.

A cross-check of the robots-software task-horizon conversion (robots_software.py), not a horizon:
the suite's per-task expert time estimates do not predict which tasks agents fail (in 30 of the
35 configurations of 2026-10-17 METR's logistic slope fits <= 0, success does not fall with task
length; METR's "How does time horizon vary across domains" (2025-07-14) drops a suite when most
models' slope is below 0.25), so only the resolution rate is used: an independent (not in ECI)
measure of progress on long agentic tasks (66 tasks, median expert estimate 4 h, 5 trials each).

SOURCE  https://www.tbench.ai/leaderboard/terminal-bench/4.0 (Stanford / Laude Institute / Harbor;
  the page also answers at /leaderboard). The Next.js page embeds the Harbor Hub leaderboard
  object in its `self.__next_f.push([1, "<JSON string>"])` chunks: {"name": "4-0-0", "title":
  "Terminal-Bench 4.0", ...} followed by "rows": [{metadata: {date (model release date,
  YYYY-MM-DD), model_display.label, agent_display.label, reasoning_effort, ...}, metrics:
  {accuracy (% of trials resolved), accuracy_ci95_half_width, n_trials, ...}}]. Per-trial results
  are on hub.harborframework.com (/datasets/terminal-bench/terminal-bench/4/leaderboards/4-0-0/
  rows/<row id>?page=N); not needed for the rates.
  Another leaderboard version (title/name) fails loudly: the ids measure 4.0.
"""
from __future__ import annotations

import json
import re

URL = "https://www.tbench.ai/leaderboard/terminal-bench/4.0"
TITLE, NAME = "Terminal-Bench 4.0", "4-0-0"
_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', re.S)


def payload(html: str) -> str:
    """The concatenated Next.js flight payload of the page (each chunk is a JSON string literal)."""
    chunks = [json.loads(c) for c in _CHUNK.findall(html)]
    if not chunks:
        raise SystemExit(f"{URL}: no Next.js payload chunks (page layout changed?)")
    return "".join(chunks)


def rows(html: str) -> list[dict]:
    """[{model, agent, effort, release, accuracy (%), ci95, n_trials}] of the 4.0 leaderboard."""
    t = payload(html)
    m = re.search(r'"name":"([^"]*)","title":"(Terminal-Bench [^"]*)"', t)
    if not m:
        raise SystemExit(f"{URL}: no leaderboard object in the page")
    if (m[1], m[2]) != (NAME, TITLE):
        raise SystemExit(f"{URL}: leaderboard {m[2]!r} ({m[1]}); the terminal-bench-4-* ids measure {TITLE}: "
                         f"register new ids for the new version (and retire these)")
    i = t.find('"rows":[', m.end())
    if i < 0:
        raise SystemExit(f"{URL}: leaderboard has no rows")
    try:
        raw, _ = json.JSONDecoder().raw_decode(t, i + len('"rows":'))
    except json.JSONDecodeError as e:
        raise SystemExit(f"{URL}: unparsable rows ({e})")
    out = []
    for r in raw:
        md, mt = r.get("metadata") or {}, r.get("metrics") or {}
        try:
            acc, n, rel = float(mt["accuracy"]), int(mt["n_trials"]), str(md["date"])
            model = md["model_display"]["label"]
        except (KeyError, TypeError, ValueError) as e:
            raise SystemExit(f"{URL}: malformed row {r.get('id')}: {e}")
        if not (0 <= acc <= 100 and n > 0 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", rel)):
            raise SystemExit(f"{URL}: implausible row {r.get('id')}: accuracy {acc}, n_trials {n}, date {rel}")
        out.append({"model": model, "agent": (md.get("agent_display") or {}).get("label", "?"),
                    "effort": md.get("reasoning_effort") or "default", "release": rel, "accuracy": mt["accuracy"],
                    "ci95": mt.get("accuracy_ci95_half_width"), "n_trials": n})
    if not out:
        raise SystemExit(f"{URL}: empty leaderboard")
    return out
