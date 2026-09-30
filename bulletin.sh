#!/bin/sh
# Grand Endeavors — BULLETIN: one section's report for one period, as a view of
# the ledger at a deterministic cutoff (DESIGN.md §2, §5).
# =============================================================================
#   1. snapshot  ledger.py snapshot: the ledger as of cutoff = period end + lag
#                (weekly 2d, monthly 7d, longer 14d); committed = reproducible input
#   2. draft     from the snapshot ONLY (no research), in the reference format;
#                KPI charts rendered from the ledger (kpi.py chart)
#   3. edit      editorial review (reviewer subagent + fidelity to the snapshot);
#                no new facts: gaps go to <period-dir>/gaps/<section>.md for the
#                next gather run
#   4. gate      validate.py --snapshot (fatal by default; STRICT=0 = report-only)
# Same ledger + same period => the same facts, however late the bulletin runs.
#
# USAGE:  ./bulletin.sh <period-dir> <section>
#         period-dir = pilot-<period> or <period>: 2025, 26H1, 2026-Q2, 2026-06, 2026-W39
# ENV:    EARLY=1       allow a run before the cutoff (the ledger may still grow)
#         ALLOW_DIRTY=1 skip the clean-worktree preflight
# Then: ./roundup.sh <period-dir> compiles the period README.
# =============================================================================
OUT_DIR="${1:?usage: bulletin.sh <period-dir> <section>}"
SECTION="${2:?usage: bulletin.sh <period-dir> <section>}"
. "$(dirname "$0")/lib.sh"
require_section "$SECTION"
OUT_DIR="${OUT_DIR%/}"
case "$OUT_DIR" in ""|*/*|.*|*[!A-Za-z0-9-]*)
	echo "ERROR: period-dir must be a plain top-level name, e.g. pilot-26H1" >&2; exit 1 ;;
esac
PERIOD="${OUT_DIR#pilot-}"
CUT_LINE="$(uv run ledger.py cutoff "$PERIOD")" || { echo "ERROR: '$PERIOD' is not a period" >&2; exit 1; }
CUTOFF="$(echo "$CUT_LINE" | awk '{print $2}')"
PREV_CUTOFF="$(echo "$CUT_LINE" | awk '{print $4}')"
TODAY="$(date -u +%Y-%m-%d)"
if [ "$TODAY" \< "$CUTOFF" ] && [ -z "${EARLY:-}" ]; then
	echo "ERROR: cutoff $CUTOFF not reached yet (today $TODAY); set EARLY=1 to draft anyway" >&2; exit 1
fi
require_clean

RUN_NAME="bulletin-$OUT_DIR-$SECTION"
SESS_DIR="$OUT_DIR/.sessions"
OUT_FILE="$OUT_DIR/$SECTION.md"
SNAP="$OUT_DIR/snapshot/$SECTION.json"
GAPS="$OUT_DIR/gaps/$SECTION.md"
MANIFEST="$OUT_DIR/MANIFEST-$SECTION.txt"
REF_TEMPLATE="pilot-2025/$SECTION.md"; [ -f "$REF_TEMPLATE" ] || REF_TEMPLATE="pilot-2025/climate.md"
ALLOWED="$OUT_FILE $GAPS"
mkdir -p "$OUT_DIR" "$SESS_DIR"
GATE="uv run validate.py $OUT_FILE --snapshot $SNAP"

# --- 1. snapshot ----------------------------------------------------------------
{
	echo "# Bulletin manifest — $OUT_DIR / $SECTION"
	echo "period:        $PERIOD  (cutoff $CUTOFF; new = published after $PREV_CUTOFF)"
	echo "generated_at:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo "ledger_commit: $(git rev-parse HEAD)  (the snapshot is the ledger at this commit, as of the cutoff)"
	tool_versions
} > "$MANIFEST"
uv run ledger.py snapshot "$OUT_DIR" "$SECTION"
commit "$OUT_DIR $SECTION: bulletin snapshot (cutoff $CUTOFF)" "$MANIFEST" "$SNAP"

# --- 2. draft -------------------------------------------------------------------------
pi_run draft "$(cat <<EOF
Write the "Grand Endeavors" bulletin for section "$SECTION", period $PERIOD, into
$OUT_FILE.

SOURCE OF FACTS: ONLY the ledger snapshot $SNAP (read ALL of it). It is the
ledger as of the cutoff $CUTOFF. Do no web research, and add nothing from
memory. Also read:
- ./README.md: the "$SECTION" endeavor, i.e. KPI, milestones and challenges;
- $REF_TEMPLATE: the reference FORMAT (not content);
- DESIGN.md §2 and §5.
Snapshot parts:
- new_events: this period's news (published after $PREV_CUTOFF).
- background_events: earlier context, including verification=legacy records from
  earlier reports. Use them only as explicitly earlier context, never as news.
- kpi_headlines: current / previous / change / year_ago.
- assessments: current and previous status per milestone/KPI.
- chartable_metrics, other_metrics.

STRUCTURE (follow the reference format):
- A one-line italic note first: period, "developments published up to $CUTOFF",
  and the date of the latest data.
- Executive Summary: bottom line up front; good news; bad news.
- KPI Dashboard:
  - Report every kpi_headline: its current value and obs date, the previous
    value, and the change with its caveat (a non-comparable change must be
    flagged, never presented as a trend). Give year_ago where provided.
  - Include 1-2 trend charts rendered FROM THE LEDGER, pasted verbatim, keeping
    their "%% kpi:" line. You may edit only the title and y-axis label. E.g.:
        uv run kpi.py chart $OUT_DIR $SECTION <metric> --since <YYYY> --label year [--match '*-05']
    Choose metrics from chartable_metrics. Use a single granularity (--match for
    one month per year) and about 10-15 points.
- Milestone Status: one subsection per README milestone, using the assessment
  status (green 🟢, yellow 🟡, red 🔴, achieved ✅), its label (the verdict word
  first, e.g. "Off track", as defined in ./STATUS.md) and rationale, and what
  changed since the previous assessment. Mark it "Not yet assessed" if it has
  none. Add the relevant new events. Show the KPI assessment the same way in
  the KPI Dashboard, and add a one-line status legend from STATUS.md: KPI
  status = pace versus what the goal needs, not the level; milestone status =
  ETA on evidence.
- Open Challenges: one subsection per README challenge, covering its new events.
  If there are none, write "No significant developments this period." (Name every
  challenge and milestone exactly as README does.)
- Beyond the Framework: the "beyond" new events.
- Reference Data: dataset links from the snapshot sources.
- Footnotes: wiki-style [^ref] citations; each points to a source URL of the
  snapshot record it states.

HARD RULES:
- Every number must appear VERBATIM in the snapshot (no rounding, no arithmetic
  of your own). Use the provided change / year_ago values.
- Keep metric scopes exactly as the claims label them. No causal bridges across
  distinct metrics (e.g. atmospheric growth vs emissions).
- Distinguish achieved vs announced vs projected.
Then run until 0 errors:
    $GATE
Write only $OUT_FILE.
EOF
)"
commit "$OUT_DIR $SECTION: bulletin draft" "$OUT_FILE"

# --- 3. edit ---------------------------------------------------------------------------
pi_run edit "$(cat <<EOF
Edit and finalize $OUT_FILE (the "$SECTION" bulletin for $PERIOD, written from the
ledger snapshot $SNAP). This is EDITORIAL review, not research.
1. Dispatch a reviewer subagent. It critiques form and substance against the
   reference $REF_TEMPLATE: structure, clarity, bottom-line-up-front, and
   whether the milestone statuses follow from the cited evidence.
2. Dispatch a fidelity subagent. It checks every sentence against the snapshot
   record it cites:
   - the claim, numbers, scope labels and dates match the record;
   - new vs background framing is right (legacy and background items must not
     read as this period's news);
   - achieved vs announced vs projected is kept;
   - no hindsight: nothing published after $CUTOFF.
3. Apply the fixes to $OUT_FILE. Do not add facts that are not in the snapshot.
   If a reviewer finds an important gap that the snapshot cannot fill, append
   it as a bullet to $GAPS (create it with the heading "# Gaps for the next
   gather run"). It is input for the next gather, not for this bulletin.
4. Run until 0 errors:
       $GATE
Modify ONLY $OUT_FILE and $GAPS. Report the changes.
EOF
)"
commit "$OUT_DIR $SECTION: bulletin edit" "$OUT_FILE" "$GAPS"

# --- 4. gate ----------------------------------------------------------------------------
echo ">>> [$RUN_NAME] gate"
if ! $GATE; then
	echo "!!! bulletin gate reported errors in $OUT_FILE"
	[ "${STRICT:-1}" = 0 ] || exit 1
fi
echo ">>> done: $OUT_FILE  (snapshot $SNAP, cutoff $CUTOFF)"
