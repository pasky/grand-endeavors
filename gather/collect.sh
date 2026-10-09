#!/bin/sh
# Grand Endeavors — COLLECT: the scheduled, LLM-free part of gathering (DESIGN.md §4a).
# =============================================================================
# For every section with a deterministic collector (gather/collectors/<section>.py):
# run it and merge into the ledger (gather/collectors/run.sh), check the section,
# and commit its observations. Then refresh the published site (build/ in the checkout) and
# push the data repo. A failing section does not stop the others; the script
# exits non-zero if anything failed, so the systemd unit shows up as failed.
# Run daily by gather/systemd/grand-endeavors-collect.timer (setup: DESIGN.md §4a).
#
# USAGE:  gather/collect.sh [section...]   (default: every section with a collector)
# ENV:    NO_PUSH=1   do not push the data repo (and allow a branch other than main)
# =============================================================================
. "$(dirname "$0")/../core/lib.sh"   # set -eu, cwd = the data repo ($D)
TODAY="$(date -u +%Y-%m-%d)"

if [ -z "${NO_PUSH:-}" ] && [ "$(git symbolic-ref --short -q HEAD || true)" != main ]; then
	echo "ERROR: data repo $D is not on main (set NO_PUSH=1 to collect without pushing)" >&2
	exit 1
fi
# commits are path-scoped, but a dirty observations file would be swept into ours
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
	echo "ERROR: data repo $D has uncommitted changes; not collecting" >&2
	git status --short --untracked-files=no >&2
	exit 1
fi

if [ $# -eq 0 ]; then
	for s in $SECTIONS; do
		[ -f "$ROOT/gather/collectors/$(echo "$s" | tr - _).py" ] && set -- "$@" "$s"
	done
fi

failed=""
for s in "$@"; do
	require_section "$s"
	echo ">>> collect $s"
	if sh "$ROOT/gather/collectors/run.sh" "$s" && uv run "$ROOT/core/ledger.py" check "$s"; then
		commit "collect $s ($TODAY)" "ledger/observations/$s.csv"
	else
		echo "ERROR: collect $s failed (see above)" >&2
		failed="$failed $s"
	fi
done

echo ">>> site"
uv run "$ROOT/views/explore.py" site >/dev/null || failed="$failed site"
if [ -z "${NO_PUSH:-}" ]; then
	echo ">>> push data"
	git push -q origin main || failed="$failed push"
fi

if [ -n "$failed" ]; then
	echo "FAILED:$failed" >&2
	exit 1
fi
echo ">>> done: collect $* ($TODAY)"
