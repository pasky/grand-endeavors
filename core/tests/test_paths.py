#!/usr/bin/env python3
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
        for m in sorted(set(PATH_RE.findall(text))):
            path = m.rstrip(".")
            if path in ("data",):  # the default data repo location, not code
                continue
            case(f"{rel}: $ROOT/{path} exists", os.path.exists(os.path.join(REPO, path)))
        for d, mod in sorted(set(IMPORT_RE.findall(text))):
            where = os.path.join(REPO, d.lstrip("/"))
            case(f"{rel}: import {mod} from $ROOT{d}", os.path.exists(os.path.join(where, mod + ".py")))
    print(f"\n{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
