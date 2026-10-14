#!/bin/sh
# Grand Endeavors — ASSESS: (re)judge KPI/milestone status under RUBRIC.md.
# =============================================================================
# Normally called by gather.sh for targets with new evidence (ledger.py stale).
# Standalone uses: re-assessment after a rubric change, or backfilling statuses.
#
# USAGE:  gather/assess.sh <section>
# ENV:    UNTIL=YYYY-MM-DD   assessment as-of date = made_at (default: today UTC)
#         FORCE=1            assess ALL targets (kpi + milestones), not just stale ones
#         CORRECTION=1       records are rubric corrections (RUBRIC.md rule 4:
#                            once per target per rubric version, no new-evidence claim)
#         DEFCHANGE=<commit> the framework.yaml definition of the targets changed in that
#                            mechanism commit (RUBRIC.md rule 6)
#         ONLY="milestone:x kpi"   restrict to these targets
#         AUDIT=<path>       audit report(s) (a file or a directory, e.g. ledger/audits/<round>/)
#                            whose findings the assessor must address (RUBRIC.md rule 7 (d))
#         ALLOW_DIRTY=1      skip the clean-worktree preflight
# =============================================================================
SECTION="${1:?usage: assess.sh <section>}"
RUBRIC=v5  # current gather/RUBRIC.md version (= ledger.RUBRIC; checked by core/tests/test_paths.py)
. "$(dirname "$0")/../core/lib.sh"
require_section "$SECTION"
require_clean
UNTIL="${UNTIL:-$(date -u +%Y-%m-%d)}"
case "$UNTIL" in *[!0-9-]*) echo "ERROR: UNTIL must be YYYY-MM-DD" >&2; exit 1 ;; esac
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_NAME="assess-$SECTION-$RUN_ID"
STAGE="ledger/staging/assess-$SECTION-$RUN_ID"
SESS_DIR="ledger/.sessions"
NOTES_DIR="ledger/assessments/notes"  # = ledger.NOTES_DIR (checked by core/tests/test_paths.py)
NOTES="$NOTES_DIR/$SECTION/$RUN_ID.md"  # the run's ETA working, committed with its records (by = assess:$RUN_ID[:mode])
ALLOWED="$STAGE/"
mkdir -p "$STAGE"

TARGETS="$(uv run $ROOT/core/ledger.py stale "$SECTION" --until "$UNTIL" $( [ "${FORCE:-}" = 1 ] && echo --force ))"
if [ -n "${ONLY:-}" ]; then  # restrict to the given targets (space-separated)
	TARGETS="$(printf '%s\n' "$TARGETS" | while IFS='|' read -r t id; do
		case " $ONLY " in *" $t "*) echo "$t|$id" ;; esac; done)"
fi
warn_drivers() {  # KNOWN GAP (TODO.md, deferred): cross-section ETA drivers are not tracked by `ledger.py stale`
	uv run $ROOT/core/ledger.py drivers "$SECTION" | while IFS='|' read -r t s m; do
		echo "WARN: $SECTION $t: its ETA rests on $s/$m, but a new $m observation will NOT re-assess it (cross-section staleness is not implemented, TODO.md)" >&2
	done
}
[ -n "$TARGETS" ] || { warn_drivers; echo ">>> [$RUN_NAME] nothing to assess"; exit 0; }
SPEC="$(awk -F, -v s="$SECTION" 'NR==1 || $1==s' metrics/kpi-assessment.csv)"
case "$SPEC" in *"
$SECTION,"*) : ;; *) SPEC="(no KPI spec for $SECTION: do NOT assess its 'kpi' target; skip it)" ;; esac
CORR=""
[ -n "${DEFCHANGE:-}" ] && CORR="The framework.yaml definition of these targets changed in mechanism commit $DEFCHANGE
(see: git -C $ROOT show $DEFCHANGE -- framework.yaml). Set \"definition_change\": \"$DEFCHANGE\"
on every record and judge the evidence against the NEW wording only (RUBRIC.md rule 6)."
[ "${CORRECTION:-}" = 1 ] && CORR="Set \"rubric_correction\": \"$RUBRIC\" on every record: these re-judge the existing
evidence under the new rubric (no new-evidence claim). The change_note must
say what the previous assessment got wrong under RUBRIC.md."
AUD=""
if [ -n "${AUDIT:-}" ]; then
	[ -e "$AUDIT" ] || { echo "ERROR: AUDIT=$AUDIT does not exist" >&2; exit 1; }
	AUD="An audit of the current assessments found problems: read every report in $AUDIT.
Address each finding about your targets, and each rubric-wide or cross-section finding that
applies to them: fix it, or say in the change_note why it does not hold (RUBRIC.md rule 7 (d)).
DEFINITION findings await an owner decision: keep the most natural reading, state it in
basis.path, and model the alternative reading as a sensitivity."
fi
# every registered series, all sections: milestone ETAs may rest on a driver from another section
METRICS="$(for f in metrics/*.csv; do s="$(basename "$f" .csv)"; [ "$s" = kpi-assessment ] && continue
	printf '    %s: %s\n' "$s" "$(awk -F, 'NR>1{printf "%s%s", (n++ ? ", " : ""), $1}' "$f")"; done)"
AS="$STAGE/assessments.jsonl"

prompt() {  # the assess prompt; $BY names the run (and the fallback mode, if used)
cat <<EOF
Assess the status of these "$SECTION" targets as of $UNTIL under the status rubric
in $ROOT/gather/RUBRIC.md (read it fully; it is binding). Targets (target|assessment id to use):
$TARGETS

Inputs:
- $ROOT/framework.yaml: the "$SECTION" KPI and milestone definitions (their literal wording).
- KPI spec (fixed; do not choose your own metric, window or benchmark):
$SPEC
- Evidence: the effective events in ledger/events/$SECTION.jsonl with published <= $UNTIL.
  Records superseded via "supersedes" do not count. Legacy (unverified) records may
  inform context but cannot establish 'achieved'. Observations: use
      uv run $ROOT/core/ledger.py series $SECTION <metric> --as-of $UNTIL
  to compute window statistics exactly (show the numbers in basis.window).
- Previous assessments: ledger/assessments/$SECTION.jsonl (the latest per target
  with made_at <= $UNTIL is "prev"), and prev's working notes $NOTES_DIR/$SECTION/<run id>.md,
  where prev.by is "assess:<run id>" or "assess:<run id>:<mode>". RUBRIC.md rule 7: start
  from prev's model and inputs and update them; do not re-derive the forecast from scratch.
- Other sections, for milestone ETAs (RUBRIC.md §4.1 step 2: a driver trend may live
  elsewhere, e.g. METR task horizons in robots-software): ledger/events/<section>.jsonl,
  and the registered series (same "series <section> <metric>" command):
$METRICS
  Cite such data in basis.eta.calc (metric, values, event ids); the evidence list holds
  only $SECTION event ids.
$CORR
$AUD
Judge each milestone on its OWN quantity as the framework wording defines it (e.g.
total greenhouse-gas emissions, not CO2 alone). If only a proxy has data, name
the proxy and why it tracks the target in basis.path, and let that uncertainty
show in the ETA.
Milestone ETAs: follow RUBRIC.md §4.1 step by step for EACH milestone, from all the data
above, before choosing its status. Do the arithmetic (uv run python is fine) and write
your working per milestone to $STAGE/eta-notes.md, one section per milestone headed
"## milestone:<slug>": the gap, every data point used, the growth model and why, the
time-to-target calculation, the input register with each input's sensitivity (RUBRIC.md
§4.1 step 7: measured / sourced / assumed), the cross-checks (reference class, discounted
proponent dates, prev ETA), the cruxes, and what changed against prev and why (rule 7);
for an achieved or unknown milestone, briefly why. The pipeline commits this file next to
the records as $NOTES, the audit trail of basis.eta: make it self-contained (inline the
numbers, the final version of any script you ran and its output; other staged files are
not kept). Put the result in basis.eta
{p_achieved, p10, p50, p90, method, calc, cruxes} (RUBRIC.md §4.1 step 5: unconditional
quantiles, null past 2100, so a milestone that probably fails has p50 null) and quote the
median in the label ("ETA ~2034"), or without one the chance ("P(by 2100) 20%").
A gap since a series' last point is unmeasured, not flat; and check a faster-reporting series
of the same outcome when the milestone's own series lags (RUBRIC.md §4.1 step 3).
Do not restate a status band ("5-10 years") as an ETA, and do not answer "not estimable"
or ">10 years" for lack of a series: tie the milestone to a driver or a reference class.
Exponential quantities must be extrapolated exponentially.
A milestone with an "assumes:" entry in framework.yaml is judged as if that assumption held
(RUBRIC.md §4.2): the gate never blocks it, basis.eta.assumes repeats it, the label says
"ETA ~YYYY*" (or "P(by 2100) NN%*" without a median), and basis.blockers reports the gate's real state.
If the rubric cannot judge a target (e.g. its KPI series does not cover the
window), write status "unknown" with the label "Unassessed: <reason>" and the
basis keys rule, reason, prev and change_note (evidence may be empty). Never
leave a listed target out.

Write $AS: one JSON object per line with fields exactly: id (EXACTLY as given),
target, status (green|yellow|red, or achieved for milestones), label
("<Verdict>: ..." per RUBRIC.md, at most 100 chars), made_at "$UNTIL", rationale
(2-4 sentences, consistent with basis), evidence [event ids], by
"$BY", rubric "$RUBRIC", basis (the keys $ROOT/DESIGN.md §3 "Assessment" lists for
KPI or milestone targets)$( [ "${CORRECTION:-}" = 1 ] && echo ", rubric_correction \"$RUBRIC\"" ).
Validate until 0 errors:
    uv run $ROOT/core/ledger.py lint $SECTION --assessments $AS
Never run git add/commit (the pipeline commits; a commit by you aborts the run).
Work only in $STAGE: do not read other runs' files under ledger/staging/ or ledger/.sessions/,
and of $NOTES_DIR/ only your targets' prev working (notes are not evidence).
EOF
}
# complete = one record per target with its given id (target|id pairs) AND lint-clean
as_complete() {
	[ -s "$AS" ] || { echo "ERROR: assess wrote no $AS" >&2; return 1; }
	want_ids="$(printf '%s\n' "$TARGETS" | sort)"
	got_ids="$(uv run python -c 'import json,sys; [print(r.get("target"), r.get("id"), sep="|") for r in map(json.loads, filter(str.strip, open(sys.argv[1])))]' "$AS" | sort)" || return 1
	[ "$want_ids" = "$got_ids" ] || { printf 'ERROR: %s target|id pairs differ from the targets:\nwant:\n%s\ngot:\n%s\n' "$AS" "$want_ids" "$got_ids" >&2; return 1; }
	# by names THIS attempt's run (and mode): it is the link to the committed $NOTES
	bad_by="$(uv run python -c 'import json,sys; [print(r.get("target"), r.get("by")) for r in map(json.loads, filter(str.strip, open(sys.argv[1]))) if r.get("by") != sys.argv[2]]' "$AS" "$BY")" || return 1
	[ -z "$bad_by" ] || { printf 'ERROR: %s records with by other than "%s":\n%s\n' "$AS" "$BY" "$bad_by" >&2; return 1; }
	uv run $ROOT/core/ledger.py lint "$SECTION" --assessments "$AS" || { echo "ERROR: $AS does not lint clean" >&2; return 1; }
	case "$TARGETS" in *milestone:*)  # milestone ETAs need their working (RUBRIC.md §4.1), kept as $NOTES
		[ -s "$STAGE/eta-notes.md" ] || { echo "ERROR: assess wrote no $STAGE/eta-notes.md (the ETA working)" >&2; return 1; } ;;
	esac
}
# Provider-side false-positive blocks ("This request was blocked ...") hit some runs at random
# points. Salvage a complete file; otherwise retry fresh once, then once more in the fallback
# mode (ASSESS_FALLBACK_MODE, default "deep", resolved via modes.json). Other failures abort.
FALLBACK_MODE="${ASSESS_FALLBACK_MODE:-deep}"
NOTE=""
attempt=1
while :; do
	BY="assess:$RUN_ID"; PI_MODEL=""
	if [ "$attempt" = 3 ]; then PI_MODEL="$(pi_mode_model "$FALLBACK_MODE")"; BY="assess:$RUN_ID:$FALLBACK_MODE"; fi
	rm -f "$AS" "$STAGE/eta-notes.md"   # a fresh attempt never inherits a half-written file or another attempt's working
	PI_SOFT_FAIL=1
	pi_run "assess-$attempt" "$(prompt)"
	PI_SOFT_FAIL=
	[ "$PI_RC" = 0 ] && break
	[ -n "$PI_BLOCKED" ] && NOTE="$NOTE (attempt $attempt blocked by the provider)"   # recorded whatever follows
	if as_complete 2>/dev/null; then
		echo "WARN: assess agent failed (pi exit $PI_RC) after staging a complete, lint-clean $AS: salvaged" >&2
		NOTE="$NOTE (attempt $attempt salvaged: the agent exited $PI_RC after staging a complete, lint-clean file)"
		break
	fi
	if [ -z "$PI_BLOCKED" ] || [ "$attempt" = 3 ]; then
		echo "ERROR: assess failed (pi exit $PI_RC, attempt $attempt$( [ -n "$PI_BLOCKED" ] && echo ', provider block'))" >&2
		exit 1
	fi
	echo "WARN: assess attempt $attempt blocked by the provider; retrying$( [ "$attempt" = 2 ] && echo " in mode $FALLBACK_MODE")" >&2
	attempt=$((attempt + 1))
done
[ "$attempt" = 3 ] && NOTE="$NOTE (fallback mode $FALLBACK_MODE: $PI_MODEL)"
as_complete || exit 1
for t in $(echo "$TARGETS" | cut -d'|' -f1 | grep '^milestone:' || true); do
	grep -qE "^## $t([^a-z0-9-]|\$)" "$STAGE/eta-notes.md" || echo "WARN: $STAGE/eta-notes.md has no '## $t' section" >&2
done
uv run $ROOT/core/ledger.py merge "$SECTION" --assessments "$AS"
if [ -s "$STAGE/eta-notes.md" ]; then mkdir -p "$NOTES_DIR/$SECTION"; cp "$STAGE/eta-notes.md" "$NOTES"; fi
uv run $ROOT/core/ledger.py check "$SECTION"
commit "assess $SECTION as of $UNTIL$( [ "${CORRECTION:-}" = 1 ] && echo " (rubric $RUBRIC correction)"): $(echo "$TARGETS" | cut -d'|' -f1 | tr '\n' ' ')$NOTE$( [ -n "${AUDIT:-}" ] && echo " (audit: $AUDIT)")" \
	"ledger/assessments/$SECTION.jsonl" "$NOTES"
warn_drivers
echo ">>> done: assess $SECTION as of $UNTIL"
