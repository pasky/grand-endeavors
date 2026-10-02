#!/bin/sh
# Grand Endeavors — period round-up generator (after the period's bulletins)
# =============================================================================
#
# Compiles the per-endeavor section files of one reporting period into the
# period's front page, <out-dir>/README.md (cf. pilot-2025/README.md): per
# endeavor a KPI headline, good/bad-news summary, milestone status table and a
# link to the full section report, then a Quick Reference table.
#
# USAGE:
#   views/roundup.sh <out-dir>          e.g.  views/roundup.sh pilot-26H1
#
# Run AFTER the period's bulletins exist (views/bulletin.sh <period-dir> <section>).
# Only sections present as <out-dir>/<section>.md are compiled; endeavors
# without a section file are listed as "not covered in this edition".
#
# The round-up is a pure SUMMARY: no research, no new facts. This is enforced by
# the deterministic gate (validate.py --roundup): every number in an endeavor
# block must appear in the section file it links to, every section is linked,
# and every link resolves.
#
# Same conventions as bulletin.sh: clean-worktree preflight (ALLOW_DIRTY=1 to
# override), scoped commit of this stage's own artifacts only, saved pi session
# under <out-dir>/.sessions/, fatal gate (STRICT=0 for report-only).
# Provenance: <out-dir>/MANIFEST-roundup.txt (separate from the per-section
# MANIFEST-<section>.txt files) records the tool versions and the git blob hash of every input
# section file.
# =============================================================================

set -eu

OUT_DIR="${1:?usage: roundup.sh <out-dir>}"
OUT_DIR="${OUT_DIR%/}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"   # mechanism repo (code, README)
D="$(cd "${GE_DATA:-$ROOT/data}" 2>/dev/null && pwd)" \
	|| { echo "ERROR: data repo not found at ${GE_DATA:-$ROOT/data} (set GE_DATA)" >&2; exit 1; }
export GE_DATA="$D"
cd "$D"                                  # period dirs live in the data repo (DESIGN.md §7)

PERIOD="${OUT_DIR#pilot-}"
OUT_FILE="$OUT_DIR/README.md"
MANIFEST="$OUT_DIR/MANIFEST-roundup.txt"
SESS_DIR="$OUT_DIR/.sessions"
REF_TEMPLATE="pilot-2025/README.md"   # structural reference (format, not content)
AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
# Canonical section order (as in README.md); also the allow-list of inputs.
ALL_SECTIONS="robots-software robots-hardware rockets fusion health climate knowledge-beyond society-cohesion"

case "$OUT_DIR" in *[[:space:]]*)
	echo "ERROR: out-dir must not contain whitespace: '$OUT_DIR'" >&2; exit 1 ;;
esac
[ -d "$OUT_DIR" ] || { echo "ERROR: no such period dir: $OUT_DIR" >&2; exit 1; }
# Compare canonical paths so ./pilot-2025, absolute paths or symlinks can't alias it.
if [ "$(cd "$OUT_DIR" && pwd -P)" = "$(cd "${REF_TEMPLATE%/*}" && pwd -P)" ]; then
	echo "ERROR: refusing to overwrite the reference round-up ($REF_TEMPLATE)" >&2; exit 1
fi

if [ -z "${ALLOW_DIRTY:-}" ] && [ -n "$(git status --porcelain)" ]; then
	echo "ERROR: git worktree not clean. Commit/stash first, or set ALLOW_DIRTY=1." >&2
	git status --short >&2
	exit 1
fi

present=""; missing=""
for s in $ALL_SECTIONS; do
	if [ -s "$OUT_DIR/$s.md" ]; then present="$present $s"; else missing="$missing $s"; fi
done
[ -n "$present" ] || { echo "ERROR: no section files in $OUT_DIR (run bulletin.sh first)" >&2; exit 1; }
present="${present# }"; missing="${missing# }"
section_files="$(for s in $present; do printf '%s ' "$OUT_DIR/$s.md"; done)"

mkdir -p "$SESS_DIR"

{
	echo "# Round-up manifest — $OUT_DIR"
	echo "report_period: $PERIOD"
	echo "generated_at:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
	echo "pi_version:    $(pi --version 2>&1 | head -1)"
	echo "agent_commit:  $(git -C "$AGENT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
	git -C "$AGENT_DIR" diff --quiet 2>/dev/null \
		&& echo "agent_dirty:   no" \
		|| echo "agent_dirty:   YES (config not pinned — capture settings/extensions to reproduce)"
	echo "settings_sha:  $(sha256sum "$AGENT_DIR/settings.json" 2>/dev/null | cut -c1-16)"
	echo "mechanism_commit: $(git -C "$ROOT" rev-parse HEAD)"
	echo "data_commit:   $(git rev-parse HEAD)  (at run START; output committed AFTER)"
	echo "inputs (git blob hash of each compiled section):"
	for s in $present; do
		# separate assignment so a hashing failure trips set -e (fail closed)
		h="$(git hash-object "$OUT_DIR/$s.md")"
		echo "  $h  $OUT_DIR/$s.md"
	done
	echo "not_covered:   ${missing:-none}"
} > "$MANIFEST"

echo ">>> [roundup/$OUT_DIR] compile ($present)"
pi -p --approve \
	--session-dir "$SESS_DIR" \
	--name "${OUT_DIR}-roundup" \
	"$(cat <<EOF
Write the round-up front page for the "Five Grand Endeavors" newsletter,
reporting period "$PERIOD", into $OUT_FILE.

Inputs:
- The section reports for this period (the ONLY source of facts): $section_files
  Read each one in full.
- $ROOT/README.md: endeavor definitions, their order, and the short intro text for
  each endeavor.
- $REF_TEMPLATE: the structural/formatting reference (the 2025 round-up).
  Follow its format, NOT its content. Its numbers are from a different period.

Endeavors with NO section report this period (not covered): ${missing:-none}.

Structure (as in $REF_TEMPLATE):
- Title "# Five Grand Endeavors — $PERIOD Report", the tagline blockquote, and a
  one-paragraph edition note: which period it is, which endeavors this edition
  covers, and which it does not. If a section report says it is a
  narrowed/partial-scope run, say so here and in that endeavor's block.
- For each present endeavor, in README.md order: a heading (robots-software and
  robots-hardware go under "## Robots and Automation" as "### Software" /
  "### Hardware"; knowledge-beyond and society-cohesion go under
  "## Supplemental"), then:
  - a one-line italic intro condensed from README.md
  - the **KPI line**, giving EVERY component of the KPI exactly as that
    section's KPI Dashboard reports it (e.g. current value AND multi-year
    trend)
  - a short good-news paragraph, then "**However:**" for the bad news
  - a milestone table (or metric table for supplemental sections) covering
    only milestones the section actually assesses
  - on its own line, the section link:
        📄 **[Full Report: <Endeavor>](<section>.md)**
  - separate endeavors with "---" lines
- A "## Quick Reference" table (Endeavor | KPI | Key $PERIOD Number | Status) for
  the present endeavors, then the status legend line.

HARD RULES:
- Summarize only. Every fact and number MUST come from the linked section
  report, copied VERBATIM. No rounding, unit conversion, recomputed or derived
  percentages, and nothing from your own knowledge or from $REF_TEMPLATE.
- Milestone statuses (emoji + label) must match the section's own verdict. Do
  not re-judge them.
- Keep metric scopes exactly as the section labels them (e.g. "fossil CO₂" vs
  "total CO₂"; concentration growth vs emissions). Do not bridge distinct
  metrics causally. Any headline "record"/"peak"/"rising" claim must name its
  measure.
- No footnotes. The round-up cites by linking to the full reports.
- Do NOT modify the section files. Write ONLY $OUT_FILE.

Then run the mechanical validator and fix EVERY error it reports. It checks
that every number in an endeavor block appears in the section file that block
links to, that every section file is linked, and that the links resolve:
    uv run $ROOT/views/validate.py $OUT_FILE --roundup
Re-run until it reports 0 errors. Then give a brief summary.
EOF
)" </dev/null

[ -s "$OUT_FILE" ] || { echo "ERROR: round-up stage wrote no $OUT_FILE" >&2; exit 1; }

# Scoped commit: only this stage's own artifacts (the pi agent may already have
# committed them itself; that's fine).
git add "$OUT_FILE" "$MANIFEST"
if git diff --cached --quiet -- "$OUT_FILE" "$MANIFEST"; then
	echo "    (nothing to commit for round-up)"
else
	git commit -q -m "$OUT_DIR: round-up README ($present)" -- "$OUT_FILE" "$MANIFEST"
fi

echo ">>> [roundup/$OUT_DIR] validate"
if ! uv run $ROOT/views/validate.py "$OUT_FILE" --roundup; then
	echo "!!! validation gate reported errors in $OUT_FILE"
	[ "${STRICT:-1}" = 0 ] || exit 1
fi
echo ">>> done: $OUT_FILE  (manifest: $MANIFEST)"
