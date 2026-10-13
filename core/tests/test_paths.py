#!/usr/bin/env python3
# /// script
# dependencies = ["pyyaml"]
# ///
"""Static check that the pipeline scripts reference code that exists.

Run:  uv run core/tests/test_paths.py      (no network, no data repo)

The scripts build their agent prompts in heredocs, where a failing command
substitution does NOT abort under `set -e`: a moved file silently becomes an
empty or broken prompt. So every "$ROOT/<path>" and every `cd "$ROOT[/dir]" &&
... import <module>` in the shell scripts must resolve in this repo.
"""
import glob
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPTS = sorted(set(glob.glob(os.path.join(REPO, "*", "*.sh")) + glob.glob(os.path.join(REPO, "*", "*", "*.sh")))
               - set(glob.glob(os.path.join(REPO, "*", "tests", "*.sh"))))
PATH_RE = re.compile(r"\$\{?ROOT\}?/([A-Za-z0-9_./-]+)")
IMPORT_RE = re.compile(r"""cd "?\$\{?ROOT\}?(/[A-Za-z0-9_/-]+)?"? && [^\n]*?import ([a-z_]+)""")
FAILS = []


def case(name, cond):
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def main():
    case("found the pipeline scripts", len(SCRIPTS) >= 5)
    for script in SCRIPTS:
        rel = os.path.relpath(script, REPO)
        text = open(script, encoding="utf-8").read()
        # syntax, with the interpreter of its shebang (sh = POSIX: no arrays, no [[ ]])
        shell = "bash" if text.startswith("#!/usr/bin/env bash") or text.startswith("#!/bin/bash") else "sh"
        r = subprocess.run([shell, "-n", script], capture_output=True, text=True)
        case(f"{rel}: {shell} -n syntax ok{(': ' + r.stderr.strip()) if r.returncode else ''}", r.returncode == 0)
        for m in sorted(set(PATH_RE.findall(text))):
            path = m.rstrip(".")
            if path in ("data", ".pi/modes.json"):  # the default data repo location; an optional project mode override
                continue
            case(f"{rel}: $ROOT/{path} exists", os.path.exists(os.path.join(REPO, path)))
        for d, mod in sorted(set(IMPORT_RE.findall(text))):
            where = os.path.join(REPO, d.lstrip("/"))
            case(f"{rel}: import {mod} from $ROOT{d}", os.path.exists(os.path.join(where, mod + ".py")))
    # every runnable script declares the third-party modules the shared core needs
    # (`uv run <script>` installs only what the script's own PEP 723 block lists)
    for p in sorted(glob.glob(os.path.join(REPO, "**", "*.py"), recursive=True)):
        rel = os.path.relpath(p, REPO)
        if rel.startswith(("data", "build", ".")):
            continue
        text = open(p, encoding="utf-8").read()
        if text.startswith("#!"):  # runnable: `uv run <script>`
            case(f"{rel}: PEP 723 block declares pyyaml",
                 bool(re.search(r'^# /// script\n(#.*\n)*?# dependencies = \[[^\]]*"pyyaml"', text, re.M)))
    # assess.sh stamps new records with the current rubric version, which ledger.py must know as current
    assess = open(os.path.join(REPO, "gather", "assess.sh"), encoding="utf-8").read()
    ledger_py = open(os.path.join(REPO, "core", "ledger.py"), encoding="utf-8").read()
    sh = re.search(r"^RUBRIC=(\S+)", assess, re.M)
    py = re.search(r'^RUBRICS = \((.*)\)', ledger_py, re.M)
    case("assess.sh RUBRIC = the last of ledger.RUBRICS",
         bool(sh and py) and sh.group(1) == re.findall(r'"(v\d+)"', py.group(1))[-1])
    # assess.sh commits a run's ETA working where ledger.check_notes looks for it
    sh = re.search(r'^NOTES_DIR="([^"]+)"', assess, re.M)
    py = re.search(r'^NOTES_DIR = "([^"]+)"', ledger_py, re.M)
    case("assess.sh NOTES_DIR = ledger.NOTES_DIR", bool(sh and py) and sh.group(1) == py.group(1))
    print(f"\n{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
