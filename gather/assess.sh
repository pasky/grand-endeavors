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
#         AUDIT=<audit id>   the ETA audit in ledger/audits/<audit id>/ whose findings the assessor
#                            must address; records set audit_correction (RUBRIC.md rules 7, 8).
#                            Usually with FORCE=1 ONLY="<milestones>" (the audited targets are not stale)
#         REVIEW=0           skip the review stage (default: on when milestones are assessed)
#         ASSESS_REVIEW_MODE the reviewer's pi mode (default deep)
#         ALLOW_DIRTY=1      skip the clean-worktree preflight
# =============================================================================
SECTION="${1:?usage: assess.sh <section>}"
RUBRIC=v6  # current gather/RUBRIC.md version (= ledger.RUBRIC; checked by core/tests/test_paths.py)
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
	[ -d "ledger/audits/$AUDIT" ] || { echo "ERROR: AUDIT=$AUDIT: no directory ledger/audits/$AUDIT" >&2; exit 1; }
	AUD="An audit of the current assessments found problems: read every report in ledger/audits/$AUDIT/.
Address each finding about your targets, and each rubric-wide or cross-section finding that
applies to them: fix it, or say in the change_note which findings you fixed and why any other
does not hold (RUBRIC.md rules 7 (d) and 8). Set \"audit_correction\": \"$AUDIT\" on every record.
DEFINITION findings await an owner decision: keep the most natural reading, state it in
basis.path, and model the alternative reading as a sensitivity."
fi
# every registered series, all sections: milestone ETAs may rest on a driver from another section
METRICS="$(for f in metrics/*.csv; do s="$(basename "$f" .csv)"; [ "$s" = kpi-assessment ] && continue
	printf '    %s: %s\n' "$s" "$(awk -F, 'NR>1{printf "%s%s", (n++ ? ", " : ""), $1}' "$f")"; done)"
# shared ETA drivers (data drivers.yaml) and external anchors (framework.yaml) of this section's milestones
# (plain assignments: a failing ledger.py aborts under set -e; a pipeline would hide it)
DRIVERS="$(uv run $ROOT/core/ledger.py driver-draws --section "$SECTION")"
DRIVERS="$(printf '%s\n' "${DRIVERS:-(none used by $SECTION milestones)}" | sed 's/^/    /')"
ANCHORS="$(uv run $ROOT/core/ledger.py anchors "$SECTION")"
ANCHORS="$(printf '%s\n' "${ANCHORS:-(none for $SECTION milestones)}" | sed 's/^/    /')"
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
- Shared drivers (RUBRIC.md §4.1 step 2; $D/drivers.yaml has their fits), driver|used_by|params:
$DRIVERS
  A milestone in a driver's used_by samples its draws and never refits it: draw i of
      uv run $ROOT/core/ledger.py driver-draws <driver> --as-of $UNTIL   (CSV; canonical seed and n)
  goes into draw i of your simulation; name the driver id in basis.eta.calc. The mapping onto the
  milestone stays yours (§4.1 step 3). A driver fit you think wrong: say so in the notes, still use it.
- External anchors (RUBRIC.md §4.1 step 4), target|source|id|relation|deadline|metric ids|note:
$ANCHORS
  For a milestone with anchors, finish its forecast first and write a line "pre-anchor p50: YYYY
  (p10-p90 ..., p_achieved ...)" in its notes section BEFORE reading any anchor series. Then read
  them (series $SECTION <metric> --as-of $UNTIL --with-note: the note gives forecasters=n and the
  question), compare, and explain each gap in
  basis.eta.calc (the crux, citing the anchor's metric id); do not close a gap without a reason
  you would accept without the anchor.
- Every failure scenario of 10% or more names its reference class with counts, or says why no class
  can be counted (then it is a disclosed judgment with a sensitivity) (§4.1 step 5).
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
Validate until 0 errors, and fix the WARN lines it prints about your records (an unexplained
anchor gap, an unnamed shared driver):
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

# REVIEW: the ETA audit (2026-10-14 rounds, data ledger/audits/) as a permanent stage. A fresh agent in
# another mode (ASSESS_REVIEW_MODE, default deep; the same mode as a deep-fallback assessor, which is
# then not "another" model) audits the staged milestone records + notes; MAJOR findings get ONE fix
# attempt by the assessor and one re-review. What remains is committed with the run: the accepted
# review rounds, then a final "MAJOR: <n>" = findings left (a fix whose re-review failed counts as
# unresolved); ledger.py check warns while it is > 0. A failed or blocked review is noted, never
# fatal; the one fatal case is a reviewer that edits what it reviews. REVIEW=0 skips the stage.
# --- review stage (core/tests/test_review.sh runs this block with stubs) ---
REVIEW_FILE="$NOTES_DIR/$SECTION/$RUN_ID.review.md"  # = ledger.review_path
review_prompt() {  # $1 = output file, $2 = the previous round's report (re-review after a fix)
cat <<EOF2
Audit the ETA assessments that another agent just staged for "$SECTION" as of $UNTIL, before they
are committed. Records: $AS; their working notes: $STAGE/eta-notes.md. Do NOT modify either file;
write only $1 and scratch files under $STAGE/review-work/. Read $ROOT/gather/RUBRIC.md fully
(binding) and the milestones' wording in $ROOT/framework.yaml (description + details). Comparison:
the previous record per target in ledger/assessments/$SECTION.jsonl and its notes
$NOTES_DIR/$SECTION/<run id>.md (prev.by = "assess:<run id>[:mode]"). Evidence: effective events in
ledger/events/<section>.jsonl; series:
    uv run $ROOT/core/ledger.py series <section> <metric> --as-of $UNTIL
$( [ -n "${2:-}" ] && printf '%s\n' "This is a RE-REVIEW after the assessor's fix: read $2 first. For each of its MAJOR findings say
whether it is fixed or soundly rebutted in the notes' '## Review response' (an unresolved one stays
MAJOR), then check the revised files afresh for regressions.")
For each milestone record check: (1) right quantity for the framework wording and details;
(2) data recency, measurement gaps unmeasured not flat; (3) spot-check 2-3 key numbers against the
ledger; (4) rerun the notes' script and confirm the stored numbers: copy it under
$STAGE/review-work/, inspect array sizes first, batch anything large and cap the process memory
(e.g. ulimit -v 2000000); (5) input register: measured / sourced / assumed labels true,
sensitivities for assumed inputs that matter; (6) RUBRIC.md rule 7: every move vs prev (p10/p50/p90
by a year or more or year<->null, p_achieved by 0.05 or more) attributed, and truly; (7) effective
records only; (8) consistency across milestones sharing a driver; (9) shared drivers: a milestone in a
drivers.yaml used_by samples the driver's draws (ledger.py driver-draws <driver> --as-of $UNTIL) as its
script shows, with no private refit of the driver; (10) anchors (ledger.py anchors $SECTION): the notes
state a pre-anchor p50 before the anchors are read, and each gap (RUBRIC.md §4.1 step 4 thresholds) is
explained in calc with its crux and the anchor's metric id (for a "similar" anchor: how much of it the
wording differences account for), not closed by an unattributed move; (11)
every failure scenario of 10% or more names its reference class with counts, or argues why no class
can be counted and gives a sensitivity (RUBRIC.md §4.1 step 5).
SEVERITY: MAJOR = a factual error vs the ledger, a superseded or corrected claim relied on, the
wrong quantity, arithmetic that does not reproduce, an unattributed or falsely attributed move,
an assumed input labelled measured, a shared driver refitted instead of sampled, an anchor gap left
unexplained or closed without a reason, a failure scenario of 10% or more with neither reference-class
counts nor an argued reason why none can be counted, or another broken RUBRIC.md rule that changes a number (e.g. an optional adjustment without
evidence in the median). NOT major: a disclosed assumption with its
sensitivity, an incomplete minor sensitivity, wording.

Write $1: per MAJOR finding the target, what is wrong (with numbers / ids) and what would fix it;
then minor findings briefly. Paraphrase the notes, never copy long passages. The LAST line of
$1 must be exactly "MAJOR: <count>".
Never run git add/commit: the pipeline commits your report (a commit by you aborts the run).
EOF2
}
run_review() {  # $1 = round, $2 = previous report; sets REV_MAJOR (empty = the review failed)
	rev="$STAGE/review-$1.md"; rm -f "$rev"; REV_MAJOR=""
	if ! PI_MODEL="$(pi_mode_model "$REVIEW_MODE")"; then
		PI_MODEL="$ASSESS_MODEL"; echo "WARN: review $1 failed: no pi mode '$REVIEW_MODE'" >&2; return 0
	fi
	sums="$(cksum "$AS" "$STAGE/eta-notes.md")"
	PI_SOFT_FAIL=1
	pi_run "review-$1" "$(review_prompt "$rev" "${2:-}")"
	PI_SOFT_FAIL=; PI_MODEL="$ASSESS_MODEL"
	[ "$(cksum "$AS" "$STAGE/eta-notes.md")" = "$sums" ] || { echo "ERROR: the reviewer modified $AS or the notes" >&2; exit 1; }
	REV_MAJOR="$(tail -n 1 "$rev" 2>/dev/null | sed -n 's/^MAJOR: \([0-9][0-9]*\)$/\1/p')"
	if [ "$PI_RC" != 0 ] || [ -n "${PI_BLOCKED:-}" ] || [ -z "$REV_MAJOR" ]; then
		echo "WARN: review $1 failed (pi exit $PI_RC$( [ -n "${PI_BLOCKED:-}" ] && echo ', provider block'), or no 'MAJOR: <n>' last line)" >&2
		REV_MAJOR=""; if [ -f "$rev" ]; then mv "$rev" "$rev.rejected"; fi   # a failed round is never committed
	fi
}
review_stage() {  # updates NOTE; writes $STAGE/review.md (nothing when round 1 failed)
	REVIEW_MODE="${ASSESS_REVIEW_MODE:-deep}"; ASSESS_MODEL="${PI_MODEL:-}"
	rm -f "$STAGE/review.md"
	run_review 1
	if [ -z "$REV_MAJOR" ]; then NOTE="$NOTE (review failed)"; return 0; fi
	left="$REV_MAJOR"; tail_note=""
	if [ "$REV_MAJOR" -gt 0 ]; then
		cp "$AS" "$AS.draft"; cp "$STAGE/eta-notes.md" "$STAGE/eta-notes.md.draft"
		PI_SOFT_FAIL=1
		pi_run fix "$(prompt)

You already staged $AS and $STAGE/eta-notes.md in this run (they are your draft: do not start over).
An independent review found $left MAJOR problem(s): read $STAGE/review-1.md. Revise both files in
place: fix each MAJOR finding, or rebut it with evidence in a final '## Review response' section of the
notes. Change only what a finding requires (RUBRIC.md rule 7 applies to your own draft too)."
		PI_SOFT_FAIL=
		if [ "$PI_RC" = 0 ] && [ -z "${PI_BLOCKED:-}" ] && as_complete; then
			rm -f "$AS.draft" "$STAGE/eta-notes.md.draft"
			run_review 2 "$STAGE/review-1.md"
			if [ -n "$REV_MAJOR" ]; then NOTE="$NOTE (review: $left MAJOR, $REV_MAJOR after one fix)"; left="$REV_MAJOR"
			else NOTE="$NOTE (review: $left MAJOR, fixed once, re-review failed)"
				tail_note="The re-review failed: the fix is unverified, so round 1's count stands."; fi
		else  # a failed, blocked or broken fix never replaces the complete draft
			mv "$AS.draft" "$AS"; mv "$STAGE/eta-notes.md.draft" "$STAGE/eta-notes.md"
			echo "WARN: the fix attempt failed (pi exit $PI_RC$( [ -n "${PI_BLOCKED:-}" ] && echo ', provider block'), or incomplete); committing the reviewed draft" >&2
			NOTE="$NOTE (review: $left MAJOR, fix failed)"
			tail_note="The fix attempt failed; the reviewed draft was committed unchanged."
		fi
	else NOTE="$NOTE (review: 0 MAJOR)"
	fi
	{
		for r in 1 2; do
			if [ -s "$STAGE/review-$r.md" ]; then printf '# Review round %s\n\n' "$r"; cat "$STAGE/review-$r.md"; echo; fi
		done
		printf '# Remaining\n\n%s\nMAJOR: %s\n' "$tail_note" "$left"
	} > "$STAGE/review.md"
	if [ "$left" -gt 0 ]; then echo "WARN: $left MAJOR review finding(s) remain; see $REVIEW_FILE" >&2; fi
}
# --- end review stage ---
case "$TARGETS" in *milestone:*) if [ "${REVIEW:-1}" != 0 ]; then review_stage; fi ;; esac

for t in $(echo "$TARGETS" | cut -d'|' -f1 | grep '^milestone:' || true); do
	grep -qE "^## $t([^a-z0-9-]|\$)" "$STAGE/eta-notes.md" || echo "WARN: $STAGE/eta-notes.md has no '## $t' section" >&2
done
uv run $ROOT/core/ledger.py merge "$SECTION" --assessments "$AS"
if [ -s "$STAGE/eta-notes.md" ]; then mkdir -p "$NOTES_DIR/$SECTION"; cp "$STAGE/eta-notes.md" "$NOTES"; fi
if [ -s "$STAGE/review.md" ]; then mkdir -p "$NOTES_DIR/$SECTION"; cp "$STAGE/review.md" "$REVIEW_FILE"; fi
uv run $ROOT/core/ledger.py check "$SECTION"
commit "assess $SECTION as of $UNTIL$( [ "${CORRECTION:-}" = 1 ] && echo " (rubric $RUBRIC correction)"): $(echo "$TARGETS" | cut -d'|' -f1 | tr '\n' ' ')$NOTE$( [ -n "${AUDIT:-}" ] && echo " (audit: $AUDIT)")" \
	"ledger/assessments/$SECTION.jsonl" "$NOTES" "$REVIEW_FILE"
warn_drivers
echo ">>> done: assess $SECTION as of $UNTIL"
