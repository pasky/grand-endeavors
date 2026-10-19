#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Helpers for gather/editorial.sh, the cross-section editorial pass over the current KPI
labels and rationales (DESIGN.md §4b). Run with cwd = the data repo.

  editorial.py collect <out.jsonl> <notes dir>
                                          one line per section whose current KPI assessment is
                                          judged (not unknown): {section, kpi, record}; prints how
                                          many of them no earlier pass has read (the "Read:" line of
                                          <notes dir>/*.md)
  editorial.py apply <stage> <run id> <made at>
                                          for every proposal the fact check accepted: re-check it
                                          mechanically (core/textcheck.py: only label/rationale,
                                          verdict word kept, numbers from the record, as is or
                                          rounded) against the still-current record, and write
                                          the reworded copy to <stage>/out/<section>.jsonl; prints
                                          one outcome line per proposal
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
import ledger  # noqa: E402
import textcheck  # noqa: E402


def current_kpis(today: dt.date) -> list[dict]:
    out = []
    for s in ledger.SECTIONS:
        try:
            sec, _ = ledger.fw_section(s)
        except KeyError:
            continue
        a = ledger.assessment_as_of(s, today).get("kpi")
        if a and a.get("status") != "unknown":
            out.append({"section": s, "kpi": " ".join(str(sec.get("kpi") or "").split()),
                        "record": ledger.clean(a)})
    return out


def collect(out: str, notes: str) -> int:
    rows = current_kpis(dt.date.today())
    with open(out, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    read = set()
    for p in sorted(os.listdir(notes)) if os.path.isdir(notes) else []:
        for ln in open(os.path.join(notes, p), encoding="utf-8"):
            if ln.startswith("Read: "):
                read.update(ln.split()[1:])
    print(sum(f"{r['section']}:{r['record']['id']}" not in read for r in rows))
    return 0


def accepted(factcheck: str) -> set[str]:
    """Sections with an "ACCEPT <section>" line (a later REJECT line for the same section wins)."""
    ok: set[str] = set()
    for ln in open(factcheck, encoding="utf-8").read().splitlines():
        m = re.fullmatch(r"(ACCEPT|REJECT) ([a-z-]+)\b.*", ln.strip())
        if m:
            (ok.add if m.group(1) == "ACCEPT" else ok.discard)(m.group(2))
    return ok


def apply(stage: str, run_id: str, made: str) -> int:
    cur = {r["section"]: r["record"] for r in current_kpis(dt.date.fromisoformat(made))}
    ok = accepted(os.path.join(stage, "factcheck.md"))
    props = [json.loads(ln) for ln in open(os.path.join(stage, "proposals.jsonl"), encoding="utf-8") if ln.strip()]
    os.makedirs(os.path.join(stage, "out"), exist_ok=True)
    seen = set()
    for p in props:
        s, rid = p.get("section"), p.get("id")
        a = cur.get(s)
        why = None
        if s in seen:
            why = "a second proposal for the section"
        elif s not in ok:
            why = "not accepted by the fact check"
        elif a is None or a["id"] != rid:
            why = f"{rid} is no longer the current KPI assessment"
        elif not isinstance(p.get("label"), str) or not isinstance(p.get("rationale"), str):
            why = "label/rationale missing"
        else:
            probs = textcheck.problems(a, a | {"label": p["label"], "rationale": p["rationale"]})
            if len(p["label"]) > 100:
                probs.append("label longer than 100 chars")
            if (p["label"], p["rationale"]) == (a["label"], a["rationale"]):
                probs.append("no change")
            why = "; ".join(probs) or None
        seen.add(s)
        if why:
            print(f"SKIP {s}: {why}")
            continue
        ids = {x["id"] for x in ledger.assessments(s)}
        base = f"{a['made_at']}-kpi"
        nid = base if base not in ids else next(f"{base}-{n}" for n in range(2, 1000) if f"{base}-{n}" not in ids)
        basis = dict(a.get("basis") or {})
        basis["change_note"] = (f"Label and rationale reworded by the cross-section editorial pass (editorial:{run_id}, "
                                f"{made}); the judgment is {a['id']}'s, unchanged (by {a.get('by')}). "
                                + str(basis.get("change_note") or "")).strip()
        rec = a | {"id": nid, "label": p["label"], "rationale": p["rationale"], "by": f"editorial:{run_id}",
                   "basis": basis}
        with open(os.path.join(stage, "out", f"{s}.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"REWORD {s}: {a['id']} -> {nid}")
    return 0


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["?"]
    if cmd == "collect" and len(args) == 2:
        sys.exit(collect(*args))
    if cmd == "apply" and len(args) == 3:
        sys.exit(apply(*args))
    sys.exit(__doc__)
