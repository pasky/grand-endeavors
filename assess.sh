#!/bin/sh
# Grand Endeavors — ASSESS: (re)judge KPI/milestone status under STATUS.md.
# =============================================================================
# Normally called by gather.sh for targets with new evidence (ledger.py stale).
# Standalone uses: re-assessment after a rubric change, or backfilling statuses.
#
# USAGE:  ./assess.sh <section>
# ENV:    UNTIL=YYYY-MM-DD   assessment as-of date = made_at (default: today UTC)
#         FORCE=1            assess ALL targets (kpi + milestones), not just stale ones
#         CORRECTION=1       records are rubric corrections (STATUS.md rule 4:
#                            once per target per rubric version, no new-evidence claim)
#         ALLOW_DIRTY=1      skip the clean-worktree preflight
# =============================================================================
SECTION="${1:?usage: assess.sh <section>}"
. "$(dirname "$0")/lib.sh"
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

TARGETS="$(uv run $ROOT/ledger.py stale "$SECTION" --until "$UNTIL" $( [ "${FORCE:-}" = 1 ] && echo --force ))"
[ -n "$TARGETS" ] || { echo ">>> [$RUN_NAME] nothing to assess"; exit 0; }
SPEC="$(awk -F, -v s="$SECTION" 'NR==1 || $1==s' metrics/kpi-assessment.csv)"
case "$SPEC" in *"
$SECTION,"*) : ;; *) SPEC="(no KPI spec for $SECTION: do NOT assess its 'kpi' target; skip it)" ;; esac
CORR=""
[ "${CORRECTION:-}" = 1 ] && CORR='Set "rubric_correction": "v1" on every record: these re-judge the existing
evidence under the new rubric (no new-evidence claim). The change_note must
say what the previous assessment got wrong under STATUS.md.'
AS="$STAGE/assessments.jsonl"

pi_run assess "$(cat <<EOF
Assess the status of these "$SECTION" targets as of $UNTIL under the status rubric
in $ROOT/STATUS.md (read it fully; it is binding). Targets (target|assessment id to use):
$TARGETS

Inputs:
- $ROOT/README.md: the "$SECTION" KPI and milestone definitions (their literal wording).
- KPI spec (fixed; do not choose your own metric, window or benchmark):
$SPEC
- Evidence: the effective events in ledger/events/$SECTION.jsonl with published <= $UNTIL.
  Records superseded via "supersedes" do not count. Legacy (unverified) records may
  inform context but cannot establish 'achieved'. Observations: use
      uv run $ROOT/ledger.py series $SECTION <metric> --as-of $UNTIL
  to compute window statistics exactly (show the numbers in basis.window).
- Previous assessments: ledger/assessments/$SECTION.jsonl (the latest per target
  with made_at <= $UNTIL is "prev").
$CORR
If the rubric cannot judge a target (e.g. its KPI series does not cover the
window), write status "unknown" with the label "Unassessed: <reason>" and the
basis keys rule, reason, prev and change_note (evidence may be empty). Never
leave a listed target out.

Write $AS: one JSON object per line with fields exactly: id (EXACTLY as given),
target, status (green|yellow|red, or achieved for milestones), label
("<Verdict>: ..." per STATUS.md, at most 100 chars), made_at "$UNTIL", rationale
(2-4 sentences, consistent with basis), evidence [event ids], by
"assess:$RUN_ID", rubric "v1", basis (the object STATUS.md specifies for KPI or
milestone targets)$( [ "${CORRECTION:-}" = 1 ] && echo ', rubric_correction "v1"' ).
Validate until 0 errors:
    uv run $ROOT/ledger.py lint $SECTION --assessments $AS
EOF
)"
[ -s "$AS" ] || { echo "ERROR: assess wrote no $AS" >&2; exit 1; }
uv run $ROOT/ledger.py merge "$SECTION" --assessments "$AS"
uv run $ROOT/ledger.py check "$SECTION"
commit "assess $SECTION as of $UNTIL$( [ "${CORRECTION:-}" = 1 ] && echo ' (rubric v1 correction)'): $(echo "$TARGETS" | cut -d'|' -f1 | tr '\n' ' ')" \
	"ledger/assessments/$SECTION.jsonl"
echo ">>> done: assess $SECTION as of $UNTIL"
