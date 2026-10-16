#!/bin/sh
# Regression tests for gather/assess.sh's review stage (the block between its "review stage"
# markers, run with stubbed pi_run / pi_mode_model / as_complete / prompt).
#   sh core/tests/test_review.sh
set -u
ASSESS="$(cd "$(dirname "$0")/../.." && pwd)/gather/assess.sh"
FAILS=0
w=$(mktemp -d)
sed -n '/^# --- review stage/,/^# --- end review stage ---/p' "$ASSESS" > "$w/block.sh"

# $1 name, $2 expected exit (0|1), $3 expected "MAJOR ..." lines of review.md's "# Remaining" block,
# joined by "|" ("" = no file; targets: milestone:a, milestone:b and the unreviewed kpi),
# $4 expected substring of NOTE, $5 expected records content afterwards, then stage bodies:
# $6 review-1, $7 fix, $8 review-2 (shell snippets; "$rev" = the report path; set RC/BLOCK),
# optional $9: one more milestone target
t() {
	rm -rf "$w/s"; mkdir -p "$w/s"; echo draft > "$w/s/assessments.jsonl"; echo notes > "$w/s/eta-notes.md"
	(
		set -eu
		STAGE="$w/s"; AS="$STAGE/assessments.jsonl"; NOTES_DIR=n; SECTION=x; RUN_ID=r; UNTIL=2026-01-01; ROOT=/r
		TARGETS="$(printf 'milestone:b|b1\nkpi|k1\nmilestone:a|a1')${9:+
$9|x1}"
		NOTE=""; PI_MODEL="assessor/model"; R1="$6"; FIX="$7"; R2="$8"
		pi_mode_model() { [ "${NO_MODE:-}" = "" ] && echo "reviewer/model"; }
		prompt() { echo base; }
		as_complete() { ! grep -q BROKEN "$AS"; }
		pi_run() {
			RC=0; BLOCK=""; rev="$STAGE/$1.md"
			case "$1" in review-1) eval "$R1" ;; fix) eval "$FIX" ;; review-2) eval "$R2" ;; esac
			PI_RC=$RC; PI_BLOCKED=$BLOCK
		}
		. "$w/block.sh"
		review_stage 2>/dev/null
		echo "$NOTE" > "$w/note"
		[ "$PI_MODEL" = "assessor/model" ] || echo "model not restored: $PI_MODEL" >> "$w/note"
	) >/dev/null 2>&1; got=$?   # not "&& ... ||": that would disable set -e inside the subshell
	[ "$got" = 0 ] || got=1
	fin="$(sed -n '/^# Remaining$/,$p' "$w/s/review.md" 2>/dev/null | grep '^MAJOR' | paste -sd'|')"
	ok=1
	[ "$got" = "$2" ] || ok=""
	if [ "$2" = 0 ]; then
		[ "$fin" = "$3" ] || ok=""
		[ -z "$3" ] || [ "$(tail -n 1 "$w/s/review.md")" = "${3##*|}" ] || ok=""   # the total stays the LAST line
		case "$(cat "$w/note")" in *"$4"*) : ;; *) ok="" ;; esac
		case "$(cat "$w/note")" in *"not restored"*) ok="" ;; esac
		[ "$(cat "$w/s/assessments.jsonl")" = "$5" ] || ok=""
		[ ! -e "$w/s/assessments.jsonl.draft" ] || ok=""
	fi
	if [ -n "$ok" ]; then echo "ok   $1"; else echo "FAIL $1 (exit $got, final '$fin', note '$(cat "$w/note" 2>/dev/null)')"; FAILS=$((FAILS + 1)); fi
}

M0='printf "fine\nMAJOR milestone:a: 0\nMAJOR milestone:b: 0\nMAJOR: 0\n" > "$rev"'
M2='printf "two bad\nMAJOR milestone:b: 2\n\nMAJOR milestone:a: 0\nMAJOR: 2\n" > "$rev"'   # any order, blank lines
M1='printf "x\nMAJOR milestone:a: 1\nMAJOR milestone:b: 0\nMAJOR: 1\n" > "$rev"'
F0="MAJOR milestone:a: 0|MAJOR milestone:b: 0|MAJOR: 0"
F2="MAJOR milestone:a: 0|MAJOR milestone:b: 2|MAJOR: 2"
F1="MAJOR milestone:a: 1|MAJOR milestone:b: 0|MAJOR: 1"
FIXED='echo fixed > "$AS"'
t "clean review: committed with 0 left"              0 "$F0" "(review: 0 MAJOR)"                  draft "$M0" "" ""
t "MAJOR, fix, clean re-review"                      0 "$F0" "(review: 2 MAJOR, 0 after one fix)" fixed "$M2" "$FIXED" "$M0"
t "MAJOR, fix, re-review still finds one"            0 "$F1" "(review: 2 MAJOR, 1 after one fix)" fixed "$M2" "$FIXED" "$M1"
t "fix blocked by the provider: draft restored"      0 "$F2" "fix failed"                         draft "$M2" "$FIXED; BLOCK=1" ""
t "fix exits nonzero: draft restored"                0 "$F2" "fix failed"                         draft "$M2" "$FIXED; RC=1" ""
t "fix leaves broken records: draft restored"        0 "$F2" "fix failed"                         draft "$M2" 'echo BROKEN > "$AS"' ""
t "re-review fails: the fix stays, round 1's counts" 0 "$F2" "re-review failed"                   fixed "$M2" "$FIXED" "$M0; RC=1"
t "blocked round-1 review: noted, no review file"    0 ""    "(review failed)"                    draft "$M0; BLOCK=1" "" ""
t "review without a MAJOR line: failed, not fatal"   0 ""    "(review failed)"                    draft 'echo prose > "$rev"' "" ""
NO_MODE=1 t "unknown review mode: failed, not fatal" 0 ""    "(review failed)"                    draft "$M0" "" ""
t "a reviewer that edits the records aborts the run" 1 ""    ""                                   ""    'echo x >> "$AS"; '"$M0" "" ""
t "no per-target lines: the total only"              0 "MAJOR: 0" "(review: 0 MAJOR)"             draft 'printf "x\nMAJOR: 0\n" > "$rev"' "" ""
t "a target missing: the total only"                 0 "MAJOR: 2" "fix failed"                    draft 'printf "x\nMAJOR milestone:b: 2\nMAJOR: 2\n" > "$rev"' "RC=1" ""
t "a kpi line is not a milestone target: total only" 0 "MAJOR: 0" "(review: 0 MAJOR)"             draft 'printf "x\nMAJOR kpi: 0\nMAJOR milestone:a: 0\nMAJOR milestone:b: 0\nMAJOR: 0\n" > "$rev"' "" ""
t "per-target lines not summing to the total: total" 0 "MAJOR: 2" "fix failed"                    draft 'printf "x\nMAJOR milestone:a: 1\nMAJOR milestone:b: 0\nMAJOR: 2\n" > "$rev"' "RC=1" ""
LC_ALL=en_US.UTF-8 t "prefix slugs sort alike in any locale; 0-padded" 0 "MAJOR milestone:a: 2|MAJOR milestone:a-1: 0|MAJOR milestone:b: 0|MAJOR: 2" "fix failed" \
	draft 'printf "x\nMAJOR milestone:b: 0\nMAJOR milestone:a-1: 00\nMAJOR milestone:a: 02\nMAJOR: 02\n" > "$rev"' "RC=1" "" "milestone:a-1"
t "a duplicated target: the total only"              0 "MAJOR: 0" "(review: 0 MAJOR)"             draft 'printf "x\nMAJOR milestone:a: 0\nMAJOR milestone:a: 0\nMAJOR milestone:b: 0\nMAJOR: 0\n" > "$rev"' "" ""
t "accepted re-review without valid lines: its total, not round 1's lines" \
                                                     0 "MAJOR: 1" "(review: 2 MAJOR, 1 after one fix)" fixed "$M2" "$FIXED" 'printf "x\nMAJOR: 1\n" > "$rev"'

rm -rf "$w"
echo "$FAILS failure(s)"
[ "$FAILS" = 0 ]
