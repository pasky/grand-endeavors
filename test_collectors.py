#!/usr/bin/env python3
"""Offline regression tests for the deterministic KPI collectors (collectors/*.py).

Run:  uv run test_collectors.py     (no network; sources come from tests/fixtures/,
                                     small verbatim snippets of the real files)
"""
import datetime as dt
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(ROOT, "tests", "fixtures")
sys.path.insert(0, os.path.join(ROOT, "collectors"))

import climate  # noqa: E402
import common  # noqa: E402
import ledger  # noqa: E402
import robots_software  # noqa: E402
import rockets  # noqa: E402

FAILS = []
TODAY = dt.date(2026, 9, 28)


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def raises_exit(fn, *a):
    try:
        fn(*a)
    except SystemExit:
        return True
    return False


def fixture(name):
    return common.fetch("https://example.invalid/" + name, FIX)


def by_key(rows):
    return {(r["metric"], r["obs"]): r for r in rows}


def registry_ok(section, rows):
    """Every row passes ledger.check_obs_row against the section registry."""
    errs = common.check(rows, common.registry(section))
    for e in errs[:5]:
        print("     ", e)
    return not errs and bool(rows)


# --- climate -------------------------------------------------------------------
mm = climate.parse_monthly(fixture("co2_mm_mlo.txt"))
case("climate: monthly MLO parses every data row, values verbatim",
     len(mm) == 8 and mm[0][:2] == ("1958-03", "315.71") and ("2026-05", "432.34") in [m[:2] for m in mm])
gl = climate.parse_monthly(fixture("co2_mm_gl.txt"))
case("climate: negative missing-value sentinel is skipped", [m[0] for m in gl] == ["1979-01", "2026-05", "2026-06"])
case("climate: file creation date parsed from header", climate.file_created(fixture("co2_mm_mlo.txt")) == "2026-09-05")
case("climate: growth file keeps source formatting ('1.90')",
     ("2017", "1.90") in climate.parse_annual(fixture("co2_gr_mlo.txt")))

gr_mlo = climate.parse_annual(fixture("co2_gr_mlo.txt"))
gr_gl = climate.parse_annual(fixture("co2_gr_gl.txt"))
t10 = {y: v for y, v, _ in climate.trend(gr_mlo, 10)}
case("climate: 10-yr MLO trend 2025 = mean 2016-2025 = 2.56", t10.get("2025") == "2.56")
case("climate: 10-yr MLO trend 2020 = 2.43 (24.25/10 rounded half-up, not float 2.42)", t10.get("2020") == "2.43")
case("climate: 10-yr trend starts at the first full window (2010-2019)", min(t10) == "2019")
case("climate: 5-yr MLO trend 2025 = 2.61, 2020 = 2.51",
     {y: v for y, v, _ in climate.trend(gr_mlo, 5)}.get("2025") == "2.61"
     and {y: v for y, v, _ in climate.trend(gr_mlo, 5)}.get("2020") == "2.51")
g10 = {y: v for y, v, _ in climate.trend(gr_gl, 10)}
g5 = {y: v for y, v, _ in climate.trend(gr_gl, 5)}
case("climate: global trends match the verified ledger (10yr 2020/2024/2025 = 2.38/2.62/2.53; 5yr 2020/2025 = 2.44/2.63)",
     (g10["2020"], g10["2024"], g10["2025"], g5["2020"], g5["2025"]) == ("2.38", "2.62", "2.53", "2.44", "2.63"))
case("climate: negative growth rates are kept, only <= -99 sentinels are dropped",
     climate.parse_annual("  2025  -0.20  0.10\n  2024  -99.99  -9.99\n") == [("2025", "-0.20")])
case("climate: no trend window across a gap in the years",
     climate.trend([("2000", "1"), ("2001", "1"), ("2003", "1"), ("2004", "1")], 3) == [])

daily = dict(climate.parse_daily(fixture("co2_daily_mlo.txt")))
case("climate: daily keeps only the last 60 days before the file's latest date",
     "2026-09-24" in daily and "2026-07-27" in daily and "2026-07-26" not in daily and "2026-05-01" not in daily)

crow = climate.collect(FIX, TODAY, "collectors/climate.py@2026-09-28")
ck = by_key(crow)
case("climate: all rows pass ledger.check_obs_row against metrics/climate.csv", registry_ok("climate", crow))
case("climate: emits every source metric and the four derived trends",
     {r["metric"] for r in crow} == {"co2-mlo-monthly", "co2-global-monthly", "co2-mlo-annual", "co2-global-annual",
                                     "co2-growth-mlo-jan-dec", "co2-growth-global-jan-dec", "co2-mlo-daily",
                                     "co2-trend-10yr-mlo-jan-dec", "co2-trend-5yr-mlo-jan-dec",
                                     "co2-trend-10yr-global-jan-dec", "co2-trend-5yr-global-jan-dec"})
r = ck[("co2-mlo-monthly", "2026-05")]
case("climate: rule-basis publication (obs end + 7 d), provenance fields",
     (r["published"], r["published_basis"], r["retrieved"], r["verification"], r["collector"])
     == ("2026-06-07", "rule", "2026-09-28", "collector", "collectors/climate.py@2026-09-28"))
case("climate: rule publication is capped at retrieved (daily 2026-09-24 + 2 d vs retrieved 09-25)",
     by_key(climate.collect(FIX, dt.date(2026, 9, 25), "x"))[("co2-mlo-daily", "2026-09-24")]["published"] == "2026-09-25")
case("climate: notes flag Scripps era, interpolated month, Maunakea site, preliminary",
     "Scripps" in ck[("co2-mlo-monthly", "1958-03")]["note"]
     and "interpolated" in ck[("co2-mlo-monthly", "1975-12")]["note"]
     and "Maunakea" in ck[("co2-mlo-monthly", "2023-01")]["note"]
     and "preliminary" in ck[("co2-mlo-monthly", "2025-09")]["note"]
     and "preliminary" not in ck[("co2-mlo-monthly", "2025-08")]["note"]
     and "preliminary" in ck[("co2-mlo-annual", "2025")]["note"]
     and "preliminary" not in ck[("co2-mlo-annual", "2024")]["note"])
tr = ck[("co2-trend-10yr-mlo-jan-dec", "2025")]
case("climate: trend row is marked derived, cites the growth file and window",
     tr["value"] == "2.56" and tr["source"].endswith("/co2_gr_mlo.txt") and "Derived" in tr["note"]
     and "2016-2025" in tr["note"] and "co2_gr_mlo.txt" in tr["note"] and tr["unit"] == "ppm/yr")

# --- robots-software (METR) --------------------------------------------------------
case("metr: yaml_paths reads nested scalars, ignores comments and list items",
     robots_software.yaml_paths("a: # c\n  b:\n    c: 1\n  d: x\n  l:\n  - y: 2\ne: 3\n")
     == {("a", "b", "c"): "1", ("a", "d"): "x", ("e",): "3"})
bench, ms = robots_software.models(fixture("benchmark_results_1_1.yaml"))
case("metr: fixture models parsed (benchmark name, 6 models, release dates, estimates)",
     bench == "METR-Horizon-v1.1" and len(ms) == 6
     and {m["id"]: m["release"] for m in ms}["gpt_4_turbo_inspect"] == "2024-04-09"
     and abs({m["id"]: m for m in ms}["claude_opus_4_6_inspect"]["p50"]["estimate"] - 718.8) < 0.1)
case("metr: p50 frontier = models that beat every earlier release (same-date tie keeps the higher)",
     [m["id"] for m in robots_software.frontier(ms, "p50")] == ["gpt_4", "gpt_4_1106_inspect", "claude_opus_4_6_inspect"])
case("metr: p80 frontier is computed independently of p50",
     [m["id"] for m in robots_software.frontier(ms, "p80")]
     == ["gpt_4", "gpt_4_turbo_inspect", "claude_opus_4_6_inspect", "gemini_3_1_pro"])
mrow = robots_software.collect(FIX, TODAY, "collectors/robots_software.py@2026-09-28")
mk = by_key(mrow)
case("metr: all rows pass ledger.check_obs_row against metrics/robots-software.csv", registry_ok("robots-software", mrow))
case("metr: emits the release-cohort ids only (never the as-publicly-evaluated *-frontier ids)",
     {r["metric"] for r in mrow} == {"metr-50-horizon-by-release", "metr-80-horizon-by-release"})
reg_rs = common.registry("robots-software")
case("metr: registry: by-release ids (min, irregular, no lag); p80 required from 26H1, old p80 frontier retired after 2025",
     all((reg_rs[m]["unit"], reg_rs[m]["cadence"], reg_rs[m]["release_lag_days"]) == ("min", "irregular", "")
         and "RELEASED" in reg_rs[m]["definition"] for m in robots_software.METRICS.values())
     and reg_rs["metr-80-horizon-by-release"]["required_from"] == "pilot-26H1"
     and reg_rs["metr-80-horizon-frontier"]["retired_after"] == "pilot-2025")
case("metr: legacy rows of the old *-frontier ids are NOT re-stated under the new ids",
     not any(r["obs"] == "2025-11" for r in robots_software.collect(
         FIX, TODAY, "x", [{"metric": "metr-80-horizon-frontier", "obs": "2025-11"},
                           {"metric": "metr-50-horizon-frontier", "obs": "2025-11"}])))
r = mk[("metr-80-horizon-by-release", "2026-02-19")]
case("metr: row = release date, 2-dp estimate, basis seen, note names the model",
     r["value"] == "89.80" and r["published"] == r["retrieved"] == "2026-09-28" and r["published_basis"] == "seen"
     and "gemini_3_1_pro" in r["note"] and "release_date" in r["note"] and r["unit"] == "min")
case("metr: frontier series is strictly increasing per metric",
     all(float(a["value"]) < float(b["value"]) for m in robots_software.METRICS.values()
         for a, b in zip([x for x in mrow if x["metric"] == m], [x for x in mrow if x["metric"] == m][1:])))
case("metr: an HTML 404 page is rejected, not silently parsed as empty",
     raises_exit(robots_software.models, "<!DOCTYPE html>\n<title>404 - METR</title>\n"))

# two vintages: METR re-estimates gemini_3_1_pro (a p80 frontier point) far down
with tempfile.TemporaryDirectory() as tmp:
    v2 = fixture("benchmark_results_1_1.yaml").replace("estimate: 89.801503", "estimate: 1.0")
    with open(os.path.join(tmp, "benchmark_results_1_1.yaml"), "w") as f:
        f.write(v2)
    v1_rows = robots_software.collect(FIX, dt.date(2026, 9, 1), "v1")
    v2_rows = robots_software.collect(tmp, TODAY, "v2", v1_rows)
restated = by_key(v2_rows).get(("metr-80-horizon-by-release", "2026-02-19"))
case("metr: a revised-away frontier date is re-stated at the current frontier (69.87, not 89.80)",
     restated is not None and restated["value"] == "69.87" and "claude_opus_4_6_inspect" in restated["note"])
latest = {}
for r in v1_rows + v2_rows:  # ledger as-of rule: per (metric, obs) the latest-known row wins
    latest[(r["metric"], r["obs"])] = r
head = max((r for (m, _), r in latest.items() if m == "metr-80-horizon-by-release"), key=lambda r: r["obs"])
case("metr: after both vintages the latest p80 frontier in the ledger view is 69.87", head["value"] == "69.87")
case("metr: YYYY-MM ledger dates of the metric are re-stated as of the month end",
     by_key(robots_software.collect(FIX, TODAY, "x", [{"metric": "metr-80-horizon-by-release", "obs": "2024-04"}]))
     [("metr-80-horizon-by-release", "2024-04")]["value"] == "0.93")

# --- rockets (JSR) ---------------------------------------------------------------------
parsed = rockets.parse(fixture("msatannual.txt"))
case("jsr: year rows parsed (Total column, verbatim), all-time Total row skipped",
     parsed == [(1956, "0.0"), (2016, "337.4"), (2024, "2625.9"), (2025, "3194.0"), (2026, "2120.6")])
rrow = rockets.collect(FIX, TODAY, "collectors/rockets.py@2026-09-28")
case("jsr: the partial current year (2026) is NOT emitted", [r["obs"] for r in rrow] == ["1956", "2016", "2024", "2025"])
case("jsr: a year is emitted only once its release lag has passed (2025 absent on 2026-01-10)",
     "2025" not in [r["obs"] for r in rockets.collect(FIX, dt.date(2026, 1, 10), "x")]
     and "2025" in [r["obs"] for r in rockets.collect(FIX, dt.date(2026, 1, 15), "x")])
case("jsr: all rows pass ledger.check_obs_row against metrics/rockets.csv", registry_ok("rockets", rrow))
r = by_key(rrow)[("payload-mass-to-orbit", "2025")]
case("jsr: 2025 = 3194.0 t, rule-published 2026-01-15",
     (r["value"], r["unit"], r["published"], r["published_basis"]) == ("3194.0", "t", "2026-01-15", "rule"))
case("jsr: unexpected column layout fails loudly",
     raises_exit(rockets.parse, "# Bin YDate USA Total\n 1 2020 1.0\n"))

# --- revisions (common.mark_revisions) -------------------------------------------------------
def lrow(obs, value, published, verification="collector", basis="rule", retrieved=None, metric="payload-mass-to-orbit"):
    """A ledger row (only the fields mark_revisions / obs_as_of look at matter)."""
    return {"metric": metric, "obs": obs, "value": value, "unit": "t", "published": published,
            "published_basis": basis, "retrieved": retrieved or published, "verification": verification}


ledger_rows = [lrow("2025", "3141", "2026-01-15"), lrow("2024", "2625.90", "2025-01-15", "verified")]
marked = by_key(common.mark_revisions(rrow, ledger_rows))
r = marked[("payload-mass-to-orbit", "2025")]
case("revisions: a changed value is re-dated to first seen (basis seen, published = retrieved)",
     (r["published"], r["published_basis"]) == ("2026-09-28", "seen") and "3141" in r["note"])
case("revisions: numerically unchanged and brand-new obs keep the rule date",
     marked[("payload-mass-to-orbit", "2024")]["published_basis"] == "rule"
     and marked[("payload-mass-to-orbit", "2016")]["published"] == "2017-01-15")
case("revisions: re-dated rows still pass ledger.check_obs_row", registry_ok("rockets", list(marked.values())))

# effective-row semantics: compare with ledger.obs_as_of's winner, not with every historical value
revert = [lrow("2025", "3194.0", "2026-01-15"),                                     # original release
          lrow("2025", "3200.0", "2026-05-01", basis="seen")]                       # later source revision
r = by_key(common.mark_revisions(rrow, revert))[("payload-mass-to-orbit", "2025")]
case("revisions: a revert to an EARLIER value (3194.0 after 3200.0) is a revision, re-dated to first seen",
     (r["published"], r["published_basis"]) == ("2026-09-28", "seen") and "3200.0" in r["note"])
r = by_key(common.mark_revisions(rrow, revert[::-1] + [lrow("2025", "3194", "2026-06-01", "verified", "source")]))[
    ("payload-mass-to-orbit", "2025")]
case("revisions: equal to the effective row (numerically, 3194 vs 3194.0) -> unchanged, rule date kept",
     (r["published"], r["published_basis"]) == ("2026-01-15", "rule") and "revises" not in r["note"])
legacy_only = [lrow("2025", "3100", "2026-08-01", "legacy", "seen"), lrow("2024", "2625.9", "2026-08-01", "legacy", "seen")]
lm = by_key(common.mark_revisions(rrow, legacy_only))
case("revisions: only a legacy row exists (differing) -> primary-source value keeps its rule date, note flags legacy",
     (lm[("payload-mass-to-orbit", "2025")]["published"], lm[("payload-mass-to-orbit", "2025")]["published_basis"])
     == ("2026-01-15", "rule") and "legacy report value 3100" in lm[("payload-mass-to-orbit", "2025")]["note"])
case("revisions: only a legacy row exists (equal) -> rule date kept (merge admits it: outranks legacy)",
     lm[("payload-mass-to-orbit", "2024")]["published_basis"] == "rule" and "legacy" not in lm[("payload-mass-to-orbit", "2024")]["note"])
mixed = [lrow("2025", "3194.0", "2026-01-15"), lrow("2025", "3300", "2026-08-01", "legacy", "seen")]
r = by_key(common.mark_revisions(rrow, mixed))[("payload-mass-to-orbit", "2025")]
case("revisions: a newer legacy row does not outrank a non-legacy one (equal to the effective collector row)",
     r["published_basis"] == "rule" and "revises" not in r["note"])

# end to end through the real ledger.prepare (merge planning), with a stubbed ledger state
def effective_after(existing, staged, quiet=False):
    """(rows ledger.prepare would admit, obs_as_of of existing + admitted) for a rockets merge."""
    existing = [dict(r, source="https://example.invalid/x", collector="test", note="") for r in existing]
    saved = ledger.observations, ledger.events, ledger.assessments
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "staged.csv")
        common.write(f, staged)
        try:
            ledger.observations, ledger.events, ledger.assessments = (lambda s: list(existing)), (lambda s: []), (lambda s: [])
            errs, _, plan = ledger.prepare("rockets", obs_files=[f])
        finally:
            ledger.observations, ledger.events, ledger.assessments = saved
    for e in [] if quiet else errs[:5]:
        print("     ", e)
    admitted = plan["obs"] if not errs else None
    return admitted, ledger.obs_as_of("", rows=existing + (admitted or []))


adm, eff = effective_after(revert, common.mark_revisions(rrow, revert))
case("revisions: after merging, the reverted value is the effective one",
     adm is not None and eff[("payload-mass-to-orbit", "2025")]["value"] == "3194.0"
     and eff[("payload-mass-to-orbit", "2025")]["collector"] == "collectors/rockets.py@2026-09-28")
case("revisions: without re-dating, the reverted value would NOT become effective (merge refuses the exact "
     "duplicate of the original row, or it stays outranked; regression guard)",
     effective_after(revert, rrow, quiet=True)[1][("payload-mass-to-orbit", "2025")]["value"] == "3200.0")
adm, eff = effective_after(legacy_only, common.mark_revisions(rrow, legacy_only))
case("revisions: legacy-only rows are superseded by the collector value (both the equal and the differing one)",
     adm is not None and eff[("payload-mass-to-orbit", "2025")]["value"] == "3194.0" and eff[("payload-mass-to-orbit", "2024")]["verification"] == "collector")
same = [lrow(r["obs"], r["value"], r["published"]) for r in rrow]
case("revisions: a re-run against its own output is a no-op (all rows dedup)",
     effective_after(same, common.mark_revisions(rrow, same))[0] == [])

# --- CLI: staged file loads with the exact ledger header ------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    ok = True
    for script, section in (("climate.py", "climate"), ("robots_software.py", "robots-software"), ("rockets.py", "rockets")):
        out = os.path.join(tmp, f"{section}.csv")
        p = subprocess.run([sys.executable, os.path.join(ROOT, "collectors", script), "--fixture", FIX,
                            "--out", out, "--today", "2026-09-28"], capture_output=True, text=True)
        try:
            rows = ledger.load_obs(out)  # raises unless the header is exactly OBS_COLUMNS
            ok &= p.returncode == 0 and bool(rows) and all(r["verification"] == "collector" for r in rows)
        except (OSError, ValueError) as e:
            print("     ", script, e, p.stderr[-500:])
            ok = False
    case("cli: each collector writes a staged CSV with exactly ledger.OBS_COLUMNS", ok)

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall collector tests passed")
sys.exit(1 if FAILS else 0)
