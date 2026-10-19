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
  editorial.py apply <stage> <run id> <made at> <out dir> <rounds>
                                          for every proposal the fact check accepted (proposals.jsonl
                                          by factcheck.md, then, with rounds 2, for sections not yet
                                          reworded, proposals-2.jsonl by factcheck-2.md): re-check it
                                          mechanically (core/textcheck.py: only label/rationale,
                                          verdict word kept, numbers from the record, as is or
                                          rounded) against the still-current record, and write
                                          the reworded copy to <out dir>/<section>.jsonl (a
                                          directory the agents never saw); prints one outcome line
                                          per proposal ("REWORD <section>: <old id> -> <new id>"
                                          is the manifest of what to merge)
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


# one-shot authorizations of the record reworded (gather/RUBRIC.md rules 4, 6, 8): a text copy does
# not re-judge, so it must not claim them again (check_hysteresis would count a second use)
ONE_SHOT = ("rubric_correction", "audit_correction", "definition_change")
PREFIX_RE = re.compile(r"Label and rationale reworded by the cross-section editorial pass \([^)]*\); "
                       r"the judgment is (\S+)'s, unchanged \(by ([^)]*)\)\. ?")


def apply(stage: str, run_id: str, made: str, out: str, n_rounds: str) -> int:
    cur = {r["section"]: r["record"] for r in current_kpis(dt.date.fromisoformat(made))}
    rounds = []
    files = (("proposals.jsonl", "factcheck.md"), ("proposals-2.jsonl", "factcheck-2.md"))
    for props, check in files[:int(n_rounds)]:  # only the rounds editorial.sh ran
        pp, cp = os.path.join(stage, props), os.path.join(stage, check)
        if os.path.exists(pp):
            rounds.append((accepted(cp) if os.path.exists(cp) else set(),
                           [json.loads(ln) for ln in open(pp, encoding="utf-8") if ln.strip()]))
    done: set[str] = set()
    for ok, props in rounds:
        seen: set[str] = set()
        for p in props:
            rec = reword(p, ok, cur, seen | done, run_id, made, out)
            seen.add(p.get("section"))
            if rec:
                done.add(rec)
    return 0


def reword(p: dict, ok: set[str], cur: dict, taken: set[str], run_id: str, made: str, out: str) -> str | None:
    """Check one proposal; write its copy and return the section, or print why not."""
    s, rid = p.get("section"), p.get("id")
    a = cur.get(s)
    why = None
    if s in taken:
        why = "another proposal for the section came first"
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
    if why:
        print(f"SKIP {s}: {why}")
        return None
    ids = {x["id"] for x in ledger.assessments(s)}
    base = f"{a['made_at']}-kpi"
    nid = base if base not in ids else next(f"{base}-{n}" for n in range(2, 1000) if f"{base}-{n}" not in ids)
    basis = dict(a.get("basis") or {})
    note, judged, by = str(basis.get("change_note") or ""), a["id"], a.get("by")
    if m := PREFIX_RE.match(note):  # rewording a rewording: still name the judgment itself
        note, judged, by = note[m.end():], m.group(1), m.group(2)
    basis["change_note"] = (f"Label and rationale reworded by the cross-section editorial pass (editorial:{run_id}, "
                            f"{made}); the judgment is {judged}'s, unchanged (by {by}). {note}").strip()
    rec = {k: v for k, v in a.items() if k not in ONE_SHOT} | {
        "id": nid, "label": p["label"], "rationale": p["rationale"], "by": f"editorial:{run_id}", "basis": basis}
    with open(os.path.join(out, f"{s}.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"REWORD {s}: {a['id']} -> {nid}")
    return s

if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["?"]
    if cmd == "collect" and len(args) == 2:
        sys.exit(collect(*args))
    if cmd == "apply" and len(args) == 5:
        sys.exit(apply(*args))
    sys.exit(__doc__)
