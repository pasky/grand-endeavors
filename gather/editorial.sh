#!/bin/sh
# Grand Endeavors — EDITORIAL: every section's current KPI label and rationale, read side by side
# as the dashboard's reader would (DESIGN.md §4b).
# =============================================================================
# The per-run reader pass (assess.sh) sees one section's records at a time and may only polish
# them. This pass reads all the KPI texts together, so it catches what only shows in comparison
# (one KPI explains its status rule while another states facts; a caveat one keeps, another drops),
# and it may restructure a text completely under RUBRIC.md §6.
#   1. collect   the current judged KPI assessment of every section (editorial.py collect)
#   2. edit      an editor on another model than the assessor's (EDITORIAL_MODE, default best;
#                oracle when best is the assessor's own model) writes a report and proposals;
#                it edits nothing else
#   3. check     a fact check on the assessor's model accepts or rejects each proposal against
#                the full record (basis included); it edits nothing
#   4. apply     accepted proposals that pass core/textcheck.py (label/rationale only, verdict
#                word kept, every number from the record as is or rounded) are appended as copies
#                of the current record (same status, made_at, evidence and basis; by
#                editorial:<run id>), merged and committed with the report
#                ledger/assessments/notes/editorial/<run id>.md
# gather.sh runs it after every gather (EDITORIAL=0 skips); it exits at once unless some current KPI
# text is unread by an earlier pass. FORCE=1 re-reads (e.g. after a RUBRIC.md §6 change). Never
# touches milestones or a status.
#
# USAGE:  gather/editorial.sh
# ENV:    FORCE=1          run even when every current KPI text was read by an earlier pass
#         EDITORIAL_MODE   the editor's pi mode (default: best, else oracle; never the assessor's model)
#         ALLOW_DIRTY=1    skip the clean-worktree preflight
# =============================================================================
. "$(dirname "$0")/../core/lib.sh"
require_clean
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
TODAY="$(date -u +%Y-%m-%d)"
RUN_NAME="editorial-$RUN_ID"
STAGE="ledger/staging/editorial-$RUN_ID"
SESS_DIR="ledger/.sessions"
NOTES_DIR="ledger/assessments/notes"
REPORT="$NOTES_DIR/editorial/$RUN_ID.md"
ALLOWED="$STAGE/"
mkdir -p "$STAGE"

# a pass reads every current KPI text, but runs only when one of them is unread: new since the last
# pass (each report's "Read:" line lists what it read, its own rewordings included)
unread="$(uv run $ROOT/gather/editorial.py collect "$STAGE/current.jsonl" "$NOTES_DIR/editorial")"
if ! grep -q . "$STAGE/current.jsonl"; then echo ">>> [$RUN_NAME] no judged KPI assessment to read"; exit 0; fi
if [ "$unread" = 0 ] && [ "${FORCE:-}" != 1 ]; then echo ">>> [$RUN_NAME] every current KPI text was read by an earlier pass (FORCE=1 reads them again)"; exit 0; fi

# the editor runs on another model than the assessor (pi's default model, which assess.sh uses)
amodel="$(python3 -c 'import json, sys
s = json.load(open(sys.argv[1]))
print(s.get("defaultProvider", "?") + "/" + s.get("defaultModel", "?"))' "$AGENT_DIR/settings.json" 2>/dev/null || echo "?/?")"
EMODE="${EDITORIAL_MODE:-}"
if [ -z "$EMODE" ]; then
	for m in best oracle; do
		if mm="$(pi_mode_model "$m" 2>/dev/null)" && [ "${mm%%:*}" != "$amodel" ]; then EMODE="$m"; break; fi
	done
fi
[ -n "$EMODE" ] || { echo "ERROR: no pi mode (best, oracle) on a model other than the assessor's ($amodel); set EDITORIAL_MODE" >&2; exit 1; }

sums() { for f in "$STAGE"/*; do [ -f "$f" ] && cksum "$f"; done; true; }
before="$(sums)"
PI_MODEL="$(pi_mode_model "$EMODE")"
pi_run edit "$(cat <<EOF
You are the editor of a public dashboard that tracks humanity's great endeavors (AI, robots,
rockets, fusion, health, climate, ...). Each endeavor shows a KPI: its name and definition, a
status label, and, always visible under it, a rationale. Read every current KPI label and rationale
side by side, as the dashboard's reader: smart and technical, not a specialist, who sees only the
KPI's name and definition above the text (the numbers' derivation, the basis, is folded away).
Input: $STAGE/current.jsonl, one line per section: {section, kpi (the name and definition shown),
record (the assessment: status, label, rationale, and the basis the text must stay consistent with)}.
Writing rules: $ROOT/gather/RUBRIC.md §6 (label, rationale); read them first. The dashboard's
folded explainers are in $ROOT/framework.yaml (each section's kpi_about), for your understanding only.

For each section ask, as an editor rather than a copy editor: does the text tell this reader what
the level means in the world, how fast it moves, and why that earns its status? Would they miss each
sentence if it were gone? Then compare the sections: the same kind of judgment (against an outside
need, against the KPI's own earlier pace) should read the same way; a habit that is fine in one and
noise in another (a caveat that dismisses itself, a description of the status rule, rubric words,
ledger history, false precision, a level the reader cannot picture) shows up best side by side.
Propose a new label and/or rationale wherever the reader would be better served; restructure freely.
Hard limits (proposals breaking them are dropped mechanically): keep the status and the label's
verdict word (the text before its first colon); label at most 100 characters; every number must
occur in the record (basis included), as is or rounded to fewer decimals (7.9 -> 8, 1.79 -> 1.8; a
share 0.96 may read 96%), never a figure computed from them (a ratio, a conversion); nothing the
basis does not support (no new facts, no stronger claims). Dropping numbers is fine.

Write two files, and modify nothing else:
1. $STAGE/proposals.jsonl: one JSON object per line per section you would change:
   {"section": ..., "id": <the record's id>, "label": <full new label>, "rationale": <full new
   rationale>, "why": <one line>} (repeat the current label or rationale when you keep it).
2. $STAGE/editorial.md: per section, "## <section>", what each sentence of the current text tells
   the reader and your verdict; then "## Across sections", the patterns you saw. Its LAST line must
   be exactly "EDITS: <the number of lines in proposals.jsonl>".
Never run git add/commit.
EOF
)"
PI_MODEL=""
edits="$(tail -n 1 "$STAGE/editorial.md" 2>/dev/null | sed -n 's/^EDITS: 0*\([0-9][0-9]*\)$/\1/p')"
[ -n "$edits" ] || { echo "ERROR: the editor wrote no $STAGE/editorial.md ending 'EDITS: <n>'" >&2; exit 1; }
[ -f "$STAGE/proposals.jsonl" ] || : > "$STAGE/proposals.jsonl"
[ "$(grep -c . "$STAGE/proposals.jsonl" || true)" = "$edits" ] \
	|| { echo "ERROR: EDITS: $edits, but $STAGE/proposals.jsonl has $(grep -c . "$STAGE/proposals.jsonl" || true) line(s)" >&2; exit 1; }
[ "$(printf '%s\n' "$before" | grep " $STAGE/current.jsonl\$")" = "$(sums | grep " $STAGE/current.jsonl\$")" ] \
	|| { echo "ERROR: the editor modified $STAGE/current.jsonl" >&2; exit 1; }

OUTCOME=""
if [ "$edits" != 0 ]; then
	before="$(sums)"
	pi_run check "$(cat <<EOF
Fact-check proposed rewordings of public dashboard texts. $STAGE/current.jsonl holds, per section,
the current KPI assessment record (status, label, rationale, basis: the data and the judgment);
$STAGE/proposals.jsonl proposes a new label and rationale for some of them ($STAGE/editorial.md
says why). For each proposal, compare it with the full record: does every statement follow from
the record (basis included)? Does each number keep its meaning (the right quantity, period, unit)?
Does it claim more than the basis supports (e.g. "accelerating" when the basis finds the halves'
paces within noise of each other)? Does it still give the reader the level, the pace and why it
has its status, and keep any caveat that could change what the reader takes away ($ROOT/gather/RUBRIC.md
§6)? Wording taste is not your call: reject only for a fact, a meaning, a missing essential, or a
§6 violation.
Write $STAGE/factcheck.md: per proposal a short paragraph, then a line exactly "ACCEPT <section>" or
"REJECT <section>: <reason>". Modify no other file; never run git add/commit.
EOF
)"
	[ "$(printf '%s\n' "$before" | grep -v " $STAGE/factcheck.md\$")" = "$(sums | grep -v " $STAGE/factcheck.md\$")" ] \
		|| { echo "ERROR: the fact check modified the staged files" >&2; exit 1; }
	[ -s "$STAGE/factcheck.md" ] || { echo "ERROR: the fact check wrote no $STAGE/factcheck.md" >&2; exit 1; }
	OUTCOME="$(uv run $ROOT/gather/editorial.py apply "$STAGE" "$RUN_ID" "$TODAY")"
	echo "$OUTCOME"
fi

reworded=""
for f in "$STAGE"/out/*.jsonl; do
	[ -f "$f" ] || continue
	s="$(basename "$f" .jsonl)"
	uv run $ROOT/core/ledger.py merge "$s" --assessments "$f"
	uv run $ROOT/core/ledger.py check "$s"
	reworded="$reworded $s"
done
mkdir -p "$NOTES_DIR/editorial"
{
	echo "# Editorial pass $RUN_ID ($TODAY): the current KPI labels and rationales, side by side"
	echo
	echo "Editor: $EMODE ($(pi_mode_model "$EMODE")); fact check: the assessor's model ($amodel)."
	echo
	# what this pass read (for the next pass's unread test): the current records and its rewordings
	echo "Read: $(uv run python -c 'import json, sys
print(" ".join(r["section"] + ":" + r["record"]["id"] for r in map(json.loads, filter(str.strip, open(sys.argv[1])))))' "$STAGE/current.jsonl")$(printf '%s\n' "$OUTCOME" | sed -n 's/^REWORD \([a-z-]*\): .* -> \(.*\)$/ \1:\2/p' | tr -d '\n')"
	echo
	echo "## Outcome"
	echo
	if [ -n "$OUTCOME" ]; then printf '%s\n' "$OUTCOME" | sed 's/^/- /'; else echo "- no proposals"; fi
	echo
	echo "# Editor's report"
	echo
	cat "$STAGE/editorial.md"
	if [ -s "$STAGE/proposals.jsonl" ]; then
		echo; echo "# Proposals"; echo
		sed 's/^/    /' "$STAGE/proposals.jsonl"
	fi
	if [ -s "$STAGE/factcheck.md" ]; then echo; echo "# Fact check"; echo; cat "$STAGE/factcheck.md"; fi
} > "$REPORT"
paths="$REPORT"
for s in $reworded; do paths="$paths ledger/assessments/$s.jsonl"; done
commit "editorial pass $RUN_ID: KPI labels and rationales side by side (${edits} proposed; reworded:${reworded:- none})" $paths
if [ -n "$reworded" ]; then  # the published site, $ROOT/build/ (derived; best effort, as in gather.sh)
	uv run $ROOT/views/explore.py site >/dev/null || echo "WARN: site refresh failed (see above); the ledger is fine" >&2
fi
echo ">>> done: editorial pass $RUN_ID"
