#!/usr/bin/env bash
# Write the judge prompts for one section in batches: gather/reverify-judge-batches.sh <section> [batch size]
# -> <cache>/<section>/judge-NN.md (one per batch; results go to results-wayback2.NN.jsonl)
set -euo pipefail
cd "$(dirname "$0")/.."
sec=$1; size=${2:-6}
cache=${GE_REVERIFY_CACHE:-$HOME/.cache/grand-endeavors/reverify}
uv run --quiet gather/reverify_legacy.py list "$sec" | uv run --no-project python3 -c '
import json, sys, re
sec, size, cache, repo = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
ids = [json.loads(l)["id"] for l in sys.stdin if l.strip()]
tpl = open("gather/reverify-judge.md").read().split("\n---\n", 1)[1]
for b in range(0, len(ids), size):
    n = b // size + 1
    out = f"{cache}/{sec}/results-wayback2.{n:02d}.jsonl"
    s = tpl.replace("{SECTION}", sec).replace("{REPO}", repo).replace("{CACHE}", cache) \
           .replace("{OUT}", out).replace("{IDS}", "\n".join("- " + i for i in ids[b:b + size]))
    assert not re.search(r"\{[A-Z]+\}", s)
    open(f"{cache}/{sec}/judge-{n:02d}.md", "w").write(s)
    print(f"{cache}/{sec}/judge-{n:02d}.md")
' "$sec" "$size" "$cache" "$PWD"
