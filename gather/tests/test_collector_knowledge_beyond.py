#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Offline tests for gather/collectors/knowledge_beyond.py (World Bank/ITU internet use, the
Erdős problems database, TOP500, NASA Exoplanet Archive), on trimmed real fixtures in
gather/tests/fixtures/knowledge-beyond/. Reads the data repo's metric registry.

Run:  uv run gather/tests/test_collector_knowledge_beyond.py
"""
import datetime as dt
import os
import shutil
import sys
import tempfile
from decimal import Decimal

GATHER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(GATHER, "tests", "fixtures", "knowledge-beyond")
sys.path.insert(0, os.path.join(GATHER, "collectors"))

import common  # noqa: E402
import knowledge_beyond as kb  # noqa: E402
import ledger  # noqa: E402

FAILS = []
TODAY = dt.date(2026, 10, 16)
kb.MIN_PLANETS = 10  # the exoplanet fixture is trimmed to 40 planets (exoplanets_count.csv says 40 to match)
REG = common.registry(kb.SECTION)


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def raises(exc, fn, *a):
    try:
        fn(*a)
    except exc:
        return True
    return False


def read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def t5row(obs, value, verification="collector"):
    return dict(common.row(REG, kb.M_TOP500, obs, value, "https://top500.org/", "", "t", "2026-01-01"),
                verification=verification)


HAVE = [t5row("2025-11", "1809")]  # TOP500: fetch from Nov 2025 on
rows = kb.collect(FIX, TODAY, "t", HAVE)
by = {(r["metric"], r["obs"]): r for r in rows}
errs = common.check(rows, common.registry(kb.SECTION))
case("all rows pass the registry/ledger row checks", not errs and bool(rows))
for e in errs[:5]:
    print("     ", e)

# --- World Bank / ITU
case("internet: non-null World years, values verbatim (no float noise; '67' stays '67')",
     [(o, r["value"]) for (m, o), r in sorted(by.items()) if m == kb.M_INTERNET]
     == [("2005", "15.6"), ("2022", "67"), ("2024", "71.2"), ("2025", "73.6")])
case("internet: rule-basis date = year end + lag, capped at retrieval",
     by[(kb.M_INTERNET, "2024")]["published"] == "2025-10-27" and by[(kb.M_INTERNET, "2025")]["published"] == str(TODAY))
WB = read("wb_internet_users.json")
case("internet: a paged, short (total mismatch) or valueless answer is refused",
     raises(ValueError, kb.parse_wb, WB.replace('"pages": 1', '"pages": 2'))
     and raises(ValueError, kb.parse_wb, WB.replace('"total": 5', '"total": 66'))
     and raises(ValueError, kb.parse_wb, '[{"page": 1, "pages": 1, "total": 0}, []]'))
with tempfile.TemporaryDirectory() as tmp:
    for f in os.listdir(FIX):
        shutil.copy(os.path.join(FIX, f), tmp)
    with open(os.path.join(tmp, "wb_internet_users.json"), "w") as f:
        f.write(WB.replace('"date": "2004"', '"date": "2026"').replace('"value": null', '"value": 75.0', 1))
    cur = [r["obs"] for r in kb.collect(tmp, TODAY, "t", HAVE) if r["metric"] == kb.M_INTERNET]
case("internet: a current-year (partial) value is not emitted", "2026" not in cur and "2025" in cur)

# --- Erdős problems
snaps = kb.parse_erdos(read("statistics_history.csv"))
case("erdos: snapshot dates are converted to UTC (21:19 PDT on Aug 31 = Sept 1 UTC)",
     snaps[2]["at"] == dt.datetime(2025, 9, 1, 4, 19, 42, tzinfo=dt.timezone.utc))
case("erdos: complete months only, from 2025-09 (2026-10 is still running)",
     sorted(o for m, o in by if m == kb.M_ERDOS)[0] == "2025-09" and (kb.M_ERDOS, "2026-10") not in by)
case("erdos: a month's value = the last snapshot by its end (UTC): Sept 2025 = 379/1062, not Oct 1's row",
     by[(kb.M_ERDOS, "2025-09")]["value"] == "35.7" and "6da7146ee659" in by[(kb.M_ERDOS, "2025-09")]["note"])
case("erdos: a month without snapshots carries the previous one (Aug 2026 = Sept 2025's 379/1062)",
     by[(kb.M_ERDOS, "2026-08")]["value"] == "35.7")
case("erdos: 579 of 1221 solved = 47.4 % (Sept 2026)", by[(kb.M_ERDOS, "2026-09")]["value"] == "47.4")
case("erdos: out-of-order snapshot dates are refused",
     raises(ValueError, kb.parse_erdos, "\n".join(read("statistics_history.csv").splitlines()[::-1][-1:]
                                                  + read("statistics_history.csv").splitlines()[:0:-1])))

# --- TOP500
v, name = kb.parse_top500(read("top500-1993-06.html"), "u", (1993, 6))
case("top500: GFlop/s header converted exactly (59.70 GFlop/s = 0.0000597 PFlop/s), system named",
     format(v.normalize(), "f") == "0.0000597" and name == "CM-5/1024")
v18, _ = kb.parse_top500(read("top500-2018-11.html"), "u", (2018, 11))
case("top500: the Nov 2018 erratum (header GFlop/s over TFlop/s values) gives Summit's 143.5 PFlop/s", v18 == Decimal("143.5"))
case("top500: a page of another edition is refused",
     raises(ValueError, kb.parse_top500, read("top500-2018-11.html"), "u", (2019, 6)))
case("top500: lists to fetch = from the latest collected one to the newest due (legacy rows are no watermark; "
     "TOP500_REFRESH = all)",
     kb.top500_lists(dt.date(2026, 12, 1), HAVE) == [(2025, 11), (2026, 6), (2026, 11)]
     and kb.top500_lists(dt.date(1993, 12, 1), []) == [(1993, 6), (1993, 11)]
     and kb.top500_lists(dt.date(1993, 12, 1), [t5row("2025-11", "1809", "legacy")]) == [(1993, 6), (1993, 11)]
     and kb.top500_lists(dt.date(1993, 12, 1), HAVE, refresh=True) == [(1993, 6), (1993, 11)])
t5 = {r["obs"]: r for r in kb.collect(FIX, dt.date(2026, 12, 1), "t", HAVE) if r["metric"] == kb.M_TOP500}
case("top500: the newest list may be missing (Nov 2026 not out); PFlop/s values verbatim",
     sorted(t5) == ["2025-11", "2026-06"] and t5["2026-06"]["value"] == "2198.4" and t5["2025-11"]["value"] == "1809")
case("top500: a missing older list fails the run",
     raises(kb.NotFound, kb.collect, FIX, dt.date(2026, 12, 1), "t", [t5row("2024-11", "1742")]))
case("top500: the newest list missing after its own month (never released?) fails the run",
     raises(kb.NotFound, kb.collect, FIX, dt.date(2026, 12, 2), "t", HAVE))
case("top500: an edition already in the ledger that went missing fails the run",
     raises(kb.NotFound, kb.collect, FIX, dt.date(2026, 11, 20), "t", HAVE + [t5row("2026-11", "2500")]))
case("top500: a #1 Rmax below the previous list's (e.g. a unit error) fails the run",
     raises(ValueError, kb.collect, FIX, TODAY, "t", HAVE + [t5row("2025-06", "1809000")]))

# --- Q-Day qubit gap (derived from the ledger's input rows)
def inrow(metric, obs, value, verification="verified"):
    return dict(common.row(REG, metric, obs, value, f"https://example.org/{metric}/{obs}", "", "t", obs,
                           published=obs), verification=verification)


QIN = [inrow(kb.M_NEEDED, "2019-05-23", "20000000"), inrow(kb.M_DEVICE, "2024-04-16", "20"),
       inrow(kb.M_NEEDED, "2025-05-21", "1000000"), inrow(kb.M_DEVICE, "2025-11-05", "98"),
       inrow(kb.M_NEEDED, "2026-02-12", "100000"), inrow(kb.M_NEEDED, "2026-03-01", "13000", "withdrawn")]
gap = {r["obs"]: r for r in kb.collect(FIX, TODAY, "t", HAVE + QIN) if r["metric"] == kb.M_GAP}
case("qday gap: needed / available at each input date once both exist, 3 significant digits, withdrawn values out",
     [(o, r["value"]) for o, r in sorted(gap.items())]
     == [("2024-04-16", "1000000"), ("2025-05-21", "50000"), ("2025-11-05", "10200"), ("2026-02-12", "1020")])
case("qday gap: dated by the later input, sourced by the changed one",
     gap["2025-11-05"]["published"] == "2025-11-05" and gap["2025-11-05"]["published_basis"] == "source"
     and gap["2025-11-05"]["source"].endswith(f"{kb.M_DEVICE}/2025-11-05"))
case("qday gap: a weaker later estimate or a smaller later device does not raise the gap (record series)",
     [r["value"] for r in [g for g in kb.collect(FIX, TODAY, "t", HAVE + QIN[:5] + [
         inrow(kb.M_NEEDED, "2026-04-01", "500000"), inrow(kb.M_DEVICE, "2026-05-01", "50")])
         if g["metric"] == kb.M_GAP]][-2:] == ["1020", "1020"])


def day(d, base):
    """Run the gap derivation on day d against the ledger rows `base` and merge it (ledger.prepare):
    (merge errors, the new ledger rows, the staged rows)."""
    staged = common.mark_revisions(kb.gap_rows(REG, base, "t", dt.date.fromisoformat(d)), base)
    saved = ledger.observations, ledger.events, ledger.assessments
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "staged.csv")
        common.write(f, staged)
        try:
            ledger.observations, ledger.events, ledger.assessments = (lambda s: list(base)), (lambda s: []), (lambda s: [])
            errs, _, plan = ledger.prepare(kb.SECTION, obs_files=[f])
        finally:
            ledger.observations, ledger.events, ledger.assessments = saved
    for e in errs[:5]:
        print("     ", e)
    return errs, list(base) + (plan["obs"] if not errs else []), staged


L0 = [inrow(kb.M_NEEDED, "2026-02-01", "1000"), inrow(kb.M_DEVICE, "2026-02-01", "10"),
      inrow(kb.M_DEVICE, "2026-03-01", "20")]
errs, L1, st = day("2026-04-01", L0)
g = lambda base: {o: r["value"] for (m, o), r in ledger.obs_as_of("", rows=base).items() if m == kb.M_GAP}
case("qday gap lifecycle: both inputs on one date make one row (no crash); 100x then 50x",
     not errs and g(L1) == {"2026-02-01": "100", "2026-03-01": "50"})
wd = dict(inrow(kb.M_DEVICE, "2026-03-01", "20"), published="2026-05-01", retrieved="2026-05-01",
          published_basis="seen", verification="withdrawn", note="wrong")
errs, L2, st = day("2026-05-02", L1 + [wd])
case("qday gap lifecycle: an input withdrawn -> its gap row is withdrawn too (the stale 50x is not the headline)",
     not errs and g(L2) == {"2026-02-01": "100"}
     and any(r["verification"] == "withdrawn" and r["obs"] == "2026-03-01" for r in st))
rev = dict(inrow(kb.M_DEVICE, "2026-02-01", "8"), published="2026-06-01", retrieved="2026-06-01", published_basis="seen")
errs, L3, st = day("2026-06-02", L2 + [rev])
r125 = next(r for r in st if r["obs"] == "2026-02-01")
case("qday gap lifecycle: an input revision re-derives the gap as a revision dated first seen, which becomes effective",
     not errs and g(L3) == {"2026-02-01": "125"} and r125["published"] == "2026-06-02" and r125["published_basis"] == "seen")
errs, L4, st = day("2026-06-03", L3)
case("qday gap lifecycle: the next day's run is a clean no-op (merge-valid, nothing new)",
     not errs and len(L4) == len(L3))
newd = dict(inrow(kb.M_DEVICE, "2026-07-01", "40"), published="2026-07-01", published_basis="seen", retrieved="2026-07-01")
st = kb.gap_rows(REG, L3 + [newd], "t", dt.date(2026, 7, 3))
r7 = next(r for r in st if r["obs"] == "2026-07-01")
case("qday gap: a gap from a first-seen input is first-seen too", r7["published_basis"] == "seen" and r7["published"] == "2026-07-03")

case("qday gap: sig3", [kb.sig3(Decimal(x)) for x in ("1020.408", "0.041666", "9.995", "10", "123456")]
     == ["1020", "0.0417", "10", "10", "123000"])

# --- exoplanets
case("exoplanets: cumulative by discovery year, complete years past the lag only",
     by[(kb.M_EXO, "2009")]["value"] == "23" and by[(kb.M_EXO, "2014")]["value"] == "40"
     and (kb.M_EXO, "2026") not in by and kb.collect(FIX, dt.date(2026, 1, 29), "t", HAVE)[-1]["obs"] == "2024")
EXO = read("exoplanets_pscomppars.csv")
case("exoplanets: an answer short of the archive's count(*) is refused",
     raises(ValueError, kb.parse_exo, "\n".join(EXO.splitlines()[:-1]), read("exoplanets_count.csv"))
     and raises(ValueError, kb.parse_exo, "\n".join(EXO.splitlines()[:5]), "count(*)\n4\n"))

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall knowledge-beyond collector tests passed")
sys.exit(1 if FAILS else 0)
