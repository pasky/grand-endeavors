#!/bin/sh
# Regression tests for gather/editorial.sh, end to end on a scratch clone of the data repo with a
# stub `pi` (the editor and fact-check stages are shell snippets).
#   sh core/tests/test_editorial.sh      (needs the data repo; no network)
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DATA="${GE_DATA:-$REPO/data}"
FAILS=0
w=$(mktemp -d)
git clone -q "$DATA" "$w/data0" || { echo "FAIL cannot clone $DATA"; exit 1; }
git -C "$w/data0" config user.email t@t; git -C "$w/data0" config user.name t
mkdir -p "$w/agent" "$w/bin"
echo '{"defaultProvider": "a", "defaultModel": "assessor"}' > "$w/agent/settings.json"
echo '{"modes": {"edtest": {"provider": "e", "modelId": "editor"}, "astest": {"provider": "a", "modelId": "assessor"}}}' > "$w/agent/modes.json"
# stub pi: the stage is the --name suffix; it runs $EDIT or $CHECK with $S = the staging dir
cat > "$w/bin/pi" <<'EOF'
#!/bin/sh
name=""; while [ $# -gt 0 ]; do [ "$1" = --name ] && name="$2"; shift; done
S="$(grep -o 'ledger/staging/editorial-[0-9TZ]*' | head -1)"
case "$name" in *-edit|*-revise) eval "$EDIT" ;; *-check|*-check-2) eval "$CHECK" ;; esac
EOF
chmod +x "$w/bin/pi"
cur() {  # $1 section: the current KPI record's field $2
	(cd "$w/data" && uv run --no-project python -c 'import json, sys
r = [json.loads(l) for l in open(f"ledger/assessments/{sys.argv[1]}.jsonl") if l.strip()]
k = sorted((x for x in r if x["target"] == "kpi"), key=lambda x: x["made_at"])[-1]
print(k.get(sys.argv[2]))' "$1" "$2")
}
# the robots-software KPI record (its id, the current label) as the stub editor sees it
RID="$(cd "$w/data0" && uv run --no-project python -c 'import json
r = [json.loads(l) for l in open("ledger/assessments/robots-software.jsonl") if l.strip()]
print(sorted((x for x in r if x["target"] == "kpi"), key=lambda x: x["made_at"])[-1]["id"])')"
LAB="$(cd "$w/data0" && uv run --no-project python -c 'import json
r = [json.loads(l) for l in open("ledger/assessments/robots-software.jsonl") if l.strip()]
print(sorted((x for x in r if x["target"] == "kpi"), key=lambda x: x["made_at"])[-1]["label"])')"
PROP="{\"section\": \"robots-software\", \"id\": \"$RID\", \"label\": \"$LAB\", \"rationale\": \"Plainer.\", \"why\": \"w\"}"

# $1 name, $2 expected exit (0|1), $3 expected robots-software rationale afterwards, $4 EDIT, $5 CHECK;
# env MODE = EDITORIAL_MODE (default edtest), RERUN=1 runs the pass twice (the second must be a no-op)
t() {
	rm -rf "$w/data"; git clone -q "$w/data0" "$w/data"
	git -C "$w/data" config user.email t@t; git -C "$w/data" config user.name t
	run() { env PATH="$w/bin:$PATH" GE_DATA="$w/data" PI_CODING_AGENT_DIR="$w/agent" EDITORIAL_MODE="${MODE:-edtest}" \
		SITE=0 ALLOW_DIRTY=1 FORCE="${FORCE-1}" EDIT="$1" CHECK="$2" sh "$REPO/gather/editorial.sh" >"$w/log" 2>&1; }
	run "$4" "$5"; got=$?
	[ "$got" = 0 ] || got=1
	ok=1
	[ "$got" = "$2" ] || ok=""
	[ "$(cur robots-software rationale)" = "$3" ] || ok=""
	[ "$2" = 1 ] || [ -z "$(git -C "$w/data" status --porcelain)" ] || ok=""
	if [ -n "${RERUN:-}" ]; then
		head="$(git -C "$w/data" rev-parse HEAD)"
		FORCE= run "$4" "$5" || ok=""
		[ "$(git -C "$w/data" rev-parse HEAD)" = "$head" ] || ok=""
	fi
	if [ -n "$ok" ]; then echo "ok   $1"; else echo "FAIL $1 (exit $got)"; sed 's/^/     /' "$w/log" | tail -5; FAILS=$((FAILS + 1)); fi
}
ORIG="$(cd "$w/data0" && uv run --no-project python -c 'import json
r = [json.loads(l) for l in open("ledger/assessments/robots-software.jsonl") if l.strip()]
print(sorted((x for x in r if x["target"] == "kpi"), key=lambda x: x["made_at"])[-1]["rationale"])')"
E0='echo "EDITS: 0" > "$S/editorial.md"'
E1="printf '%s\n' '$PROP' > \"\$S/proposals.jsonl\"; echo 'EDITS: 1' > \"\$S/editorial.md\""
A='echo "ACCEPT robots-software" > "$S/factcheck.md"'
R='echo "REJECT robots-software: wrong" > "$S/factcheck.md"'
RERUN=1 t "no proposals: report committed, nothing reworded, then nothing unread" 0 "$ORIG" "$E0" ""
RERUN=1 t "an accepted proposal: appended as the current record, then nothing unread" 0 "Plainer." "$E1" "$A"
t "a rejected proposal, given up in revision: nothing reworded" 0 "$ORIG"   "$E1" "$R"
# the revision (proposals-2.jsonl) for the rejected section, accepted by the second check
REV="$(printf '%s' "$PROP" | sed 's/Plainer[.]/Revised./')"
E1R="$E1; [ ! -e \"\$S/factcheck.md\" ] || printf '%s\n' '$REV' > \"\$S/proposals-2.jsonl\""
CK2='if [ -e "$S/proposals-2.jsonl" ]; then echo "ACCEPT robots-software" > "$S/factcheck-2.md"; else echo "REJECT robots-software: wrong" > "$S/factcheck.md"; fi'
t "a rejected proposal, revised and accepted: the revision is appended" 0 "Revised." "$E1R" "$CK2"
t "a proposal with a new number: dropped mechanically"        0 "$ORIG"     "$(echo "$E1" | sed 's/Plainer[.]/Plainer, 987654./')" "$A"
t "EDITS disagrees with proposals.jsonl: fails, nothing merged" 1 "$ORIG"   "$(echo "$E1" | sed 's/EDITS: 1/EDITS: 2/')" "$A"
# a valid copy of the current record, planted where the pipeline once wrote its own copies
PLANT='mkdir -p "$S/out"; uv run --no-project python -c "import json, sys
r = json.loads(open(sys.argv[1]).readline())[\"record\"]
print(json.dumps(r | {\"id\": r[\"id\"] + \"-x\", \"rationale\": \"Hijacked.\"}))" "$S/current.jsonl" > "$S/out/robots-software.jsonl"'
t "agent-written copies in staging are never merged"          0 "$ORIG"     "$PLANT; $E0" ""
t "a fact check that edits the proposals: fails"              1 "$ORIG"     "$E1" "$A; echo x >> \"\$S/proposals.jsonl\""
MODE=astest t "an editor mode on the assessor's model: refused" 1 "$ORIG"   "$E1" "$A"

rm -rf "$w"
[ "$FAILS" = 0 ] && echo "0 failure(s)" || { echo "$FAILS failure(s)"; exit 1; }
