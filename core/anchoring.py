"""External forecast anchors (gather/RUBRIC.md §4.1 step 4, rubric v6+).

A milestone in framework.yaml may list `anchors:`, community forecasts of the same event or of a
bounding one, collected as observations of the milestone's section by gather/collectors/anchors.py:

    anchors:
      - {source: manifold, id: <market id>, relation: same|weaker|stronger, by: YYYY-MM-DD}
      - {source: metaculus, id: <question (post) id>, relation: ..., by: YYYY-MM-DD}   (binary)
      - {source: metaculus, id: <question (post) id>, relation: ...}                   (date question)

relation: same = the question resolves on our event; weaker = an easier event that comes no later
than ours (its date is a LOWER bound on our ETA: our P(by its deadline) <= its probability);
stronger = a harder event that implies ours (an UPPER bound: our P(by its deadline) >= its
probability). `by` = the last day the event may happen for the binary question to resolve YES.
Metric ids (registered in metrics/<section>.csv): manifold-<id lowercased>-p and metaculus-<id>-p
(binary, probability 0-1), metaculus-<id>-p10/-p50/-p90 (date questions, decimal years).

gap() is the mechanical divergence test of `ledger.py check`: a gap that the record's
basis.eta.calc does not address (by citing the anchor's metric id) is a warning.
"""
from __future__ import annotations

import datetime as dt
import re

SOURCES = ("manifold", "metaculus")
RELATIONS = ("same", "weaker", "stronger")
ID_RE = {"manifold": re.compile(r"^[A-Za-z0-9]+$"), "metaculus": re.compile(r"^[0-9]+$")}
# gap thresholds (gather/RUBRIC.md §4.1 step 4)
MEDIAN_YEARS = 5      # same-event date anchor: medians more than this apart
BOUND_YEARS = 1       # weaker/stronger date anchor: bound violated by more than this
SAME_PROB = 0.25      # same-event binary anchor: |our P(by deadline) - its P| above this
BOUND_PROB = 0.15     # weaker/stronger binary anchor: bound violated by more than this
FORECASTERS_RE = re.compile(r"\bforecasters=(\d+)")


def metrics(a: dict) -> dict[str, str]:
    """{quantity: metric id} of an anchor: {'p': ...} for a binary question, else p10/p50/p90."""
    src, qid = a["source"], str(a["id"])
    if src == "manifold":
        return {"p": f"manifold-{qid.lower()}-p"}
    if a.get("by"):
        return {"p": f"metaculus-{qid}-p"}
    return {q: f"metaculus-{qid}-{q}" for q in ("p10", "p50", "p90")}


def check(at: str, anchors) -> list[str]:
    """framework.yaml schema errors of one milestone's `anchors:` list."""
    if not isinstance(anchors, list):
        return [f"{at}: anchors must be a list"]
    errs, seen = [], set()
    for i, a in enumerate(anchors):
        here = f"{at}: anchors[{i}]"
        if not isinstance(a, dict) or a.get("source") not in SOURCES:
            errs.append(f"{here}: source must be one of {', '.join(SOURCES)}")
            continue
        if not ID_RE[a["source"]].match(str(a.get("id") or "")):
            errs.append(f"{here}: bad {a['source']} id {a.get('id')!r}")
        if a.get("relation") not in RELATIONS:
            errs.append(f"{here}: relation must be one of {', '.join(RELATIONS)}")
        if set(a) - {"source", "id", "relation", "by", "note"}:
            errs.append(f"{here}: unknown key(s) {sorted(set(a) - {'source', 'id', 'relation', 'by', 'note'})}")
        if "by" in a or a["source"] == "manifold":
            try:
                dt.date.fromisoformat(str(a.get("by")))
            except ValueError:
                errs.append(f"{here}: by must be YYYY-MM-DD (the event deadline of a binary question; "
                            "Manifold anchors are binary)")
        key = (a["source"], str(a.get("id")).lower())
        if key in seen:
            errs.append(f"{here}: duplicate anchor {key[0]} {key[1]}")
        seen.add(key)
    return errs


def decimal_year(d: dt.date) -> float:
    start = dt.date(d.year, 1, 1)
    return d.year + ((d - start).days + 0.5) / (dt.date(d.year + 1, 1, 1) - start).days


def our_cdf(eta: dict, made_at: str):
    """P(achieved by decimal year t) of a forecast {p_achieved, p10, p50, p90}: piecewise linear
    through 0 at made_at, each non-null quantile at the middle of its calendar year, and
    p_achieved at the end of 2100 (a rough interpolation, enough for a divergence threshold)."""
    pts = [(y + 0.5, lvl) for y, lvl in ((eta.get("p10"), 0.1), (eta.get("p50"), 0.5), (eta.get("p90"), 0.9))
           if y is not None]
    start = decimal_year(dt.date.fromisoformat(made_at))
    pts = [(start, 0.0)] * (not pts or start < pts[0][0]) + pts + [(2101.0, float(eta["p_achieved"]))]

    def f(t: float) -> float:
        if t <= pts[0][0]:
            return pts[0][1] if pts[0][1] > 0 else 0.0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if t <= x1:
                return y0 + (y1 - y0) * (t - x0) / (x1 - x0) if x1 > x0 else y1
        return pts[-1][1]
    return f


def gap(a: dict, values: dict[str, float], eta: dict, made_at: str) -> str | None:
    """Why the anchor diverges from our forecast beyond the thresholds, or None. values: the
    anchor's latest {quantity: value} (see metrics())."""
    rel = a["relation"]
    if "p" in values:  # binary: P(event by `by`)
        q = values["p"]
        ours = our_cdf(eta, made_at)(decimal_year(dt.date.fromisoformat(str(a["by"]))) + 0.5 / 365)
        what = f"P(by {a['by']}) {q:.2f} vs ours ~{ours:.2f}"
        if rel == "same" and abs(ours - q) > SAME_PROB:
            return f"{what} (same event: differs by more than {SAME_PROB})"
        if rel == "weaker" and ours - q > BOUND_PROB:
            return f"{what} (weaker event, a lower bound on our ETA: ours exceeds it by more than {BOUND_PROB})"
        if rel == "stronger" and q - ours > BOUND_PROB:
            return f"{what} (stronger event, an upper bound on our ETA: it exceeds ours by more than {BOUND_PROB})"
        return None
    if "p50" not in values:
        return None
    m = values["p50"]
    y = lambda k: eta.get(k) if eta.get(k) is not None else 2101  # a null quantile lies past 2100
    ours = y("p50") + 0.5
    what = f"median {m:.1f} vs ours {'>2100' if eta.get('p50') is None else eta['p50']}"
    if rel == "same":
        if abs(ours - m) > MEDIAN_YEARS:
            return f"{what} (same event: more than {MEDIAN_YEARS} years apart)"
        if not y("p10") <= m < (y("p90") + 1 if eta.get("p90") is not None else 2101):
            return f"{what} (same event: outside our p10-p90 {eta.get('p10')}-{eta.get('p90')})"
    elif rel == "weaker" and m - ours > BOUND_YEARS:
        return f"{what} (weaker event, a lower bound on our ETA: its median is later than ours)"
    elif rel == "stronger" and ours - m > BOUND_YEARS:
        return f"{what} (stronger event, an upper bound on our ETA: our median is later than its)"
    return None


def forecasters(note: str) -> int | None:
    m = FORECASTERS_RE.search(note or "")
    return int(m.group(1)) if m else None
