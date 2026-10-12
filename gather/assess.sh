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
#         ALLOW_DIRTY=1      skip the clean-worktree preflight
# =============================================================================
SECTION="${1:?usage: assess.sh <section>}"
RUBRIC=v3  # current gather/RUBRIC.md version (= ledger.RUBRIC; checked by core/tests/test_paths.py)
. "$(dirname "$0")/../core/lib.sh"
require_section "$SECTION"
require_clean
UNTIL="${UNTIL:-$(date -u +%Y-%m-%d)}"
case "$UNTIL" in *[!0-9-]*) echo "ERROR: UNTIL must be YYYY-MM-DD" >&2; exit 1 ;; esac
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_NAME="assess-$SECTION-$RUN_ID"
STAGE="ledger/staging/assess-$SECTION-$RUN_ID"
SESS_DIR="ledger/.sessions"
ALLOWED="$STAGE/"
mkdir -p "$STAGE"

TARGETS="$(uv run $ROOT/core/ledger.py stale "$SECTION" --until "$UNTIL" $( [ "${FORCE:-}" = 1 ] && echo --force ))"
if [ -n "${ONLY:-}" ]; then  # restrict to the given targets (space-separated)
	TARGETS="$(printf '%s\n' "$TARGETS" | while IFS='|' read -r t id; do
		case " $ONLY " in *" $t "*) echo "$t|$id" ;; esac; done)"
fi
[ -n "$TARGETS" ] || { echo ">>> [$RUN_NAME] nothing to assess"; exit 0; }
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
# every registered series, all sections: milestone ETAs may rest on a driver from another section
METRICS="$(for f in metrics/*.csv; do s="$(basename "$f" .csv)"; [ "$s" = kpi-assessment ] && continue
	printf '    %s: %s\n' "$s" "$(awk -F, 'NR>1{printf "%s%s", (n++ ? ", " : ""), $1}' "$f")"; done)"
AS="$STAGE/assessments.jsonl"

PI_SOFT_FAIL=1  # a failed agent may still have staged a complete, lint-clean file (salvaged below)
pi_run assess "$(cat <<EOF
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
  with made_at <= $UNTIL is "prev").
- Other sections, for milestone ETAs (RUBRIC.md §4.1 step 2: a driver trend may live
  elsewhere, e.g. METR task horizons in robots-software): ledger/events/<section>.jsonl,
  and the registered series (same "series <section> <metric>" command):
$METRICS
  Cite such data in basis.eta.calc (metric, values, event ids); the evidence list holds
  only $SECTION event ids.
$CORR
Judge each milestone on its OWN quantity as the framework wording defines it (e.g.
total greenhouse-gas emissions, not CO2 alone). If only a proxy has data, name
the proxy and why it tracks the target in basis.path, and let that uncertainty
show in the ETA.
Milestone ETAs: follow RUBRIC.md §4.1 step by step for EACH milestone, from all the data
above, before choosing its status. Do the arithmetic (uv run python is fine) and write
your working per milestone to $STAGE/eta-notes.md: the gap, every data point used, the
growth model and why, the time-to-target calculation, the cross-checks (reference class,
discounted proponent dates, prev ETA) and the cruxes. Put the result in basis.eta
{p10, p50, p90, method, calc, cruxes} and quote the median in the label ("ETA ~2034").
Do not restate a status band ("5-10 years") as an ETA, and do not answer "not estimable"
or ">10 years" for lack of a series: tie the milestone to a driver or a reference class.
Exponential quantities must be extrapolated exponentially.
A milestone with an "assumes:" entry in framework.yaml is judged as if that assumption held
(RUBRIC.md §4.2): the gate never blocks it, basis.eta.assumes repeats it, the label says
"ETA ~YYYY*", and basis.blockers reports the gate's real state.
If the rubric cannot judge a target (e.g. its KPI series does not cover the
window), write status "unknown" with the label "Unassessed: <reason>" and the
basis keys rule, reason, prev and change_note (evidence may be empty). Never
leave a listed target out.

Write $AS: one JSON object per line with fields exactly: id (EXACTLY as given),
target, status (green|yellow|red, or achieved for milestones), label
("<Verdict>: ..." per RUBRIC.md, at most 100 chars), made_at "$UNTIL", rationale
(2-4 sentences, consistent with basis), evidence [event ids], by
"assess:$RUN_ID", rubric "$RUBRIC", basis (the keys $ROOT/DESIGN.md §3 "Assessment" lists for
KPI or milestone targets)$( [ "${CORRECTION:-}" = 1 ] && echo ", rubric_correction \"$RUBRIC\"" ).
Validate until 0 errors:
    uv run $ROOT/core/ledger.py lint $SECTION --assessments $AS
Work only in $STAGE: do not read other runs' files under ledger/staging/ or ledger/.sessions/
(their notes are not evidence, and judgments must be independent).
EOF
)"
PI_SOFT_FAIL=
SALVAGE=""
if [ "$PI_RC" != 0 ]; then
	# e.g. a provider-side block of the agent's final turn after it had finished the file:
	# salvage only a complete (all targets, exact ids) and lint-clean file
	echo "WARN: assess agent failed (pi exit $PI_RC); salvaging $AS only if complete and lint-clean" >&2
	SALVAGE=" (salvaged: the assess agent exited $PI_RC after staging a complete, lint-clean file)"
fi
[ -s "$AS" ] || { echo "ERROR: assess wrote no $AS" >&2; exit 1; }
want_ids="$(printf '%s\n' "$TARGETS" | cut -d'|' -f2 | sort)"
got_ids="$(uv run python -c 'import json,sys; [print(json.loads(l)["id"]) for l in open(sys.argv[1]) if l.strip()]' "$AS" | sort)"
[ "$want_ids" = "$got_ids" ] || { echo "ERROR: $AS ids differ from the targets:" >&2
	printf 'want:\n%s\ngot:\n%s\n' "$want_ids" "$got_ids" >&2; exit 1; }
uv run $ROOT/core/ledger.py lint "$SECTION" --assessments "$AS" || { echo "ERROR: $AS does not lint clean" >&2; exit 1; }
uv run $ROOT/core/ledger.py merge "$SECTION" --assessments "$AS"
uv run $ROOT/core/ledger.py check "$SECTION"
commit "assess $SECTION as of $UNTIL$( [ "${CORRECTION:-}" = 1 ] && echo " (rubric $RUBRIC correction)"): $(echo "$TARGETS" | cut -d'|' -f1 | tr '\n' ' ')$SALVAGE" \
	"ledger/assessments/$SECTION.jsonl"
# KNOWN GAP (TODO.md, deferred): cross-section ETA drivers are not tracked by `ledger.py stale`
uv run $ROOT/core/ledger.py drivers "$SECTION" | while IFS='|' read -r t s m; do
	echo "WARN: $SECTION $t: its ETA rests on $s/$m, but a new $m observation will NOT re-assess it (cross-section staleness is not implemented, TODO.md)" >&2
done
echo ">>> done: assess $SECTION as of $UNTIL"
