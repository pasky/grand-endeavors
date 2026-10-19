#!/bin/sh
# Regression tests for gather/assess.sh's reader pass (the block between its "reader pass" markers,
# run with stubbed pi_run / pi_mode_model / as_complete).
#   sh core/tests/test_reader.sh
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
ASSESS="$REPO/gather/assess.sh"
FAILS=0
w=$(mktemp -d)
sed -n '/^# --- reader pass/,/^# --- end reader pass ---/p' "$ASSESS" > "$w/block.sh"
R0='{"id": "k", "status": "green", "label": "Ahead: 1.8 h, doubling every 2.9 mo", "rationale": "No new measurements. It rose 42-fold.", "basis": {"p": 2034, "m": 5.67}}'
R1='{"id": "k", "status": "green", "label": "Ahead: 1.8 h, doubling every 2.9 mo", "rationale": "It rose 42-fold by 2034.", "basis": {"p": 2034, "m": 5.67}}'
RS='{"id": "k", "status": "red", "label": "Ahead: 1.8 h, doubling every 2.9 mo", "rationale": "It rose.", "basis": {"p": 2034, "m": 5.67}}'
RV='{"id": "k", "status": "green", "label": "On track: 1.8 h, doubling every 2.9 mo", "rationale": "It rose.", "basis": {"p": 2034, "m": 5.67}}'
RN='{"id": "k", "status": "green", "label": "Ahead: 1.8 h, doubling every 2.9 mo", "rationale": "It rose, ETA 2099.", "basis": {"p": 2034, "m": 5.67}}'
RR='{"id": "k", "status": "green", "label": "Ahead: 1.8 h, doubling every 2.9 mo", "rationale": "It rose 42-fold, about 5.7 a year.", "basis": {"p": 2034, "m": 5.67}}'

# $1 name, $2 expected exit (0|1), $3 expected substring of NOTE, $4 expected records afterwards,
# $5 reader body, $6 fix body (shell snippets; "$out" = the report path; set RC/BLOCK); env: LAB =
# the reader mode's model (default "reader/model"; "assessor/model" = the assessor's), NOTES = expected notes afterwards (default "notes")
t() {
	rm -rf "$w/s"; mkdir -p "$w/s"; printf '%s\n' "$R0" > "$w/s/assessments.jsonl"; echo notes > "$w/s/eta-notes.md"
	(
		set -eu
		STAGE="$w/s"; AS="$STAGE/assessments.jsonl"; NOTES_DIR=n; SECTION=x; RUN_ID=r; ROOT="$REPO"; AGENT_DIR=/nonexistent
		NOTE=""; PI_MODEL="assessor/model"; RD="$5"; FIX="$6"
		pi_mode_model() { [ "${NO_MODE:-}" = "" ] && echo "${LAB:-reader/model}:high"; }
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
		[ "$(cat "$w/s/eta-notes.md")" = "${NOTES:-notes}" ] || ok=""
		[ ! -e "$w/s/reader-draft" ] || ok=""
	fi
	if [ -n "$ok" ]; then echo "ok   $1"; else echo "FAIL $1 (exit $got, note '$(cat "$w/note" 2>/dev/null)')"; FAILS=$((FAILS + 1)); fi
}

E0='printf "all fine: kpi\nEDITS: 0\n" > "$out"'
E1='printf "## kpi\ncut the first sentence\nEDITS: 1\n" > "$out"'
put() { printf 'printf "%%s\\n" '"'"'%s'"'"' > "$AS"' "$1"; }
t "nothing to change: committed as is"                     0 "(reader: 0 edits)"                        "$R0" "$E0" ""
t "a rewording (a number dropped, none new): kept"         0 "(reader: 1 suggested, 1 record(s) reworded)" "$R1" "$E1" "$(put "$R1")"
t "a fix that adopts nothing: counted as 0 reworded"       0 "(reader: 1 suggested, 0 record(s) reworded)" "$R0" "$E1" ""
t "a fix that changes the status: discarded"               0 "fix discarded"                            "$R0" "$E1" "$(put "$RS")"
t "a fix that changes the verdict word: discarded"         0 "fix discarded"                            "$R0" "$E1" "$(put "$RV")"
t "a fix that introduces a number: discarded"              0 "fix discarded"                            "$R0" "$E1" "$(put "$RN")"
t "a fix that misrounds a number (5.67 -> 5.8): discarded" 0 "fix discarded"                            "$R0" "$E1" "$(put "$RR" | sed 's/5[.]7 a/5.8 a/')"
t "a fix that rounds a number (5.67 -> 5.7): kept"          0 "1 record(s) reworded"                     "$RR" "$E1" "$(put "$RR")"
t "a fix that also edits the notes: discarded, restored"   0 "fix discarded"                            "$R0" "$E1" "$(put "$R1"); echo x > \"\$STAGE/eta-notes.md\""
t "a fix that breaks the records: discarded"               0 "fix discarded"                            "$R0" "$E1" 'echo BROKEN > "$AS"'
t "a blocked fix: discarded"                               0 "fix discarded"                            "$R0" "$E1" "$(put "$R1"); BLOCK=1"
t "a reader without the EDITS line: failed, not fatal"     0 "(reader pass failed)"                     "$R0" 'echo prose > "$out"' ""
t "a blocked reader: failed, not fatal"                    0 "(reader pass failed)"                     "$R0" "$E1; BLOCK=1" ""
NO_MODE=1 t "no reader mode: failed, not fatal"            0 "(reader pass failed)"                     "$R0" "$E1" ""
LAB=assessor/model t "only the assessor's own model: skipped, not fatal" 0 "(reader pass failed)"     "$R0" "$E1" ""
t "a reader that edits the records aborts the run"         1 ""                                         ""    "echo x >> \"\$AS\"; $E0" ""
t "a reader that edits the notes aborts the run"           1 ""                                         ""    "echo x >> \"\$STAGE/eta-notes.md\"; $E0" ""

rm -rf "$w"
[ "$FAILS" = 0 ] && echo "0 failure(s)" || { echo "$FAILS failure(s)"; exit 1; }
