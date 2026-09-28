#!/usr/bin/env python3
"""One-off migration (2026-09): per-period KPI vintages -> ledger/observations.

pilot-2025/kpis/<s>.csv  -> verification=legacy, published_basis=seen,
                            published=retrieved=first commit date of pilot-2025/<s>.md
pilot-26H1/kpis/<s>.csv  -> verification=verified (passed review + audit);
                            retrieved = first commit of the 26H1 research note (NOAA
                            files fetched Sep 2026); published = registry lag rule, or
                            the source date stated in the research notes.
"""
import csv, glob, os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kpi, ledger

def first_commit_date(p):
    out = subprocess.run(["git", "log", "--diff-filter=A", "--format=%as", "--", p],
                         capture_output=True, text=True, check=True).stdout.split()
    return out[-1]

# Source-stated publication dates for 26H1 metrics without a regular release lag
# (from pilot-26H1/research/climate/*.md).
SOURCE_DATES = {
    "metoffice.gov.uk": ("2026-02-04", "Met Office forecast page dated 4 Feb 2026"),
    "essd.copernicus.org": ("2026-05-13", "GCB 2025 final paper, ESSD 13 May 2026"),
    "iea.blob.core.windows.net": ("2026-04-30", "IEA GER 2026 (April 2026; day unknown -> month end, upper bound)"),
    "nature.com": ("2026-04-14", "Carbon Monitor, Nat Rev Earth Environ 14 Apr 2026"),
}
rows = {}
for path in sorted(glob.glob("pilot-*/kpis/*.csv")):
    pdir, sec = path.split("/")[0], os.path.basename(path)[:-4]
    reg, _ = kpi.load_registry(sec)
    legacy = pdir == "pilot-2025"
    if legacy:
        d = first_commit_date(f"{pdir}/{sec}.md")
    else:
        # NOT the note's first commit (June toy run): the values were re-fetched
        # in the FRESH=1 regen of 2026-09-25 (commit fbf0386).
        d = "2026-09-25"
    for r in csv.DictReader(open(path, newline="")):
        o = {"metric": r["metric"], "obs": r["obs"], "value": r["value"], "unit": r["unit"],
             "source": r["source"], "retrieved": d, "collector": f"backfill:{path}",
             "verification": "legacy" if legacy else "verified", "note": r["note"]}
        if legacy:
            o.update(published=d, published_basis="seen")
        elif reg[r["metric"]]["release_lag_days"]:
            o.update(published=ledger.rule_published(r["obs"], reg[r["metric"]]["release_lag_days"], d),
                     published_basis="rule")
        else:
            host = r["source"].split("/")[2].removeprefix("www.")
            if host not in SOURCE_DATES:
                sys.exit(f"no publication date rule for {r['metric']} {r['source']}")
            pub, why = SOURCE_DATES[host]
            o.update(published=pub, published_basis="source",
                     note=(o["note"] + "; " if o["note"] else "") + f"published: {why}")
        rows.setdefault(sec, []).append(o)
for sec, rs in rows.items():
    p = ledger.path("observations", sec)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ledger.OBS_COLUMNS, lineterminator="\n")
        w.writeheader(); w.writerows(rs)
    print(sec, len(rs))
