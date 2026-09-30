#!/usr/bin/env python3
"""Regression tests for the deterministic checks (ledger.py, kpi.py, validate.py).

Run:  uv run test_harness.py      (no network; builds a throwaway ledger)
Each case pins a behavior that a review found broken or easy to regress.
Collector and explorer tests live in test_collectors.py / test_explorer.py.
"""
import csv
import json
import os
import sys
import tempfile
import urllib.error
from unittest import mock

import kpi
import ledger
import validate

FAILS = []
REAL_ROOT = ledger.ROOT


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def write_jsonl(path, recs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in recs:
            f.write(json.dumps({k: v for k, v in r.items() if not k.startswith("_")}) + "\n")


def has(errs, needle):
    return any(needle in e for e in errs)


def ev(id_, published, claim, topics=("milestone:the-bend",), status="verified", sig=2, **kw):
    return {"id": id_, "date": id_[:10], "published": published, "published_basis": "source",
            "retrieved": "2026-09-28", "kind": "data", "topics": list(topics), "claim": claim,
            "sources": [{"url": f"https://x.org/{id_}", "title": "t", "primary": True}],
            "significance": sig, "collector": "test",
            "verification": {"status": status, "by": "t", "at": "2026-09-28"}, **kw}


def obs(metric, o, value, published, basis="source", unit="ppm", verification="verified", retrieved="2026-09-28"):
    return [metric, o, value, unit, "https://x.org/data", published, basis, retrieved, "test", verification, ""]


def fixture():
    """Temp ROOT: README (climate), registry, observations, events, assessments."""
    root = tempfile.mkdtemp()
    ledger.ROOT = kpi.ROOT = root
    import shutil
    shutil.copy(os.path.join(REAL_ROOT, "README.md"), root)
    write_csv(f"{root}/metrics/climate.csv", kpi.REG_COLUMNS, [
        ["co2-mlo-monthly", "ppm", "monthly", "7", "pilot-26H1", "", "NOAA Mauna Loa monthly mean CO2 dry-air mole fraction"],
        ["co2-mlo-annual", "ppm", "annual", "10", "", "", "NOAA Mauna Loa calendar-year annual mean CO2"],
        ["co2-trend-old", "ppm/yr", "annual", "", "", "pilot-2025", "Old basis decadal trend of global annual means (retired)"],
    ])
    write_csv(ledger.path("observations", "climate"), ledger.OBS_COLUMNS, [
        obs("co2-mlo-monthly", "2025-11", "426.5", "2026-01-03", "seen", verification="legacy", retrieved="2026-01-03"),
        obs("co2-mlo-monthly", "2025-06", "429.61", "2025-07-07", "rule"),
        obs("co2-mlo-monthly", "2026-06", "431.43", "2026-07-07", "rule"),
        obs("co2-mlo-monthly", "2026-07", "429.13", "2026-08-07", "rule"),   # after the 26H1 cutoff
        *[obs("co2-mlo-annual", str(y), v, f"{y + 1}-01-10", "rule")
          for y, v in [(2021, "416.41"), (2022, "418.53"), (2023, "421.08"), (2024, "424.61"), (2025, "427.35")]],
    ])
    write_jsonl(ledger.path("events", "climate"), [
        ev("2025-11-13-gcb-projection", "2025-11-13", "Global Carbon Budget projects 2025 fossil CO2 at 38.1 GtCO2, up 1.1%.", status="legacy"),
        ev("2026-05-13-gcb-final", "2026-05-13", "Global Carbon Budget final paper puts 2025 fossil CO2 at 38.1 GtCO2, up 1.0%.",
           relates=[{"id": "2025-11-13-gcb-projection", "rel": "update"}]),
        ev("2026-08-27-climate-trace-h1", "2026-08-27", "Climate TRACE: total GHG in H1 2026 was 29.7 GtCO2e, up 0.2% on H1 2025."),
    ])
    return root


def main():
    # --- number matching -----------------------------------------------------
    nums = kpi.kpi_numbers("fell −0.5% in 2016-2025, $2000/kg, 38,082 Mt, (+1.0%)")
    case("kpi_numbers keeps sign, years-as-data, thousands", {-0.5, 2000.0, 38082.0, 1.0} <= nums and -2025.0 not in nums)
    case("negative value matches unsigned prose", kpi.kpi_traceable("-0.5", {0.5}))
    case("positive value never matches negative evidence", not kpi.kpi_traceable("0.5", {-0.5}))
    case("roundup numbers(): unit suffix + no partial decimals",
         validate.numbers("9% $8.99B 12.5GW in 2025 the") == {"9", "8.99", "12.5"})

    # --- periods / cutoffs ------------------------------------------------------
    case("26H1 cutoff = period end + 14d", str(ledger.cutoff("26H1")) == "2026-07-14")
    case("26H1 previous cutoff = 25H2 cutoff", str(ledger.prev_cutoff("26H1")) == "2026-01-14")
    case("weekly cutoff = Sunday + 2d", str(ledger.cutoff("2026-W39")) == "2026-09-29")
    case("weekly previous cutoff is one week earlier", str(ledger.prev_cutoff("2026-W39")) == "2026-09-22")

    # --- registry ---------------------------------------------------------------
    fixture()
    reg, errs = ledger.kpi.load_registry("climate") if hasattr(ledger, "kpi") else kpi.load_registry("climate")
    case("fixture registry loads clean", errs == [] and len(reg) == 3)
    with open(f"{kpi.ROOT}/metrics/climate.csv", "a") as f:
        f.write("co2-x,ppm,monthly,7,,,NOAA monthly mean, unquoted comma here\n")
    case("registry row with an unquoted comma is rejected",
         any("wrong number of fields" in e for e in kpi.load_registry("climate")[1]))
    fixture()
    write_csv(f"{kpi.ROOT}/metrics/climate.csv", kpi.REG_COLUMNS, [])
    case("header-only registry still enforces registration",
         has(ledger.check_obs_row(dict(zip(ledger.OBS_COLUMNS, obs("co2-mlo-monthly", "2026-06", "431.43", "2026-07-07"))) | {"_line": 2},
                                  kpi.load_registry("climate")[0]), "not in the registry"))

    # --- ledger check -------------------------------------------------------------
    fixture()
    errs, warns = ledger.check_section("climate")
    case("clean fixture ledger passes", errs == [] and warns == [])
    reg = kpi.load_registry("climate")[0]
    row = lambda *a, **k: dict(zip(ledger.OBS_COLUMNS, obs(*a, **k))) | {"_line": 9}
    case("unregistered metric is an error", has(ledger.check_obs_row(row("co2-renamed", "2026-06", "1", "2026-07-07"), reg), "not in the registry"))
    case("unit drift vs registry is an error", has(ledger.check_obs_row(row("co2-mlo-annual", "2025", "1", "2026-01-10", unit="ppb"), reg), "!= registry"))
    case("rule-basis date must equal obs end + lag", has(ledger.check_obs_row(row("co2-mlo-monthly", "2026-06", "1", "2026-07-01", "rule"), reg), "rule-basis published must be"))
    case("published after retrieved is an error", has(ledger.check_obs_row(row("co2-mlo-monthly", "2026-06", "1", "2026-10-01"), reg), "published after retrieved"))
    case("published before the observed period is an error", has(ledger.check_obs_row(row("co2-mlo-annual", "2026", "1", "2025-12-01"), reg), "before the observed period"))
    topics = ledger.valid_topics("climate")
    bad = ev("2026-05-13-x", "2026-05-13", "short", topics=("nope",), sig=5)
    es = ledger.check_event(bad, "climate", topics)
    case("event schema: unknown topic, short claim, bad significance",
         has(es, "unknown topic") and has(es, "claim too short") and has(es, "significance"))
    case("README topics include fusion tech-tree branches as challenges",
         "challenge:d-t-fusion" in ledger.valid_topics("fusion") and "milestone:d-t-fusion" not in ledger.valid_topics("fusion"))
    dup = [ev("2026-05-13-a", "2026-05-13", "Global Carbon Budget final paper puts 2025 fossil CO2 at 38.1 GtCO2 up 1.0 percent."),
           ev("2026-05-14-b", "2026-05-14", "Global Carbon Budget final paper puts 2025 fossil CO2 at 38.1 GtCO2, up 1.0%, a record.")]
    case("near-duplicate claims are flagged", len(ledger.near_duplicates(dup)) == 1)
    par = [ev("2024-01-01-a", "2024-06-30", "IRENA global weighted-average LCOE of solar PV in 2024 was 43 USD/MWh."),
           ev("2024-01-01-b", "2024-06-30", "IRENA global weighted-average LCOE of onshore wind in 2024 was 34 USD/MWh.")]
    case("parallel claims with different figures are not duplicates", ledger.near_duplicates(par) == [])

    # --- assessments ---------------------------------------------------------------
    evs = {e["id"]: e for e in ledger.events("climate")}
    a = {"id": "2026-07-14-milestone-the-bend", "target": "milestone:the-bend", "status": "yellow", "label": "x",
         "made_at": "2026-07-14", "rationale": "r", "evidence": ["2026-08-27-climate-trace-h1"], "by": "t"}
    case("hindsight evidence (published after made_at) is rejected", has(ledger.check_assessment(a, topics, evs), "hindsight"))
    a["evidence"] = ["2026-05-13-gcb-final"]
    case("assessment with timely evidence passes", ledger.check_assessment(a, topics, evs) == [])

    # --- merge ------------------------------------------------------------------------
    st = f"{kpi.ROOT}/staged.jsonl"
    write_jsonl(st, [ev("2026-06-04-good", "2026-06-04", "CREA: China CO2 rose 2% year on year in Q1 2026, per Carbon Brief."),
                     ev("2026-06-05-bad", "2026-06-05", "Rejected by the verifier because the source does not say this.", status="rejected")])
    n0 = len(ledger.events("climate"))
    errs, stats = ledger.merge("climate", [st])
    case("merge admits verified, rejects the rest to ledger/rejected",
         errs == [] and stats["events_in"] == 1 and stats["events_rejected"] == 1
         and len(ledger.events("climate")) == n0 + 1 and os.path.exists(ledger.path("rejected", "climate")))
    write_jsonl(st, [ev("2026-06-06-ok", "2026-06-06", "A perfectly fine verified claim about emissions in 2026."),
                     ev("2026-06-07-broken", "2026-06-07", "x", topics=("nope",))])
    n1 = len(ledger.events("climate"))
    errs, _ = ledger.merge("climate", [st])
    case("merge is all-or-nothing on schema errors", errs != [] and len(ledger.events("climate")) == n1)
    good = ev("2026-06-06-ok", "2026-06-06", "A perfectly fine verified claim about emissions in 2026.")
    write_jsonl(st, [good, good])
    errs, stats = ledger.merge("climate", [st])
    n2 = len(ledger.events("climate"))
    errs2, stats2 = ledger.merge("climate", [st])
    case("same event twice in a batch is merged once; exact replay is a no-op",
         errs == [] and stats["events_in"] == 1 and errs2 == [] and stats2["events_replayed"] == 1
         and len(ledger.events("climate")) == n2 and ledger.check_section("climate")[0] == [])
    write_jsonl(st, [dict(good, claim="A conflicting different claim reusing an existing event id.")])
    case("conflicting replay of an existing id is rejected",
         has(ledger.merge("climate", [st])[0], "different content"))
    fix = ev("2026-06-06-ok-r2", "2026-06-06", "A perfectly fine verified claim about emissions in 2026.",
             supersedes=["2026-06-06-ok"])
    fix["sources"].append({"url": "https://x.org/second-source", "title": "t2", "primary": False})
    write_jsonl(st, [fix])
    errs, _ = ledger.merge("climate", [st])
    eff = {e["id"] for e in ledger.effective_events(ledger.events("climate"))}
    case("supersedes: correction with the same claim merges; views drop the superseded record",
         errs == [] and "2026-06-06-ok-r2" in eff and "2026-06-06-ok" not in eff)
    bad_date = ev("2026-99-99-x", "2026-06-06", "A claim with an impossible date prefix in its id.")
    bad_date["date"] = "2026-99-99"
    case("impossible dates are rejected", has(ledger.check_event(bad_date, "climate", topics), "bad date"))
    seen = ev("2026-06-08-seen", "2026-06-08", "A claim whose publication date is only first-seen.")
    seen["published_basis"] = "seen"
    case("basis=seen requires published = retrieved", has(ledger.check_event(seen, "climate", topics), "first seen"))
    unv = ev("2026-06-09-unv", "2026-06-09", "A claim that the verifier never looked at at all.", status="unverified")
    write_jsonl(st, [unv])
    case("lint --final rejects leftover unverified records", has(ledger.lint("climate", [st], final=True), "still unverified"))
    write_jsonl(st, [ev("2026-06-10-fresh", "2026-06-10", "A new staged claim linted next to existing legacy records.", status="unverified")])
    case("lint passes staged records alongside existing legacy records (no status false positives)",
         ledger.lint("climate", [st]) == [])
    so = f"{kpi.ROOT}/staged.csv"
    write_csv(so, ledger.OBS_COLUMNS, [obs("co2-mlo-annual", "2024", "424.610", "2025-01-10", "rule", verification="collector")])
    errs, stats = ledger.merge("climate", [], [so])
    case("numerically equal re-observation is not a revision", errs == [] and stats["obs_dup"] == 1 and stats["obs_in"] == 0)
    for v, when in (("425", "2026-09-01"), ("424.61", "2026-09-02")):
        write_csv(so, ledger.OBS_COLUMNS, [obs("co2-mlo-annual", "2024", v, when, "seen", verification="collector", retrieved=when)])
        ledger.merge("climate", [], [so])
    case("revision back to an earlier value is recorded (compared with the EFFECTIVE row)",
         ledger.obs_as_of("climate")[("co2-mlo-annual", "2024")]["value"] == "424.61")
    case("non-legacy observations outrank later-dated legacy ones",
         ledger.obs_as_of("climate")[("co2-mlo-monthly", "2025-11")]["verification"] == "legacy")  # only a legacy row exists
    write_csv(so, ledger.OBS_COLUMNS, [obs("co2-mlo-monthly", "2025-11", "426.46", "2025-12-07", "rule", verification="collector")])
    errs, stats = ledger.merge("climate", [], [so])
    case("verified value supersedes the legacy one despite an earlier publication date",
         errs == [] and stats["obs_in"] == 1 and ledger.obs_as_of("climate")[("co2-mlo-monthly", "2025-11")]["value"] == "426.46")

    # --- verification-review regressions -----------------------------------------------------
    fixture()
    so = f"{kpi.ROOT}/staged.csv"
    write_csv(so, ledger.OBS_COLUMNS, [
        obs("co2-mlo-annual", "2024", "425", "2026-09-01", "seen", verification="collector", retrieved="2026-09-01"),
        obs("co2-mlo-annual", "2024", "426", "2026-09-02", "seen", verification="collector", retrieved="2026-09-02"),
        obs("co2-mlo-annual", "2023", "1", "2026-09-02", "seen", verification="rejected", retrieved="2026-09-02")])
    e1, _ = ledger.merge("climate", [], [so])
    n_rej = len(ledger.load_jsonl(ledger.path("rejected", "climate")))
    e2, st2 = ledger.merge("climate", [], [so])
    case("observation batch replay (two revisions + a reject) is a full no-op",
         e1 == [] and e2 == [] and st2["obs_in"] == 0 and n_rej == len(ledger.load_jsonl(ledger.path("rejected", "climate")))
         and ledger.check_section("climate")[0] == [])
    open(os.path.join(kpi.ROOT, "ledger", ".lock-climate"), "w").close()   # empty leftover lock file
    case("an empty leftover lock file does not block merges (OS-held flock)", ledger.merge("climate", [], [so])[0] == [])
    stg = f"{kpi.ROOT}/chain.jsonl"
    same = "The same corrected claim text appears in a three-record replacement chain."
    write_jsonl(stg, [ev("2026-06-11-a", "2026-06-11", same),
                      ev("2026-06-11-c", "2026-06-11", same, supersedes=["2026-06-11-a"]),
                      ev("2026-06-11-b", "2026-06-11", same, supersedes=["2026-06-11-c"])])
    case("supersedes chains validate independently of record order",
         ledger.merge("climate", [stg])[0] == [] and ledger.check_section("climate")[0] == [])
    cyc = [ev("2026-06-12-x", "2026-06-12", "Cycle member one with its own distinct claim text here.", supersedes=["2026-06-12-y"]),
           ev("2026-06-12-y", "2026-06-12", "Cycle member two with a different distinct claim text.", supersedes=["2026-06-12-x"])]
    case("supersedes cycles are rejected", has(ledger.validate_state("climate", cyc, [], [])[0], "cycle"))
    # stale: same-day and late-discovered evidence
    fixture()
    a = {"id": "2026-09-28-milestone-the-bend", "target": "milestone:the-bend", "status": "yellow", "label": "x",
         "made_at": "2026-09-28", "rationale": "r", "evidence": ["2026-05-13-gcb-final"], "by": "t"}
    write_jsonl(f"{kpi.ROOT}/a.jsonl", [a])
    ledger.merge("climate", [], [], [f"{kpi.ROOT}/a.jsonl"])
    until = __import__("datetime").date(2026, 9, 29)
    fresh = lambda: [t for t, _ in ledger.stale_targets("climate", until)]
    case("sealed assessment is not stale without new evidence", "milestone:the-bend" not in fresh())
    write_jsonl(stg, [ev("2026-09-20-late-found", "2026-09-20", "A late-discovered September item about the emissions peak question.")])
    ledger.merge("climate", [stg])
    case("late-discovered evidence (published before made_at) makes the assessment stale", "milestone:the-bend" in fresh())
    case("assessment ties on made_at: the later appended record wins",
         (write_jsonl(ledger.path("assessments", "climate"), [dict(a, id="x-9", label="old"), dict(a, id="x-10", label="new")]) or True)
         and ledger.assessment_as_of("climate", until)["milestone:the-bend"]["label"] == "new")

    # --- status rubric v1 (STATUS.md) ----------------------------------------------------------
    fixture()
    evs = {e["id"]: e for e in ledger.events("climate")}
    topics = ledger.valid_topics("climate")
    base = {"target": "milestone:the-bend", "made_at": "2026-07-14", "rationale": "r", "by": "t",
            "evidence": ["2026-05-13-gcb-final"], "rubric": "v1",
            "basis": {"rule": "x", "eta": "x", "path": "x", "blockers": "x", "prev": None, "change_note": "x"}}
    A = lambda **k: dict(base, id=k.pop("id", "a1"), status=k.pop("status", "red"), label=k.pop("label", "Distant: x"), **k)
    case("rubric: verdict word must match the status", has(ledger.check_assessment(A(label="Worsening: x"), topics, evs), "verdict"))
    case("rubric: milestone basis fields are required",
         has(ledger.check_assessment(A(basis={"rule": "x"}), topics, evs), "basis"))
    case("rubric: 'achieved' needs a verified achievement event",
         has(ledger.check_assessment(A(status="achieved", label="Achieved: x"), topics, evs), "achievement"))
    case("rubric: 'achieved' is for milestones only",
         has(ledger.check_assessment(A(target="kpi", status="achieved", label="Achieved: x"), topics, evs), "milestones only"))
    evs2 = dict(evs, **{"2026-08-01-late": ev("2026-08-01-late", "2026-08-01", "A later verified event about emissions peaking globally.")})
    prev = A(id="p", status="yellow", label="Progressing: x", made_at="2026-07-14")
    flip = A(id="f", made_at="2026-09-28")
    case("hysteresis: status change without newer evidence is rejected",
         has(ledger.check_hysteresis("climate", [prev, flip], evs2), "hysteresis"))
    case("hysteresis: status change backed by newer evidence passes",
         ledger.check_hysteresis("climate", [prev, dict(flip, evidence=["2026-08-01-late"])], evs2) == [])
    corr = dict(flip, rubric_correction="v1")
    case("hysteresis: one rubric correction per target is allowed, a second is not",
         ledger.check_hysteresis("climate", [prev, corr], evs2) == []
         and has(ledger.check_hysteresis("climate", [prev, corr, dict(corr, id="g", made_at="2026-09-29")], evs2), "second"))
    kpi_a = dict(A(id="k", target="kpi", label="Off track: x"), basis={k: "x" for k in ledger.BASIS_KPI})
    case("rubric: KPI assessment needs the section's spec in metrics/kpi-assessment.csv",
         has(ledger.check_hysteresis("climate", [kpi_a], evs2), "kpi-assessment.csv"))

    # --- snapshot ---------------------------------------------------------------------
    fixture()
    pdir = f"{kpi.ROOT}/pilot-26H1"
    snap = ledger.snapshot(pdir, "climate")
    new = {e["id"] for e in snap["new_events"]}
    case("snapshot: new = published in (prev cutoff, cutoff]", new == {"2026-05-13-gcb-final"})
    case("snapshot: post-cutoff events excluded", "2026-08-27-climate-trace-h1" not in new | {e["id"] for e in snap["background_events"]})
    case("snapshot: legacy events are background, never news",
         "2025-11-13-gcb-projection" in {e["id"] for e in snap["background_events"]})
    k = snap["kpi_headlines"][0]
    case("snapshot: KPI headline = latest obs in period known by cutoff (not the July value)",
         k["current"]["obs"] == "2026-06" and k["previous"]["obs"] == "2025-11")
    case("snapshot: seasonal caveat + same-month-last-year comparison",
         not k["change"]["comparable"] and k["year_ago"]["change"] == "+1.82")
    case("snapshot: retired metrics never required", all(x["metric"] != "co2-trend-old" for x in snap["kpi_headlines"]))
    case("snapshot is self-contained: frozen series + README framework",
         snap["series"]["co2-mlo-annual"][-1] == ["2025", "427.35"] and any(f["name"] == "The Bend" for f in snap["framework"]))
    reg_rows = list(csv.reader(open(f"{kpi.ROOT}/metrics/climate.csv")))
    write_csv(f"{kpi.ROOT}/metrics/climate.csv", reg_rows[0], reg_rows[1:] + [
        ["co2-old-required", "ppm", "annual", "10", "pilot-2025", "pilot-26H1", "A metric required through 26H1 then retired"]])
    case("requirement judged at the period end (retired_after = this period still counts)",
         any(k["metric"] == "co2-old-required" for k in ledger.snapshot(pdir, "climate")["kpi_headlines"]))
    write_csv(f"{kpi.ROOT}/metrics/climate.csv", reg_rows[0], reg_rows[1:])
    ev_text = ledger.snapshot_evidence_text(snap)
    write_jsonl(f"{kpi.ROOT}/sup.jsonl", [ev("2026-05-13-gcb-final-r2", "2026-05-13",
        "Global Carbon Budget final paper: 2025 fossil CO2 was 38.1 GtCO2, up 1.0 percent.", supersedes=["2026-05-13-gcb-final"])])
    write_jsonl(ledger.path("assessments", "climate"), [{"id": "2026-07-14-milestone-the-bend", "target": "milestone:the-bend",
        "status": "yellow", "label": "x", "made_at": "2026-07-14", "rationale": "r", "evidence": ["2026-05-13-gcb-final"], "by": "t"}])
    ledger.merge("climate", [f"{kpi.ROOT}/sup.jsonl"])
    s3 = ledger.snapshot(pdir, "climate")
    kept = [e for e in s3["background_events"] if e["id"] == "2026-05-13-gcb-final"]
    case("snapshot keeps superseded assessment evidence, flagged superseded_by",
         kept and kept[0].get("superseded_by") == "2026-05-13-gcb-final-r2")
    case("all series are frozen (short ones too)", "co2-mlo-monthly" in s3["series"])
    case("typed evidence pool excludes metadata (significance, ids)", '"significance"' not in ev_text and "gcb-final" not in ev_text)
    write_jsonl(ledger.path("events", "climate"), ledger.events("climate") + [
        ev("2026-01-05-minor-evidence", "2026-01-05", "A minor but cited analysis says emissions have plateaued in 2025.", sig=1)])
    write_jsonl(ledger.path("assessments", "climate"), [
        {"id": "2026-07-14-milestone-the-bend", "target": "milestone:the-bend", "status": "yellow", "label": "x",
         "made_at": "2026-07-14", "rationale": "r", "evidence": ["2026-01-05-minor-evidence"], "by": "t"}])
    snap2 = ledger.snapshot(pdir, "climate")
    case("snapshot: assessment evidence is always included",
         "2026-01-05-minor-evidence" in {e["id"] for e in snap2["background_events"]})

    # --- charts from the ledger ------------------------------------------------------------
    chart = kpi.chart(pdir, "climate", ["co2-mlo-annual"], label="year", since="2021")
    case("ledger-rendered chart verifies clean", kpi.verify_charts(chart, pdir) == [])
    case("tampered chart value is caught", kpi.verify_charts(chart.replace("427.35", "427.36"), pdir) != [])
    y_line = next(ln for ln in chart.splitlines() if "y-axis" in ln)
    case("clipping y-axis is caught",
         has(kpi.verify_charts(chart.replace(y_line, '    y-axis "ppm" 425 --> 426'), pdir), "clips"))
    case("chart excludes obs after the period end",
         "429.13" not in kpi.chart(pdir, "climate", ["co2-mlo-monthly"], match="*-0[67]"))

    # --- bulletin gate (validate --snapshot) --------------------------------------------------
    sp = f"{pdir}/snapshot/climate.json"
    os.makedirs(os.path.dirname(sp), exist_ok=True)
    json.dump(snap, open(sp, "w"))
    names = [n for items in ledger.readme_topics("climate").values() for _, n in items]
    doc = (f"# Climate\n\nCO2 was 431.43 ppm in June 2026[^a].\n\n{chart}\n\n"
           + "\n".join(f"### {n}\nNo significant developments." for n in names)
           + "\n\n[^a]: [GCB](https://x.org/2026-05-13-gcb-final)\n")
    dp = f"{pdir}/climate.md"

    def gate(text):
        open(dp, "w").write(text)
        validate.ERRORS.clear(); validate.WARNS.clear()
        validate.check_snapshot(dp, text, sp)
        return list(validate.ERRORS)
    case("bulletin gate: faithful bulletin passes", gate(doc) == [])
    case("bulletin gate: number not in snapshot is caught", has(gate(doc.replace("431.43 ppm", "431.43 ppm (about 432)")), "number 432"))
    case("bulletin gate: URL outside the snapshot is caught", has(gate(doc.replace("https://x.org/2026-05-13-gcb-final", "https://evil.org/x")), "not a source"))
    case("bulletin gate: unreported KPI headline is caught", has(gate(doc.replace("431.43 ppm", "high")), "not reported"))
    case("bulletin gate: uncovered milestone is caught", has(gate(doc.replace("### The Bend", "### Something")), "The Bend"))
    case("bulletin gate: a name only in prose (no heading) does not count as coverage",
         has(gate(doc.replace("### The Bend\n", "The Bend is mentioned.\n")), "The Bend"))
    case("bulletin gate: charts come from the frozen snapshot, not today's ledger",
         (write_csv(ledger.path("observations", "climate"), ledger.OBS_COLUMNS,
                    [list(r.values())[:11] for r in ledger.observations("climate")]
                    + [obs("co2-mlo-annual", "2020", "414.21", "2021-01-10", "rule")]) or True)
         and gate(doc) == [])
    old = {k: v for k, v in snap.items() if k not in ("series", "framework")}
    json.dump(old, open(sp, "w"))
    case("pre-freeze snapshots fail explicitly (no silent live-ledger fallback)",
         has(gate(doc), "predates"))
    json.dump(snap, open(sp, "w"))
    case("URLs with balanced parentheses are extracted whole",
         validate.extract_urls("[x](https://a.org/S0092-8674(25)00284-3).") == ["https://a.org/S0092-8674(25)00284-3"])

    # --- link probe (mocked, no network) -----------------------------------------------------
    def seq(*codes):
        it = iter(codes)

        def fake(req, timeout=15):
            c = next(it)
            if c == 200:
                m = mock.MagicMock()
                m.__enter__.return_value.status = 200
                return m
            raise urllib.error.HTTPError(req.full_url, c, "x", {}, None)
        return fake

    with mock.patch("time.sleep"):
        for codes, want, name in [
            ((404, 200), "ok", "HEAD 404 then GET 200 is alive"),
            ((404, 404, 200), "ok", "one transient GET 404 is retried"),
            ((404, 404, 404), "404", "two GET 404s are dead"),
            ((403, 403), "403", "403 stays warn-level (not dead)"),
        ]:
            with mock.patch("urllib.request.urlopen", seq(*codes)):
                case(name, validate.probe("https://x.org/p") == want)

    print(f"\n{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
