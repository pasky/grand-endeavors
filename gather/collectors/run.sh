#!/bin/sh
# Run one section's deterministic KPI collector and merge its output into the ledger.
#   gather/collectors/run.sh <section> [collector args, e.g. --fixture DIR]
# Stages ledger/staging/<section>-collector.csv, then `ledger.py merge <section> --obs FILE...`
# (validates the whole proposed ledger, dedups each row against the EFFECTIVE row for its
# (metric, obs), appends revisions; locked, atomic, replay-idempotent: after a crash just
# re-run). Commit the ledger yourself.
set -eu
[ $# -ge 1 ] || { echo "usage: $0 <section> [collector args]" >&2; exit 2; }
section=$1; shift
cd "$(dirname "$0")/../.."   # the mechanism repo root
script="gather/collectors/$(echo "$section" | tr - _).py"
[ -f "$script" ] || { echo "no collector $script for section '$section'" >&2; exit 2; }
data="${GE_DATA:-$PWD/data}"   # the data repo (DESIGN.md §7); ledger.py reads GE_DATA too
export GE_DATA="$(cd "$data" && pwd)"
staged="$GE_DATA/ledger/staging/$section-collector.csv"
mkdir -p "$GE_DATA/ledger/staging"
uv run "$script" --out "$staged" "$@"
uv run core/ledger.py merge "$section" --obs "$staged"
