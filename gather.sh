#!/bin/sh
# Grand Endeavors — GATHER: grow the ledger for one section (DESIGN.md §4).
# =============================================================================
# Data gathering runs on its own schedule, independent of bulletins. Each run
# covers a publication window [SINCE, UNTIL] and:
#   1. collect  deterministic collectors (collectors/<section>.py), if any
#   2. intake   one web-capable pi agent per watch item (KPI, every README
#               milestone and challenge, and an open-ended "beyond" sweep) stages
#               candidate events/observations, deduplicated against the ledger
#   3. verify   a FRESH agent re-checks every staged record against its source:
#               verified / corrected / rejected (plus any registry edits)
#   4. merge    ledger.py merge (deterministic, atomic): admitted -> ledger,
#               rejected -> ledger/rejected/
#   5. assess   re-judge milestone/KPI status for targets touched by the run
#               (made_at = UNTIL; evidence must be public by then)
#   6. state    ledger/state/<section>.json records the run (next SINCE)
# Agents never write the ledger directly: they write staging files
# (ledger/staging/, gitignored) and the write-scope guard enforces it.
#
# USAGE:  ./gather.sh <section>
# ENV:    UNTIL=YYYY-MM-DD   window end (default: today, UTC)
#         SINCE=YYYY-MM-DD   window start (default: day after the last run's
#                            UNTIL; else UNTIL - 7 days)
#         ITEMS="kpi milestone:the-bend beyond"   restrict watch items (cost control)
#         SKIP_COLLECT=1     skip deterministic collectors
#         ALLOW_DIRTY=1      skip the clean-worktree preflight
# =============================================================================
SECTION="${1:?usage: gather.sh <section>}"
. "$(dirname "$0")/lib.sh"
require_section "$SECTION"
require_clean

TODAY="$(date -u +%Y-%m-%d)"
UNTIL="${UNTIL:-$TODAY}"
if [ -z "${SINCE:-}" ]; then
	last="$(uv run ledger.py state "$SECTION" --get last_until)"
	if [ -n "$last" ]; then
		SINCE="$(date -u -d "$last + 1 day" +%Y-%m-%d)"
	else
		SINCE="$(date -u -d "$UNTIL - 7 days" +%Y-%m-%d)"
	fi
fi
case "$SINCE$UNTIL" in *[!0-9-]*) echo "ERROR: SINCE/UNTIL must be YYYY-MM-DD" >&2; exit 1 ;; esac
[ "$SINCE" \< "$UNTIL" ] || [ "$SINCE" = "$UNTIL" ] || { echo "ERROR: SINCE $SINCE after UNTIL $UNTIL" >&2; exit 1; }

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_NAME="gather-$SECTION-$RUN_ID"
STAGE="ledger/staging/$SECTION-$RUN_ID"
SESS_DIR="ledger/.sessions"
REGISTRY="metrics/$SECTION.csv"
LEDGER_PATHS="ledger/events/$SECTION.jsonl ledger/observations/$SECTION.csv ledger/assessments/$SECTION.jsonl ledger/rejected/$SECTION.jsonl ledger/state/$SECTION.json $REGISTRY"
ALLOWED="$STAGE/ $REGISTRY"   # agents: staging + (audited) registry additions only
mkdir -p "$STAGE"
echo ">>> [$RUN_NAME] window $SINCE .. $UNTIL, staging $STAGE"
RUN_START="$(git rev-parse HEAD)"

# --- 1. collect (deterministic) -------------------------------------------------
collector="collectors/$(echo "$SECTION" | tr - _).py"
if [ -f "$collector" ] && [ -z "${SKIP_COLLECT:-}" ]; then
	echo ">>> [$RUN_NAME] collect ($collector)"
	sh collectors/run.sh "$SECTION"
	commit "gather $SECTION: collect ($collector, $TODAY)" $LEDGER_PATHS
fi

# --- 2. intake (one agent per watch item) ------------------------------------------
RECENT="$(uv run ledger.py recent "$SECTION" --limit 250)"
REG_TEXT="$(uv run kpi.py registry "$SECTION")"
# Open questions logged by bulletins' edit stage (DESIGN.md §5): input for intake.
GAPS_TEXT="$(cat */gaps/"$SECTION".md 2>/dev/null | grep -E '^[-*] ' | tail -40 || true)"
uv run ledger.py items "$SECTION" > "$STAGE/items.txt"
while IFS='|' read -r topic name desc <&3; do
	if [ -n "${ITEMS:-}" ]; then case " $ITEMS " in *" $topic "*) : ;; *) continue ;; esac; fi
	slug="$(printf '%s' "$topic" | tr ':' '-')"
	ev="$STAGE/$slug.events.jsonl"; ob="$STAGE/$slug.obs.csv"
	pi_run "intake-$slug" "$(cat <<EOF
You are a news-intake researcher for "Grand Endeavors", a live tracker of
humanity's progress. Section "$SECTION", watch item "$topic" ($name):
  $desc
Read ./README.md (the "$SECTION" endeavor) and DESIGN.md §2-3 (ledger time
semantics and the event schema; ledger.py check_event is the validator).

WINDOW: developments whose source was PUBLISHED between $SINCE and $UNTIL
(inclusive). Use your web-search and visit-webpage skills; prefer PRIMARY
sources (agencies, papers, companies, official data) and deep links. VISIT every
source to confirm it states the claim. Stay strictly on this watch item.$( [ "$topic" = beyond ] && printf '\n"beyond" = significant developments for this endeavor that fit NONE of the README milestones/challenges.' )

THE LEDGER ALREADY CONTAINS these $SECTION events (id [kind; topics; verification] claim):
$RECENT

Do NOT re-record anything already there. A genuine status change of a known
thread (delay, retraction, confirmation, update with new numbers) is a NEW event
with "relates": [{"id": <existing id>, "rel": update|retraction|confirmation|delay|followup}].

Metric registry (for optional "metrics" links and observations):
$REG_TEXT

OPEN GAPS reported by recent bulletins (fill them if they concern this item and
the window; otherwise ignore):
${GAPS_TEXT:-(none)}

OUTPUT (write only these files):
1. $ev: one JSON object per line (write via a small python script with
   json.dumps; create the file even if empty). Fields exactly: id
   ("YYYY-MM-DD-slug", date prefix = event date), date, published (YYYY-MM-DD),
   published_basis ("source" if the source states its date, else "seen" =
   today), retrieved ("$TODAY"), kind (achievement|announcement|projection|setback|
   data|analysis|policy|retraction), topics (valid tags: \`uv run ledger.py topics $SECTION\`;
   include "$topic"), claim (ONE self-contained sentence, numbers WITH their exact
   metric scope; distinguish achieved vs announced vs projected), sources
   [{url,title,primary}], significance (1 minor, 2 notable, 3 major; skip trivia),
   optional metrics [{metric,obs,value}], optional relates, verification
   {"status":"unverified","by":"intake:$RUN_ID","at":"$TODAY"},
   collector "gather:$SECTION/$slug@$RUN_ID".
2. OPTIONAL $ob: observations of REGISTERED metrics that the sources report
   (header exactly: $(uv run python -c 'import ledger; print(",".join(ledger.OBS_COLUMNS))')),
   verification "unverified", collector as above, published_basis
   source|rule|seen per DESIGN.md §2. A genuinely new measure needs a new
   row in $REGISTRY with a precise definition (never edit existing rows).
Validate until 0 errors:
    uv run ledger.py lint $SECTION --events $ev $( [ -f "$ob" ] && echo "--obs $ob" )
(if you wrote $ob, add --obs $ob). Finally list what you recorded, and anything
important you saw that was published OUTSIDE the window.
EOF
)"
	[ -f "$ev" ] || : > "$ev"
	lint_obs=""; [ -f "$ob" ] && lint_obs="--obs $ob"
	uv run ledger.py lint "$SECTION" --events "$ev" $lint_obs \
		|| { echo "ERROR: intake $topic staged invalid records ($ev)" >&2; exit 1; }
done 3< "$STAGE/items.txt"

# --- 3. verify (fresh agent) -----------------------------------------------------------
staged_ev="$(find "$STAGE" -name '*.events.jsonl' -size +0 | sort)"
staged_ob="$(find "$STAGE" -name '*.obs.csv' | sort)"
REG_DIFF="$(git diff "$RUN_START" -- "$REGISTRY"; git diff -- "$REGISTRY")"
if [ -n "$staged_ev$staged_ob$REG_DIFF" ]; then
	pi_run verify "$(cat <<EOF
You are an independent VERIFIER for the "$SECTION" ledger. You did not stage any
of this. Staged candidate records from this gather run (window $SINCE..$UNTIL):
$staged_ev $staged_ob
Registry changes in this run (may be empty):
$REG_DIFF

For EVERY staged record: VISIT its source URL(s) and check that the source really
states the claim: the numbers, the metric scope, the event date, the published
date (and basis), the kind (achieved vs announced vs projected), and that it
falls in the window. Check it is not a duplicate of an existing ledger event
(\`uv run ledger.py recent $SECTION\`). Then edit the staged file in place and set
verification to {"status": "verified"|"corrected"|"rejected", "by":
"verify:$RUN_ID", "at": "$TODAY", "note": what you checked, what you corrected,
or why you rejected it}. For observation CSV rows, set the verification column
to verified|corrected|rejected. Corrections must be supported by the source;
otherwise reject. Do not add new records. Every field (numbers, dates, names,
kind) must be stated by a cited source. Background knowledge never counts: an
unsupported detail must be removed or corrected from the source, or the record
rejected.
For registry changes: the definition must be precise and must not duplicate or
rename an existing metric. Existing rows must be unchanged. Revert invalid
additions and reject the rows that use them.
Validate until 0 errors (no "unverified" may remain):
    uv run ledger.py lint $SECTION --events <each events file> [--obs <each obs file>]
Report counts: verified / corrected / rejected (with reasons).
EOF
)"
	if grep -l '"status": *"unverified"' $staged_ev /dev/null >/dev/null 2>&1 \
		|| { [ -n "$staged_ob" ] && grep -q ',unverified,' $staged_ob; }; then
		echo "ERROR: verify left unverified records in $STAGE" >&2; exit 1
	fi
fi

# --- 4. merge (deterministic) -------------------------------------------------------------
for f in $staged_ev; do uv run ledger.py merge "$SECTION" --events "$f"; done
for f in $staged_ob; do uv run ledger.py merge "$SECTION" --obs "$f"; done
uv run ledger.py check "$SECTION"
commit "gather $SECTION: merge verified intake ($SINCE..$UNTIL)" $LEDGER_PATHS

# --- 5. assess --------------------------------------------------------------------------------
TARGETS="$(uv run ledger.py touched "$SECTION" $staged_ev)"
if [ -n "$TARGETS" ]; then
	AS="$STAGE/assessments.jsonl"
	pi_run assess "$(cat <<EOF
Re-assess the status of these "$SECTION" targets as of $UNTIL: $TARGETS
(README.md defines the KPI and milestones.) Evidence = ledger events in
ledger/events/$SECTION.jsonl (legacy ones included) with published <= $UNTIL.
Current assessments are in ledger/assessments/$SECTION.jsonl. Keep the status
unless the evidence justifies a change, and say what changed.
Write $AS: one JSON per line, fields exactly: id "$UNTIL-<target with ':'
replaced by '-'>", target, status green|yellow|red, label (short wording),
made_at "$UNTIL", rationale (2-4 sentences, evidence-grounded, metric scopes
exact), evidence [event ids], by "assess:$RUN_ID". Skip a target whose id
already exists in the assessments file.
Validate until 0 errors:
    uv run ledger.py lint $SECTION --assessments $AS
EOF
)"
	if [ -s "$AS" ]; then
		uv run ledger.py merge "$SECTION" --assessments "$AS"
		commit "gather $SECTION: assess $TARGETS (as of $UNTIL)" $LEDGER_PATHS
	fi
fi

# --- 6. state ------------------------------------------------------------------------------------
n_ev="$(cat $staged_ev /dev/null | grep -c . || true)"
uv run ledger.py state "$SECTION" --record "$(printf '{"run": "%s", "since": "%s", "until": "%s", "items": "%s", "staged_events": %s, "spec_commit": "%s", "pi": "%s"}' \
	"$RUN_ID" "$SINCE" "$UNTIL" "${ITEMS:-all}" "$n_ev" "$RUN_START" "$(pi --version 2>&1 | head -1)")"
uv run ledger.py check "$SECTION"
commit "gather $SECTION: state ($SINCE..$UNTIL, run $RUN_ID)" $LEDGER_PATHS
echo ">>> done: gather $SECTION $SINCE..$UNTIL"
