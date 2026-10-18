#!/bin/sh
# Regression tests for gather/assess.sh's reader pass (the block between its "reader pass" markers,
# run with stubbed pi_run / pi_mode_model / as_complete).
#   sh core/tests/test_reader.sh
set -u
ASSESS="$(cd "$(dirname "$0")/../.." && pwd)/gather/assess.sh"
FAILS=0
w=$(mktemp -d)
sed -n '/^# --- reader pass/,/^# --- end reader pass ---/p' "$ASSESS" > "$w/block.sh"
R0='{"id": "k", "status": "green", "label": "Ahead: x", "rationale": "No new measurements. It rose.", "basis": {}}'
R1='{"id": "k", "status": "green", "label": "Ahead: x", "rationale": "It rose.", "basis": {}}'
R2='{"id": "k", "status": "red", "label": "Stalled: x", "rationale": "It rose.", "basis": {}}'

# $1 name, $2 expected exit (0|1), $3 expected substring of NOTE, $4 expected records afterwards,
# $5 reader body, $6 fix body (shell snippets; "$out" = the report path; set RC/BLOCK)
t() {
	rm -rf "$w/s"; mkdir -p "$w/s"; printf '%s\n' "$R0" > "$w/s/assessments.jsonl"
	(
		set -eu
		STAGE="$w/s"; AS="$STAGE/assessments.jsonl"; NOTES_DIR=n; SECTION=x; RUN_ID=r; ROOT=/r
		NOTE=""; PI_MODEL="assessor/model"; RD="$5"; FIX="$6"
		pi_mode_model() { [ "${NO_MODE:-}" = "" ] && echo "reader/model"; }
		as_complete() { ! grep -q BROKEN "$AS"; }
		pi_run() {
			RC=0; BLOCK=""; out="$STAGE/reader.md"
			case "$1" in reader) eval "$RD" ;; reader-fix) eval "$FIX" ;; esac
			PI_RC=$RC; PI_BLOCKED=$BLOCK
		}
		. "$w/block.sh"
		reader_pass 2>/dev/null
		echo "$NOTE" > "$w/note"
		[ "$PI_MODEL" = "assessor/model" ] || echo "model not restored: $PI_MODEL" >> "$w/note"
	) >/dev/null 2>&1; got=$?
	[ "$got" = 0 ] || got=1
	ok=1
	[ "$got" = "$2" ] || ok=""
	if [ "$2" = 0 ]; then
		case "$(cat "$w/note")" in *"$3"*) : ;; *) ok="" ;; esac
		case "$(cat "$w/note")" in *"not restored"*) ok="" ;; esac
		[ "$(cat "$w/s/assessments.jsonl")" = "$4" ] || ok=""
		[ ! -e "$w/s/assessments.jsonl.draft" ] || ok=""
	fi
	if [ -n "$ok" ]; then echo "ok   $1"; else echo "FAIL $1 (exit $got, note '$(cat "$w/note" 2>/dev/null)')"; FAILS=$((FAILS + 1)); fi
}

E0='printf "all fine: kpi\nEDITS: 0\n" > "$out"'
E1='printf "## kpi\ncut the first sentence\nEDITS: 1\n" > "$out"'
TEXT='printf "%s\n" "$R1" > "$AS"'
MORE='printf "%s\n" "$R2" > "$AS"'
t "nothing to change: committed as is"                    0 "(reader: 0 edits)"            "$R0" "$E0" ""
t "a rewording: label/rationale only, kept"               0 "(reader: 1 record(s) reworded)" "$R1" "$E1" "$TEXT"
t "a fix that changes the status: discarded"              0 "fix discarded"                "$R0" "$E1" "$MORE"
t "a fix that breaks the records: discarded"              0 "fix discarded"                "$R0" "$E1" 'echo BROKEN > "$AS"'
t "a blocked fix: discarded"                              0 "fix discarded"                "$R0" "$E1" "$TEXT; BLOCK=1"
t "a reader without the EDITS line: failed, not fatal"    0 "(reader pass failed)"         "$R0" 'echo prose > "$out"' ""
t "a blocked reader: failed, not fatal"                   0 "(reader pass failed)"         "$R0" "$E1; BLOCK=1" ""
NO_MODE=1 t "unknown reader mode: failed, not fatal"      0 "(reader pass failed)"         "$R0" "$E1" ""
t "a reader that edits the records aborts the run"        1 ""                             ""    "echo x >> \"\$AS\"; $E0" ""

rm -rf "$w"
[ "$FAILS" = 0 ] && echo "0 failure(s)" || { echo "$FAILS failure(s)"; exit 1; }
