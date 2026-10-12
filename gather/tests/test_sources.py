#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Offline tests for the reference source lists (gather/sources.py, gather/sources/*.yaml).

Run:  uv run gather/tests/test_sources.py      (no network, no data repo)
"""
import os
import subprocess
import sys
import tempfile

GATHER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, GATHER)

import sources  # noqa: E402  (puts core/ on sys.path)
import ledger  # noqa: E402

FAILS = []


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def entry(**kw):
    e = {"name": "X", "url": "https://example.org/x", "items": ["kpi"], "covers": "c",
         "cadence": "monthly", "tier": "primary"}
    e.update(kw)
    return e


# --- the committed lists ----------------------------------------------------------------------
for s in ledger.SECTIONS:
    case(f"{s}: has a source list", os.path.exists(sources.path(s)))
    errs = sources.check(s)
    case(f"{s}: list is valid against framework.yaml", not errs)
    for x in errs[:5]:
        print("     ", x)
    # every milestone/challenge has its own tagged sources ("*" entries don't count);
    # kpi and beyond may rely on section-wide ones
    lst = sources.load(s) if os.path.exists(sources.path(s)) else []
    empty = [t for t, _, _ in ledger.framework_items(s)
             if not (any(t in e["items"] for e in lst) or (t in ("kpi", "beyond") and sources.for_item(s, t, lst)))]
    case(f"{s}: every watch item has a source", not empty)
    if empty:
        print("      no sources for:", ", ".join(empty))

# --- the validator ----------------------------------------------------------------------------
def errs_of(*entries):
    return sources.check("climate", list(entries))


case("check: a valid entry passes", errs_of(entry()) == [])
case("check: unknown watch item (e.g. a renamed slug)",
     any("unknown watch item 'milestone:gone'" in x for x in errs_of(entry(items=["milestone:gone"]))))
case("check: duplicate url", any("duplicate url" in x for x in errs_of(entry(), entry(name="Y"))))
case("check: bad tier", any("tier" in x for x in errs_of(entry(tier="blog"))))
case("check: missing field", any("missing covers" in x for x in errs_of(entry(covers=""))))
case("check: unknown field", any("unknown field" in x for x in errs_of(entry(itmes=["kpi"]))))
case("check: items must be a non-empty list", bool(errs_of(entry(items="kpi"))) and bool(errs_of(entry(items=[]))))
case("check: non-http url", any("bad url" in x for x in errs_of(entry(url="example.org"))))

# malformed files fail loudly instead of reading as an empty list
real_dir = sources.DIR
with tempfile.TemporaryDirectory() as tmp:
    sources.DIR = tmp
    bad = {"sources: {}\n": "non-list", "sources: false\n": "false", "sources: []\n": "empty",
           "source:\n  - name: X\n": "misspelled key", "- name: X\n": "top-level list",
           "sources: [\n": "invalid YAML"}
    for text, what in bad.items():
        with open(sources.path("climate"), "w") as f:
            f.write(text)
        case(f"check: malformed file ({what}) is an error", bool(sources.check("climate")))
    p = subprocess.run([sys.executable, "-c", f"import sys; sys.argv=['sources.py','list','climate','kpi']; "
                        f"sys.path.insert(0, {GATHER!r}); import sources; sources.DIR={tmp!r}; sys.exit(sources.main())"],
                       capture_output=True, text=True)
    case("cli list: a malformed file fails (gather.sh aborts)", p.returncode != 0)
sources.DIR = real_dir

# --- selection for one watch item --------------------------------------------------------------
lst = [entry(name="A", url="https://a", items=["kpi"]),
       entry(name="W", url="https://w", items=["*"]),
       entry(name="B", url="https://b", items=["beyond", "kpi"]),
       entry(name="C", url="https://c", items=["beyond"])]
case("for_item: tagged entries in file order, then section-wide ones",
     [e["name"] for e in sources.for_item("climate", "kpi", lst)] == ["A", "B", "W"])
case("line: collector-fed sources are marked",
     "fetched by the section collector" in sources.line(entry(collector=True))
     and "collector" not in sources.line(entry()))

# --- CLI (what gather.sh calls) ------------------------------------------------------------------
cli = [sys.executable, os.path.join(GATHER, "sources.py")]
p = subprocess.run(cli + ["list", "climate", "kpi"], capture_output=True, text=True)
case("cli list: prints the item's sources", p.returncode == 0 and "https://gml.noaa.gov/ccgg/trends/" in p.stdout)
p = subprocess.run(cli + ["list", "climate", "milestone:nope"], capture_output=True, text=True)
case("cli list: an unknown watch item fails", p.returncode != 0)
p = subprocess.run(cli + ["check"], capture_output=True, text=True)
case("cli check: all lists pass", p.returncode == 0)

print(f"\n{len(FAILS)} failure(s)" if FAILS else "\nall source-list tests passed")
sys.exit(1 if FAILS else 0)
