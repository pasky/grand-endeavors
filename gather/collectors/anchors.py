#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""External forecast anchors (gather/RUBRIC.md §4.1 step 4): the community forecasts that
framework.yaml `anchors:` names for a section's milestones (core/anchoring.py), as observations
of that section. Run per section by collect.sh (via run.sh with COLLECTOR=anchors):

    anchors.py --section <section> --out FILE [--fixture DIR] [--today YYYY-MM-DD]

- Manifold (public API, no auth): https://api.manifold.markets/v0/market/<id> -> probability.
- Metaculus: https://www.metaculus.com/api/posts/<id>/ needs an API token (METACULUS_TOKEN; Metaculus
  grants aggregate access on request since its March 2026 API change); without one, Metaculus
  anchors are skipped with a warning. Binary -> P(yes); date -> community p10/p50/p90 as decimal
  years from the latest recency-weighted CDF (schema per Metaculus's open-source serializers; not
  yet exercised against a live response).
obs = the retrieval date; an anchor already observed in the last WEEK_DAYS days is skipped (a
weekly series, although collect.sh runs daily). The note holds forecasters=<n> (Manifold unique
bettors, Metaculus forecaster count), the question and its deadline: thin markets count for less.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys

import common
from common import ledger

sys.path.insert(0, os.path.join(common.ROOT, "core"))
import anchoring  # noqa: E402

WEEK_DAYS = 7
MANIFOLD = "https://api.manifold.markets/v0/market/{id}"
METACULUS = "https://www.metaculus.com/api/posts/{id}/"


def _year(v) -> float:
    """Decimal year of a Metaculus date bound: epoch seconds or an ISO datetime string."""
    d = dt.datetime.fromtimestamp(v, dt.timezone.utc) if isinstance(v, (int, float)) \
        else dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return anchoring.decimal_year(d.date())


def unscale(x: float, lo: float, hi: float, zero) -> float:
    """Metaculus nominal location x in [0, 1] -> value (log scaling when zero_point is set)."""
    if zero is None:
        return lo + (hi - lo) * x
    r = (hi - zero) / (lo - zero)
    return lo + (hi - lo) * (r ** x - 1) / (r - 1)


def cdf_quantile(cdf: list[float], q: float) -> float | None:
    """Nominal location where the CDF (evenly spaced on [0, 1]) reaches q; None outside the range."""
    if not cdf or cdf[0] > q or cdf[-1] < q:
        return None
    step = 1 / (len(cdf) - 1)
    for i in range(1, len(cdf)):
        if cdf[i] >= q:
            lo, hi = cdf[i - 1], cdf[i]
            return (i - 1 + ((q - lo) / (hi - lo) if hi > lo else 0)) * step
    return None


def manifold(a: dict, fixture: str | None) -> tuple[dict, str, str, int | None]:
    url = MANIFOLD.format(id=a["id"])
    j = json.loads(common.fetch(url, fixture))
    if j.get("outcomeType") != "BINARY":
        raise ValueError(f"manifold {a['id']}: not a binary market ({j.get('outcomeType')})")
    res = f"; resolved {j.get('resolution')}" if j.get("isResolved") else ""
    return {"p": j["probability"]}, url, f"{j.get('question', '')}{res}", j.get("uniqueBettorCount")


def metaculus(a: dict, fixture: str | None, token: str | None) -> tuple[dict, str, str, int | None]:
    url = METACULUS.format(id=a["id"])
    j = json.loads(common.fetch(url, fixture, {"Authorization": f"Token {token}"} if token else None))
    qn = j.get("question") or {}
    latest = ((qn.get("aggregations") or {}).get("recency_weighted") or {}).get("latest") or {}
    if not latest:
        raise ValueError(f"metaculus {a['id']}: no community aggregate in the response (no aggregate access?)")
    n = latest.get("forecaster_count")
    title = f"{j.get('title') or qn.get('title') or ''}; status {qn.get('status')}"
    if a.get("by"):
        if qn.get("type") != "binary":
            raise ValueError(f"metaculus {a['id']}: framework says binary (by:), the question is {qn.get('type')}")
        p = (latest.get("centers") or [None])[0]
        if p is None:
            p = latest["forecast_values"][1]
        return {"p": p}, url, title, n
    if qn.get("type") != "date":
        raise ValueError(f"metaculus {a['id']}: not a date question ({qn.get('type')}); binary anchors need by:")
    sc = qn["scaling"]
    lo, hi = _year(sc["range_min"]), _year(sc["range_max"])
    zero = _year(sc["zero_point"]) if sc.get("zero_point") is not None else None
    vals, out = {}, []
    for k, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9)):
        x = cdf_quantile(latest.get("forecast_values") or [], q)
        if x is None:
            out.append(k)
        else:
            vals[k] = unscale(x, lo, hi, zero)
    if out:  # a quantile beyond an open bound has no year (an empty or wrong row would mislead)
        title += f"; {'/'.join(out)} outside the question range {lo:.1f}-{hi:.1f}"
    return vals, url, title, n


def collect(fixture, today, collector, existing, section):
    reg = common.registry(section)
    known = {(r["metric"], r["obs"]) for r in existing}
    token = os.environ.get("METACULUS_TOKEN")
    rows = []
    for target, al in ledger.fw_anchors(section).items():
        for a in al:
            ms = anchoring.metrics(a)
            recent = {o for (m, o) in known if m in ms.values() and len(o) == 10
                      and today - dt.timedelta(days=WEEK_DAYS) < dt.date.fromisoformat(o) <= today}
            if recent:
                continue
            if a["source"] == "metaculus" and not (token or fixture):
                print(f"WARN: {target}: metaculus {a['id']} skipped (no METACULUS_TOKEN)", file=sys.stderr)
                continue
            vals, url, title, n = manifold(a, fixture) if a["source"] == "manifold" else metaculus(a, fixture, token)
            deadline = f"; event by {a['by']}" if a.get("by") else ""
            note = (f"forecasters={n if n is not None else 'unknown'}; anchor for {target} ({a['relation']}){deadline}; "
                    f"{title}").replace("\n", " ")
            for k, v in vals.items():
                if not (isinstance(v, (int, float)) and math.isfinite(v)):
                    raise ValueError(f"{a['source']} {a['id']}: non-numeric {k} {v!r}")
                value = common.round_half_up(v, 4 if k == "p" else 2)
                rows.append(common.row(reg, ms[k], str(today), value, url, note, collector, str(today)))
    return rows


if __name__ == "__main__":
    sys.exit(common.main(None, __file__, collect, allow_empty=True))
