"""Throwaway fixture ledger shared by the ledger tests (core/tests/test_ledger.py)
and the bulletin-gate tests (views/tests/test_validate.py). Not a test itself.

fixture() points ledger.ROOT, kpi.ROOT and ledger.DATA at a fresh temp dir holding
a copy of the real framework.yaml, a climate metric registry, observations and events.
"""
import csv
import json
import os
import sys
import tempfile

CORE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CORE)
import kpi  # noqa: E402
import ledger  # noqa: E402

REAL_ROOT = ledger.ROOT


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
    """Temp ROOT: framework.yaml, registry, observations, events, assessments."""
    root = tempfile.mkdtemp()
    ledger.ROOT = kpi.ROOT = ledger.DATA = root
    import shutil
    shutil.copy(os.path.join(REAL_ROOT, "framework.yaml"), root)
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
