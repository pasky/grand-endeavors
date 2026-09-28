#!/bin/sh
# Run one section's deterministic KPI collector and merge its output into the ledger.
#   collectors/run.sh <section> [collector args, e.g. --fixture DIR]
# Stages ledger/staging/<section>-collector.csv, then `ledger.py merge` (which skips
# unchanged (metric, obs, value) rows and appends revisions). Commit the ledger yourself.
set -eu
[ $# -ge 1 ] || { echo "usage: $0 <section> [collector args]" >&2; exit 2; }
section=$1; shift
cd "$(dirname "$0")/.."
script="collectors/$(echo "$section" | tr - _).py"
[ -f "$script" ] || { echo "no collector $script for section '$section'" >&2; exit 2; }
staged="ledger/staging/$section-collector.csv"
mkdir -p ledger/staging
uv run "$script" --out "$staged" "$@"
uv run ledger.py merge "$section" --obs "$staged"
