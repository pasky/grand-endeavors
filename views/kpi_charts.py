"""Derivation charts of a KPI (framework.yaml kpi_about sections name them by `chart:`):
static SVG drawn from the ledger (and, for the robots-software conversions, the frozen
calibration file the collector writes), hover = native tooltips plus a CSS highlight; no script.

  task-horizon-timeline  the KPI and its two components over time, METR's own measurements
                         where they exist, and the raw indices (ECI, RLI) on right-hand axes
  eci-calibration        the ECI -> METR 80% horizon fit: the calibration models, the line and
                         how far today's frontier is extrapolated
  rli-conversion         how an RLI automation rate becomes a horizon: RLI's project lengths and
                         METR's success-vs-length curve of the latest frontier model
"""
from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
import re

import ledger

CALIBRATION_JSON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "gather", "collectors", "robots_software_calibration.json")
# every model AISI's cyber figure shows (the ledger series holds only the frontier steps); read off
# the figure in that audit, which documents and verifies it
AISI_MODELS = os.path.join(ledger.DATA, "ledger", "audits", "2026-10-18-aisi-cyber", "models.csv")
SEC = "robots-software"
# series colours (also in the legends); METR measured = ink
C_SW, C_RW, C_BL, C_METR, C_SWM, C_AISI = "#2563eb", "#d97706", "#7c3aed", "currentColor", "#0d9488", "#dc2626"


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def hours(h: float) -> str:
    """1.79 -> '1.8 h', 0.404 -> '24 min', 0.004 -> '15 s'."""
    if h >= 1:
        return f"{h:.2g} h" if h < 10 else f"{h:.0f} h"
    m = h * 60
    return f"{m:.2g} min" if m >= 1 else f"{m * 60:.0f} s"


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def _year(d: dt.date) -> float:
    return d.year + (d.timetuple().tm_yday - .5) / (366 if d.year % 4 == 0 else 365)


def _series(db, metric: str, unit_h: float = 1.0) -> list[tuple[dt.date, float, str]]:
    """The metric's effective daily rows: (date, value in hours (x unit_h), note)."""
    return [(_date(r[0]), r[1] * unit_h, r[2] or "") for r in db.execute(
        "SELECT obs, value, note FROM current_obs WHERE section=? AND metric=? AND obs_kind='9999-99-99' "
        "AND obs_end <= (SELECT value FROM build_info WHERE key='as_of') ORDER BY obs", (SEC, metric))]


def _model(note: str) -> str:
    """The model a collector note names ('... ECI 166.82 of Claude Opus 5.5 (released ...')."""
    m = (re.search(r"\bof (.+?) \(released", note) or re.search(r"frontier: (\S+) \(", note)
         or re.search(r"release date: (.+?) \((?:best|released)", note))
    return re.sub(r"-20\d{6}$", "", m[1].replace("_inspect", "").replace("_unknown", "")) if m else ""


class Plot:
    """A chart frame: x linear (years or a value), y log10 (or linear), in a viewBox."""

    def __init__(self, w, h, x0, x1, y0, y1, ml=46, mr=14, mt=26, mb=26, ylog=True):
        self.w, self.h, self.x0, self.x1, self.y0, self.y1 = w, h, x0, x1, y0, y1
        self.ml, self.mr, self.mt, self.mb, self.ylog = ml, mr, mt, mb, ylog
        self.out: list[str] = []

    def X(self, x):
        return self.ml + (self.w - self.ml - self.mr) * (x - self.x0) / (self.x1 - self.x0)

    def Y(self, y):
        f = (lambda v: math.log10(v)) if self.ylog else (lambda v: v)
        return self.h - self.mb - (self.h - self.mt - self.mb) * (f(y) - f(self.y0)) / (f(self.y1) - f(self.y0))

    def add(self, s: str):
        self.out.append(s)

    def yticks(self, ticks, x=None, anchor="end", cls="ax", grid=True):
        x = self.ml - 4 if x is None else x
        for v, lab in ticks:
            y = self.Y(v)
            if grid:
                self.add(f'<line class="gr" x1="{self.ml}" x2="{self.w - self.mr}" y1="{y:.1f}" y2="{y:.1f}"/>')
            self.add(f'<text class="{cls}" x="{x}" y="{y + 3:.1f}" text-anchor="{anchor}">{esc(lab)}</text>')

    def xticks(self, ticks):
        for v, lab in ticks:
            x = self.X(v)
            self.add(f'<line class="gr" x1="{x:.1f}" x2="{x:.1f}" y1="{self.mt}" y2="{self.h - self.mb}"/>'
                     f'<text class="ax" x="{x:.1f}" y="{self.h - self.mb + 12}" text-anchor="middle">{esc(lab)}</text>')

    def steps(self, pts, x_end, color, width=1.6, dash=""):
        """A frontier in force: flat until the next step (to x_end)."""
        if not pts:
            return
        d = f"M{self.X(pts[0][0]):.1f},{self.Y(pts[0][1]):.1f}"
        for nx, ny in pts[1:]:
            d += f"H{self.X(nx):.1f}V{self.Y(ny):.1f}"
        d += f"H{self.X(x_end):.1f}"
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"'
                 + (f' stroke-dasharray="{dash}"' if dash else "") + "/>")

    def dot(self, x, y, color, tip, r=3.2, shape="circle", hollow=False):
        X, Y = self.X(x), self.Y(y)
        fill = "var(--card)" if hollow else color
        if shape == "tri":
            g = (f'<path d="M{X:.1f},{Y - r - 1.5:.1f}L{X + r + 1:.1f},{Y + r:.1f}L{X - r - 1:.1f},{Y + r:.1f}Z" '
                 f'fill="{fill}" stroke="{color}" stroke-width="1.2"/>')
        elif shape == "diamond":
            g = (f'<path d="M{X:.1f},{Y - r - 1:.1f}L{X + r + 1:.1f},{Y:.1f}L{X:.1f},{Y + r + 1:.1f}'
                 f'L{X - r - 1:.1f},{Y:.1f}Z" fill="{fill}" stroke="{color}" stroke-width="1.4"/>')
        else:
            g = f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="{r}" fill="{fill}" stroke="{color}" stroke-width="1.4"/>'
        self.add(f'<g class="cp"><title>{esc(tip)}</title>{g}</g>')

    def svg(self, title: str, legend: list[tuple[str, str, str]] = (), ylabel: str = "", caption: str = "") -> str:
        """legend: (colour, kind 'line'|'dot'|'hollow'|'diamond'|'tri'|'bar', label), along the top
        (wrapping; the plot moves down to make room); ylabel: the left axis title."""
        x, row, items = 4, 0, []
        for color, kind, lab in legend:
            wd = 26 + 5.7 * len(lab)
            if x + wd > self.w and x > 4:
                x, row = 4, row + 1
            y = 10 + 15 * row
            mark = {"line": f'<line x1="{x}" x2="{x + 14}" y1="{y}" y2="{y}" stroke="{color}" stroke-width="2.4"/>',
                    "dot": f'<circle cx="{x + 7}" cy="{y}" r="3.2" fill="{color}"/>',
                    "hollow": f'<circle cx="{x + 7}" cy="{y}" r="3.2" fill="none" stroke="{color}" stroke-width="1.4"/>',
                    "diamond": f'<path d="M{x + 7},{y - 4}L{x + 11},{y}L{x + 7},{y + 4}L{x + 3},{y}Z" fill="{color}"/>',
                    "tri": f'<path d="M{x + 7},{y - 4}L{x + 11},{y + 3.5}L{x + 3},{y + 3.5}Z" fill="{color}"/>',
                    "bar": f'<rect x="{x + 2}" y="{y - 5}" width="10" height="10" fill="{color}" opacity=".35"/>'}[kind]
            items.append(f'{mark}<text class="lg" x="{x + 18}" y="{y + 3.5}">{esc(lab)}</text>')
            x += wd
        shift = 15 * row
        yl = (f'<text class="ax" transform="translate(11,{self.mt + (self.h - self.mt - self.mb) / 2:.0f}) rotate(-90)" '
              f'text-anchor="middle">{esc(ylabel)}</text>') if ylabel else ""
        cap = f"<figcaption>{esc(caption)}</figcaption>" if caption else ""
        return (f'<figure class="kc"><svg viewBox="0 0 {self.w} {self.h + shift}" role="img" aria-label="{esc(title)}">'
                f'<title>{esc(title)}</title>{"".join(items)}<g transform="translate(0,{shift})">{yl}'
                f'{"".join(self.out)}</g></svg>{cap}</figure>')


def _calibration(as_of: dt.date) -> dict | None:
    """The frozen conversions, from the day they were fitted (an earlier as-of view must not show
    a calibration, or METR measurements, that did not exist yet)."""
    try:
        with open(CALIBRATION_JSON, encoding="utf-8") as f:
            cal = json.load(f)
    except (OSError, ValueError):
        return None
    return cal if str(as_of) >= cal.get("fitted", "9999") else None


def _aisi_models(as_of: dt.date) -> list[dict]:
    import csv
    try:
        with open(AISI_MODELS, encoding="utf-8") as f:
            return [r for r in csv.DictReader(f) if r["published"] <= str(as_of)]
    except OSError:
        return []


def rli_h50(rate_pct: float, cal: dict) -> float | None:
    """The RLI conversion (robots_software.rli_hours, re-implemented from the calibration file's
    inputs; views/tests checks they agree): the 50% horizon at which METR's logistic, averaged over
    RLI's (reconstructed) project lengths, gives the automation rate."""
    p = rate_pct / 100
    if not 0 < p < 1:
        return None
    hist, beta = cal["rli"]["hist"], cal["rli"]["beta"]
    lo, hi, cs = hist["log10_lo"], hist["log10_hi"], hist["counts"]
    w = (hi - lo) / len(cs)
    tasks = [math.log2(10 ** (lo + w * (i + (k + .5) / c))) for i, c in enumerate(cs) for k in range(c)]
    tasks += [math.log2(h) for h in hist["extremes_h"]]
    a, b = -40.0, 60.0
    for _ in range(100):
        m = (a + b) / 2
        if sum(1 / (1 + math.exp(-beta * (m - t))) for t in tasks) / len(tasks) < p:
            a = m
        else:
            b = m
    return 2 ** ((a + b) / 2)


def _hour_ticks(lo, hi):
    cands = [(1 / 3600, "1 s"), (10 / 3600, "10 s"), (1 / 60, "1 min"), (1 / 6, "10 min"), (1, "1 h"),
             (10, "10 h"), (100, "100 h")]
    return [(v, lab) for v, lab in cands if lo <= v <= hi]


def task_horizon_timeline(db, as_of: dt.date) -> str:
    sw = _series(db, "horizon-80-software-eci")
    rw = _series(db, "horizon-80-remote-rli")
    bl = _series(db, "horizon-80-blended")
    metr = _series(db, "metr-80-horizon-by-release", 1 / 60)
    swm = _series(db, "swe-marathon-h80-by-release")
    aisi = _series(db, "aisi-cyber-h80-by-release")
    eci = {d: v for d, v, _ in _series(db, "eci-frontier-by-release")}
    rli = {d: v for d, v, _ in _series(db, "rli-automation-by-release")}
    if not (sw and rw and bl):
        return ""
    cal = _calibration(as_of)
    start = dt.date(2023, 1, 1)
    metr = [p for p in metr if p[0] >= start]
    end = max(as_of, max(p[0] for p in sw + rw + swm))
    p = Plot(680, 330, _year(start), _year(end) + .05, 1 / 240, 40, ml=52, mr=86, mt=22)
    p.xticks([(y, str(y)) for y in range(start.year, end.year + 1)])
    p.yticks(_hour_ticks(p.y0, p.y1))
    # the METR era: its measurements, then the gap after it stopped
    if metr:
        a, b = p.X(_year(metr[0][0])), p.X(_year(metr[-1][0]))
        yb = p.h - p.mb - 6
        p.add(f'<rect class="era" x="{a:.1f}" y="{p.mt}" width="{b - a:.1f}" height="{p.h - p.mt - p.mb}"/>'
              f'<text class="ann" x="{a + 4:.1f}" y="{p.mt + 11}">models METR measured (by release date)</text>'
              f'<text class="ann" x="{b + 4:.1f}" y="{yb - 22}">after METR\'s last</text>'
              f'<text class="ann" x="{b + 4:.1f}" y="{yb - 11}">model: conversions</text>'
              f'<text class="ann" x="{b + 4:.1f}" y="{yb}">only</text>')
    # right-hand axes: the raw indices, placed where the frozen conversions put them
    if cal:
        a_, b_ = cal["eci_cal"]["p80"]["a"], cal["eci_cal"]["p80"]["b"]
        xr = p.w - p.mr + 4
        p.add(f'<text class="ax" x="{p.w - p.mr + 2}" y="{p.mt - 4}" style="fill:{C_SW}">ECI</text>')
        for e in range(130, 175, 10):
            hh = 2 ** (a_ + b_ * e) / 60
            if p.y0 <= hh <= p.y1:
                y = p.Y(hh)
                p.add(f'<line x1="{p.w - p.mr}" x2="{xr}" y1="{y:.1f}" y2="{y:.1f}" stroke="{C_SW}"/>'
                      f'<text class="ax" x="{xr + 2}" y="{y + 3:.1f}" style="fill:{C_SW}">{e}</text>')
        xr = p.w - p.mr + 42
        p.add(f'<text class="ax" x="{xr - 2}" y="{p.mt - 4}" style="fill:{C_RW}">RLI</text>')
        k80 = 2 ** (-math.log(4) / cal["rli"]["beta"])
        for r in (1, 2, 5, 10, 20, 50):
            hh = rli_h50(r, cal) * k80
            if p.y0 <= hh <= p.y1:
                y = p.Y(hh)
                p.add(f'<line x1="{xr - 4}" x2="{xr}" y1="{y:.1f}" y2="{y:.1f}" stroke="{C_RW}"/>'
                      f'<text class="ax" x="{xr + 2}" y="{y + 3:.1f}" style="fill:{C_RW}">{r}%</text>')
    xe = _year(end)
    p.steps([(_year(d), v) for d, v, _ in sw], xe, C_SW)
    p.steps([(_year(d), v) for d, v, _ in rw], xe, C_RW)
    p.steps([(_year(d), v) for d, v, _ in bl], xe, C_BL, width=3)
    for d, v, n in sw:
        p.dot(_year(d), v, C_SW, f"{d}: {_model(n)}, ECI {eci.get(d, '?')} → software {hours(v)}", r=2.2)
    for d, v, n in rw:
        p.dot(_year(d), v, C_RW, f"{d}: {_model(n)}, RLI {rli.get(d, '?')}% → remote work {hours(v)}", r=2.2)
    for d, v, n in bl:
        p.dot(_year(d), v, C_BL, f"{d}: the KPI, √(software × remote work) = {hours(v)}", r=2.6)
    for d, v, n in metr:
        p.dot(_year(d), v, C_METR, f"{d}: {_model(n)}, METR measured {hours(v)}", r=3, hollow=True)
    for d, v, n in swm:
        p.dot(_year(d), v, C_SWM, f"{d}: {_model(n)}, SWE-Marathon measured {hours(v)}", shape="diamond")
    for d, v, n in aisi:
        p.dot(_year(d), v, C_AISI, f"{d}: {_model(n)}, UK AISI cyber (2.5M-token cap) {hours(v)}", shape="tri", r=2.6)
    return p.svg("AI task horizon at 80% success, the KPI and its parts over time (log scale)",
                 [(C_BL, "line", "the KPI (blend)"), (C_SW, "line", "software, from ECI"),
                  (C_RW, "line", "remote work, from RLI"), (C_METR, "hollow", "METR measured"),
                  (C_SWM, "diamond", "SWE-Marathon measured"), (C_AISI, "tri", "UK AISI cyber (capped)")],
                 ylabel="80% task horizon (log scale)")


def eci_calibration(db, as_of: dt.date) -> str:
    cal = _calibration(as_of)
    sw = _series(db, "horizon-80-software-eci")
    eci = {d: v for d, v, _ in _series(db, "eci-frontier-by-release")}
    if not cal or not cal.get("pairs"):
        return ""
    a, b = cal["eci_cal"]["p80"]["a"], cal["eci_cal"]["p80"]["b"]
    sd = cal["refit"]["p80"]["resid_sd"]
    pairs = cal["pairs"]
    lo_e, top_e = min(q["eci"] for q in pairs), max(q["eci"] for q in pairs)
    front = max(((eci[d], v, n) for d, v, n in sw if d in eci), default=None)
    hi_e = max(top_e, front[0] if front else top_e) + 2
    conv = lambda e: 2 ** (a + b * e) / 60  # hours
    p = Plot(680, 300, math.floor(lo_e / 5) * 5, math.ceil(hi_e / 5) * 5, 1 / 120, 30, ml=52, mr=18, mt=22)
    p.xticks([(e, str(e) if e < p.x1 else "") for e in range(int(p.x0), int(p.x1) + 1, 5)])
    p.add(f'<text class="ax" x="{p.w - p.mr}" y="{p.h - 2}" text-anchor="end">Epoch Capabilities Index</text>')
    p.yticks(_hour_ticks(p.y0, p.y1))
    # the band a single model typically falls in (±1 residual sd), the line, its extrapolation
    band = ([(e, conv(e) * 2 ** sd) for e in (lo_e, hi_e)] + [(e, conv(e) * 2 ** -sd) for e in (hi_e, lo_e)])
    p.add('<path class="band" d="M' + "L".join(f"{p.X(e):.1f},{p.Y(h):.1f}" for e, h in band) + 'Z"/>')
    p.add(f'<line x1="{p.X(lo_e):.1f}" y1="{p.Y(conv(lo_e)):.1f}" x2="{p.X(top_e):.1f}" y2="{p.Y(conv(top_e)):.1f}" '
          f'stroke="{C_SW}" stroke-width="2"/>'
          f'<line x1="{p.X(top_e):.1f}" y1="{p.Y(conv(top_e)):.1f}" x2="{p.X(hi_e):.1f}" y2="{p.Y(conv(hi_e)):.1f}" '
          f'stroke="{C_SW}" stroke-width="2" stroke-dasharray="5 3"/>')
    xt = p.X(top_e)
    p.add(f'<line class="gr2" x1="{xt:.1f}" x2="{xt:.1f}" y1="{p.mt}" y2="{p.h - p.mb}"/>'
          f'<text class="ann" x="{xt - 4:.1f}" y="{p.mt + 11}" text-anchor="end">← fitted on these models</text>'
          f'<text class="ann" x="{xt + 4:.1f}" y="{p.mt + 11}">extrapolated →</text>')
    for q in pairs:
        p.dot(q["eci"], q["metr_p80_min"] / 60, C_METR,
              f"{q['eci_model']} ({q['release']}): ECI {q['eci']:.2f}, METR measured {hours(q['metr_p80_min'] / 60)}; "
              f"the line says {hours(conv(q['eci']))}", hollow=True)
    for r in _aisi_models(as_of):
        if r["eci"]:
            v = float(r["aisi_cyber_h80_h"])
            p.dot(float(r["eci"]), v, C_AISI, f"{r['model']}: ECI {r['eci']}, UK AISI cyber horizon {hours(v)} "
                  "(2.5M-token cap: its level sits lower; its rise per ECI point is what it checks)", shape="tri", r=2.8)
    if front:
        e, v, n = front
        p.dot(e, v, C_SW, f"today's frontier, {_model(n)}: ECI {e:.2f} → {hours(v)} (on the line, by construction)",
              r=4.5)
        p.add(f'<text class="ann" x="{p.X(e) - 7:.1f}" y="{p.Y(v) + 4:.1f}" text-anchor="end">{esc(_model(n))}: '
              f'{esc(hours(v))}</text>')
    return p.svg("Converting ECI to a METR-equivalent 80% horizon: the calibration fit",
                 [(C_METR, "hollow", f"METR measured ({len(pairs)} models Epoch also scored)"),
                  (C_SW, "line", f"the fit: ×2 every {1 / b:.1f} ECI points"),
                  (C_SW, "bar", f"±{sd:.1f} doublings (typical miss)"), (C_SW, "dot", "today's frontier"),
                  (C_AISI, "tri", "UK AISI cyber, same models (a slope check)")],
                 ylabel="METR 80% horizon (log scale)")


def rli_conversion(db, as_of: dt.date) -> str:
    cal = _calibration(as_of)
    rw = _series(db, "horizon-80-remote-rli")
    rw50 = {d: v for d, v, _ in _series(db, "horizon-50-remote-rli")}
    rli = {d: v for d, v, _ in _series(db, "rli-automation-by-release")}
    if not cal or not rw:
        return ""
    beta, hist = cal["rli"]["beta"], cal["rli"]["hist"]
    lo, hi, cs = hist["log10_lo"], hist["log10_hi"], hist["counts"]
    bw = (hi - lo) / len(cs)
    dates = [d for d, _, _ in rw if d in rw50 and d in rli]
    if not dates:
        return ""
    last = dates[-1]
    early = next((d for d in dates if rli[d] >= 2), dates[0])
    h80 = {d: v for d, v, _ in rw}
    x0 = min(-1.3, math.floor(math.log10(min(h80[early], h80[last])) * 2) / 2 - .1)
    p = Plot(680, 280, x0, 2.75, 0, 1, ml=52, mr=50, mt=22, ylog=False)  # x = log10 hours, y = probability
    p.xticks([(math.log10(v), lab) for v, lab in ((1 / 60, "1 min"), (1 / 6, "10 min"), (1, "1 h"), (10, "10 h"),
                                                  (100, "100 h")) if math.log10(v) >= x0])
    p.yticks([(f, f"{f:.0%}") for f in (0, .2, .5, .8, 1)], grid=True)
    top = 40 if max(cs) <= 40 else max(cs)   # the bars' own scale, on the right
    for c in range(0, top + 1, 10):
        y = p.Y(c / top)
        p.add(f'<text class="ax" x="{p.w - p.mr + 4}" y="{y + 3:.1f}" style="fill:{C_RW}">{c}</text>')
    p.add(f'<text class="ax" transform="translate({p.w - 6},{p.mt + (p.h - p.mt - p.mb) / 2:.0f}) rotate(90)" '
          f'text-anchor="middle" style="fill:{C_RW}">RLI projects per bar</text>')
    for i, c in enumerate(cs):
        x0, x1 = p.X(lo + bw * i), p.X(lo + bw * (i + 1))
        y = p.Y(c / top)
        p.add(f'<g class="cp"><title>{c} RLI projects take {hours(10 ** (lo + bw * i))}–{hours(10 ** (lo + bw * (i + 1)))}'
              f'</title><rect x="{x0 + .5:.1f}" y="{y:.1f}" width="{x1 - x0 - 1:.1f}" height="{p.Y(0) - y:.1f}" '
              f'fill="{C_RW}" opacity=".22"/></g>')

    def curve(h50, color, width, label_at):
        pts = []
        for k in range(0, 201):
            lt = p.x0 + (p.x1 - p.x0) * k / 200
            pr = 1 / (1 + math.exp(-beta * (math.log2(h50) - lt * math.log2(10))))
            pts.append(f"{p.X(lt):.1f},{p.Y(pr):.1f}")
        p.add(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="{width}"/>')

    for d, color, width in ((early, "var(--mute)", 1.4), (last, C_RW, 2.4)):
        curve(rw50[d], color, width, d)
        x50, x80 = p.X(math.log10(rw50[d])), p.X(math.log10(h80[d]))
        p.add(f'<g class="cp"><title>{d}: RLI {rli[d]}% → 50% horizon {hours(rw50[d])}, 80% horizon {hours(h80[d])}'
              f'</title><circle cx="{x50:.1f}" cy="{p.Y(.5):.1f}" r="3.5" fill="{color}"/>'
              f'<circle cx="{x80:.1f}" cy="{p.Y(.8):.1f}" r="3.5" fill="{color}"/></g>')
        if d == last:
            p.add(f'<text class="ann" x="{x80 + 6:.1f}" y="{p.Y(.8) - 5:.1f}">80% horizon {esc(hours(h80[d]))}</text>'
                  f'<text class="ann" x="{x50 + 6:.1f}" y="{p.Y(.5) - 5:.1f}">50% horizon {esc(hours(rw50[d]))}</text>')
    name = lambda d: _model(next(n for dd, _, n in rw if dd == d))
    p.add(f'<text class="ax" x="{p.w - p.mr}" y="{p.h - 2}" text-anchor="end">task length (human hours, log scale)</text>')
    return p.svg("Converting the RLI automation rate to a horizon: METR's success-vs-length curve over RLI's projects",
                 [(C_RW, "line", f"{last.strftime('%b %Y')} ({name(last)}): {rli[last]}% of RLI projects done"),
                  ("#888", "line", f"{early.strftime('%b %Y')} ({name(early)}): {rli[early]}%"),
                  (C_RW, "bar", "RLI's projects by length (240; 201 with times, reconstructed)")],
                 ylabel="chance of success")


CHARTS = {"task-horizon-timeline": task_horizon_timeline, "eci-calibration": eci_calibration,
          "rli-conversion": rli_conversion}

CSS = """
figure.kc{margin:8px 0 10px;max-width:760px}figure.kc figcaption{font-size:12px;color:var(--mute)}figure.kc svg{width:100%;height:auto;display:block;color:var(--ink)}
.kc .gr{stroke:var(--line);stroke-width:1}.kc .gr2{stroke:var(--mute);stroke-width:1;stroke-dasharray:2 3}
.kc .ax{font-size:10px;fill:var(--mute)}.kc .lg{font-size:10.5px;fill:var(--ink)}.kc .ann{font-size:10px;fill:var(--mute)}
.kc .era{fill:var(--sel);opacity:.6}.kc .band{fill:#2563eb;opacity:.10}
.kc .cp{cursor:default}.kc text{pointer-events:none}.kc .cp:hover circle,.kc .cp:hover path{stroke-width:3}.kc .cp:hover rect{opacity:.45}
"""
