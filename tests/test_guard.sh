#!/bin/sh
# Regression tests for the lib.sh write-scope guard (scratch git repo, fake pi).
#   sh tests/test_guard.sh
set -u
LIB="$(cd "$(dirname "$0")/.." && pwd)/lib.sh"
FAILS=0
d=$(mktemp -d)
cd "$d" && git init -q && mkdir -p metrics && printf 'a\nb\n' > metrics/r.csv && echo x > prot.txt \
	&& echo keep > untracked-before.txt && git add metrics prot.txt && git commit -qm init

reset() {
	cd "$d"; git checkout -q -- metrics/r.csv prot.txt; rm -rf stage evil.txt
	echo dirty >> prot.txt; echo keep > untracked-before.txt   # pre-dirty state
}

# $1 name, $2 expected (pass|block), $3 fake pi body, $4 optional APPEND_ONLY_BASE setup
t() {
	reset
	(
		cd "$d"
		sed -n '/^_dirty_hashes()/,$p' "$LIB" > "$d/.lib"
		. "$d/.lib"
		RUN_NAME=t; SESS_DIR="$d/.s"; ALLOWED="stage/ metrics/r.csv"; APPEND_ONLY="metrics/r.csv"
		if [ -n "${4:-}" ]; then eval "$4"; fi
		pi() { eval "$FAKE"; }
		FAKE="$3"; pi_run st p
	) >/dev/null 2>&1 && got=pass || got=block
	if [ "$got" = "$2" ]; then echo "ok   $1"; else echo "FAIL $1 (got $got)"; FAILS=$((FAILS + 1)); fi
}

t "allowed registry append"                pass  'printf "c\n" >> metrics/r.csv'
t "existing registry row edited"           block 'printf "a\nB\n" > metrics/r.csv'
t "allowed staging prefix"                 pass  'mkdir -p stage; echo y > stage/x'
t "already-dirty protected file edited"    block 'echo more >> prot.txt'
t "already-dirty file restored (cleanup)"  block 'git checkout -q -- prot.txt'
t "pre-existing untracked file deleted"    block 'rm -f untracked-before.txt'
t "pi fails after an out-of-scope write"   block 'echo z > evil.txt; return 3'
t "pi fails without writes still fails"    block 'return 3'
# run-start baseline: a later stage may remove an EARLIER stage's addition, but not a baseline row
BASE='mkdir -p "$d/base"; printf "a\nb\n" > "$d/base/metrics_r.csv"; APPEND_ONLY_BASE="$d/base"; printf "c\n" >> metrics/r.csv'
t "verifier removes intake's registry addition" pass 'printf "a\nb\n" > metrics/r.csv' "$BASE"
t "verifier cannot edit a baseline row"          block 'printf "a\n" > metrics/r.csv' "$BASE"

rm -rf "$d"
echo "$FAILS failure(s)"
[ "$FAILS" = 0 ]
