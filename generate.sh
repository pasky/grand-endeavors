#!/bin/sh
# Grand Endeavors — report generation harness (pi-based, OpenProse-free)
# =============================================================================
#
# Generates one endeavor section for one reporting period via a small pipeline
# of granular, individually-committed `pi` invocations. No DSL: each stage is a
# plain prompt to `pi`.
#
# USAGE:
#   ./generate.sh <out-dir> <section> ["scope override"]
#
#   out-dir  output directory = reporting-period dir. During the pilot phase
#            prefix with "pilot-", e.g. pilot-26H1, pilot-2025, pilot-2026-W26.
#            The reporting period told to the agents is out-dir minus a leading
#            "pilot-" (so pilot-26H1 -> period "26H1").
#   section  one of: climate fusion rockets robots-software robots-hardware
#            health knowledge-beyond society-cohesion
#   scope    OPTIONAL free-text narrowing (default: full endeavor structure).
#            For toy/narrow runs, e.g.:
#              ./generate.sh pilot-26H1 climate \
#                "ONLY the KPI (atmospheric CO2 ppm + trend) and milestone
#                 'The Bend'. Cover Jan-Jun 2026 only."
#
# ARCHITECTURE (and why):
#   - Web research is done by MAIN-agent pi processes, one PER research item
#     (KPI / each milestone / each challenge). Only the main agent loads the
#     web-search + visit-webpage skills; subagents run with noExtensions and
#     therefore CANNOT reliably reach the web. One pi-per-item also makes each
#     research note independently retryable and committed.
#   - Subagents are used only in the REVIEW stage for offline critique /
#     coverage / fact-checking-against-notes (no web needed there).
#
# DETERMINISM / SAFETY:
#   - Requires a clean git worktree at start (override: ALLOW_DIRTY=1) so stage
#     commits never scoop unrelated changes.
#   - Each stage commits ONLY the run's output dir (scoped `git add`), and
#     distinguishes "nothing to commit" from a real commit failure.
#   - After planning, research notes whose slug is NOT in the new PLAN.txt are
#     pruned (kills cross-scope contamination); notes still in the plan are
#     REUSED on rerun (cheap, retryable). Force full re-research with FRESH=1.
#   - Plan slugs from the LLM are validated (^[a-z0-9][a-z0-9-]*$, unique) before
#     being used as filenames; empty research notes abort the run.
#
# REPRODUCIBILITY:
#   <out-dir>/MANIFEST.txt records pi version and the ~/.pi/agent commit (+dirty
#   flag) + settings hash. Per-stage sessions are saved under <out-dir>/.sessions/
#   (gitignored) for after-the-fact audit.
#
# DURABILITY:
#   Research is persisted as committed Markdown notes under
#   <out-dir>/research/<section>/ — citation-bearing artifacts kept and reviewable.
# =============================================================================

set -eu

OUT_DIR="${1:?usage: generate.sh <out-dir> <section> [scope]}"
SECTION="${2:?usage: generate.sh <out-dir> <section> [scope]}"
SCOPE="${3:-Cover the FULL endeavor structure: the KPI plus every milestone and every challenge defined in README.md.}"

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PERIOD="${OUT_DIR#pilot-}"             # reporting period told to the agents
RESEARCH_DIR="$OUT_DIR/research/$SECTION"
SESS_DIR="$OUT_DIR/.sessions"
PLAN_FILE="$RESEARCH_DIR/PLAN.txt"
OUT_FILE="$OUT_DIR/$SECTION.md"
REF_TEMPLATE="pilot-2025/climate.md"   # structural reference (format, not content)

AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"

# --- Preflight: clean worktree so scoped stage commits stay clean ------------
if [ -z "${ALLOW_DIRTY:-}" ] && [ -n "$(git status --porcelain)" ]; then
	echo "ERROR: git worktree not clean. Commit/stash first, or set ALLOW_DIRTY=1." >&2
	git status --short >&2
	exit 1
fi

mkdir -p "$RESEARCH_DIR" "$SESS_DIR"

# Run one granular pi stage; saved+named session.
# $1 = stage label, $2 = prompt
pi_run() {
	label="$1"; prompt="$2"
	echo ">>> [$SECTION/$OUT_DIR] $label"
	# </dev/null: keep pi from consuming the caller's stdin (e.g. the research
	# loop reading PLAN.txt) — otherwise pi slurps it and the loop ends early.
	pi -p --approve \
		--session-dir "$SESS_DIR" \
		--name "${OUT_DIR}-${SECTION}-${label}" \
		"$prompt" </dev/null
}

# Commit ONLY this run's OWN artifacts (manifest, research dir, output file) —
# never sibling sections in the same period dir, even under ALLOW_DIRTY=1.
# Relies on these paths having no spaces (true for our naming convention).
commit() {
	msg="$1"
	paths=""
	for p in "$OUT_DIR/MANIFEST.txt" "$RESEARCH_DIR" "$OUT_FILE"; do
		[ -e "$p" ] && paths="$paths $p"
	done
	[ -n "$paths" ] || { echo "    (nothing to stage for: $msg)"; return 0; }
	git add $paths
	if git diff --cached --quiet -- $paths; then
		echo "    (nothing to commit for: $msg)"
		return 0
	fi
	git commit -q -m "$msg" -- $paths
}

write_manifest() {
	{
		echo "# Generation manifest — $OUT_DIR"
		echo "report_period: $PERIOD"
		echo "section:       $SECTION"
		echo "generated_at:  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
		echo "pi_version:    $(pi --version 2>&1 | head -1)"
		echo "agent_commit:  $(git -C "$AGENT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
		git -C "$AGENT_DIR" diff --quiet 2>/dev/null \
			&& echo "agent_dirty:   no" \
			|| echo "agent_dirty:   YES (config not pinned — capture settings/extensions to reproduce)"
		echo "settings_sha:  $(sha256sum "$AGENT_DIR/settings.json" 2>/dev/null | cut -c1-16)"
		echo "spec_commit:   $(git rev-parse HEAD)  (HEAD at run START = input spec/harness version; output committed AFTER)"
		echo "fresh:         $([ "${FRESH:-}" = 1 ] && echo yes || echo no)"
		# scope last + flattened to one line: needed to reproduce/regenerate the run
		printf 'scope:         %s\n' "$(printf '%s' "$SCOPE" | tr '\n' ' ')"
	} > "$OUT_DIR/MANIFEST.txt"
}

# === Pipeline ================================================================
write_manifest
commit "$OUT_DIR $SECTION: manifest + run setup"

# --- Stage 1: plan -----------------------------------------------------------
# Emit the in-scope research items, one per line, as: "slug | description".
pi_run plan "$(cat <<EOF
Read ./README.md and extract the "$SECTION" endeavor definition (KPI,
milestones, challenges). Read $REF_TEMPLATE for the target report format.

Reporting period: $PERIOD.
SCOPE FOR THIS RUN: $SCOPE

Produce a research plan: the list of items to research, limited to SCOPE.
Always include the KPI, then each in-scope milestone and each in-scope
challenge — one line per item. Missing an item means it won't be researched.
If the KPI definition has MULTIPLE components (e.g. "concentration AND 10-year
trend"), the KPI item's description MUST name every component so none is dropped.

Write the plan to $PLAN_FILE, ONE ITEM PER LINE, exactly in the form:
    slug | one-sentence description of what to research for this item
where slug matches ^[a-z0-9][a-z0-9-]*\$ (short, lowercase, hyphenated) and is
unique (e.g. "kpi-co2-ppm", "milestone-the-bend"). Write ONLY that file. No
prose report.
EOF
)"
commit "$OUT_DIR $SECTION: research plan"

[ -s "$PLAN_FILE" ] || { echo "ERROR: no plan produced at $PLAN_FILE" >&2; exit 1; }

# Validate the ENTIRE plan BEFORE any destructive action, so a malformed plan
# can never delete existing notes. Collect validated "slug|desc" lines.
PLAN_VALID="$(mktemp)"
trap 'rm -f "$PLAN_VALID"' EXIT
seen_slugs=" "
while IFS= read -r line; do
	case "$line" in ""|\#*) continue ;; esac
	case "$line" in *"|"*) : ;; *)
		echo "ERROR: malformed plan line (no '|'): $line" >&2; exit 1 ;;
	esac
	# Trim only leading/trailing whitespace; internal whitespace stays and is
	# then rejected by the slug charset check below.
	slug="$(printf '%s' "$line" | cut -d'|' -f1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
	desc="$(printf '%s' "$line" | cut -d'|' -f2- | sed 's/^[[:space:]]*//')"
	case "$slug" in
		"" ) echo "ERROR: empty slug in plan line: $line" >&2; exit 1 ;;
		-* | *[!a-z0-9-]* ) echo "ERROR: invalid slug '$slug' (need ^[a-z0-9][a-z0-9-]*\$)" >&2; exit 1 ;;
	esac
	[ -n "$desc" ] || { echo "ERROR: empty description for slug '$slug'" >&2; exit 1 ; }
	case "$seen_slugs" in *" $slug "*)
		echo "ERROR: duplicate slug '$slug' in plan" >&2; exit 1 ;;
	esac
	seen_slugs="$seen_slugs$slug "
	printf '%s|%s\n' "$slug" "$desc" >> "$PLAN_VALID"
done < "$PLAN_FILE"
[ -s "$PLAN_VALID" ] || { echo "ERROR: plan has no valid items" >&2; exit 1; }

# Plan is valid -> now safe to prune notes whose slug isn't in the plan.
for f in "$RESEARCH_DIR"/*.md; do
	[ -e "$f" ] || continue
	s="$(basename "$f" .md)"
	case "$seen_slugs" in
		*" $s "*) : ;;
		*) echo "    pruning stale note: $f"; rm -f "$f" ;;
	esac
done
commit "$OUT_DIR $SECTION: prune stale research notes"

# --- Stage 2: research (one web-capable main-agent pi PER item) --------------
while IFS='|' read -r slug desc <&3; do
	note="$RESEARCH_DIR/$slug.md"
	# FRESH=1 (exactly): delete any existing note first, so a 'fresh' run can't
	# silently survive on stale content if pi exits 0 without rewriting it.
	[ "${FRESH:-}" = 1 ] && rm -f "$note"
	# Reuse an existing non-empty note (cheap retry); FRESH=1 forces re-research.
	if [ -s "$note" ]; then
		echo ">>> [$SECTION/$OUT_DIR] research-$slug: reusing existing note (FRESH=1 to redo)"
	else
	pi_run "research-$slug" "$(cat <<EOF
Research ONE item for the "Five Grand Endeavors" newsletter, section
"$SECTION", reporting period "$PERIOD".

ITEM: $slug
WHAT TO FIND: $desc
OVERALL RUN SCOPE (context): $SCOPE

Use your web-search and visit-webpage skills to find concrete developments
WITHIN the reporting period $PERIOD from authoritative PRIMARY sources.
- Every claim needs a precise, citable URL pointing at the ACTUAL data/figure
  (a deep link to the dataset/PDF/figure, NOT a generic homepage or a JS
  landing page). VISIT each source to confirm it really states the claim — do
  not cite from memory or a search snippet alone.
- Record specific dates, numbers, project/company names.
- Distinguish achieved vs announced vs projected; note setbacks honestly.
- Watch metric boundaries: do not conflate distinct measures (e.g. atmospheric
  concentration vs emissions, or different emissions scopes like energy-CO2 vs
  fossil+cement CO2 vs total GHG/CO2e). Label which measure each number is.
- If this item is the KPI, address EVERY component of the KPI definition (e.g.
  current value AND any required multi-year trend) and collect 5-10 years of
  historical datapoints for a trend chart, with the data-source URL.
- Stay within $PERIOD; older datapoints only as historical context.

Write findings to $note as a short claims list — each claim immediately
followed by its verified deep-link source URL — plus a one-line status
assessment (achieved / approaching / distant / improving / worsening). Write
ONLY that file, then report which claims you verified by visiting the source.
EOF
)"
	fi
	# A research stage that produced no note is a failure, not "nothing to commit".
	[ -s "$note" ] || { echo "ERROR: research stage wrote no note at $note" >&2; exit 1; }
	commit "$OUT_DIR $SECTION: research $slug"
done 3< "$PLAN_VALID"

# --- Stage 3: draft ----------------------------------------------------------
pi_run draft "$(cat <<EOF
Write the newsletter section "$SECTION" for period "$PERIOD" into $OUT_FILE.

Inputs:
- ./README.md — the endeavor definition to follow.
- $RESEARCH_DIR/*.md — research notes; EVERY factual claim and citation in the
  report MUST come from these notes (read all of them). Do not add unsupported
  claims, and only cover items that have a research note.
- $REF_TEMPLATE — structural/formatting reference. Follow its structure:
  Executive Summary (bottom-line-upfront) -> KPI Dashboard (value + mermaid
  xychart trend + sources) -> Milestone Status (one subsection each, 🟢/🟡/🔴)
  -> Open Challenges (substantive analysis) -> Beyond the Framework ->
  Reference Data -> Footnotes. Use wiki-style [^ref] footnote citations.

HARD REQUIREMENTS:
- The KPI Dashboard MUST report EVERY component of the KPI as defined in
  README.md (e.g. if it says "concentration AND 10-year trend", report both the
  current value AND the multi-year trend — not just the latest single-year
  number).
- Do NOT bridge distinct metrics with a causal claim. In particular, year-to-
  year atmospheric-concentration growth is NOT the same as the emissions
  trajectory (sinks/ENSO confound it); keep such metrics separate unless a
  research note explicitly supports the causal link.
- Cite the precise deep link from the research notes (dataset/PDF/figure), not a
  homepage or JS landing page.
- Respect metric scopes exactly as the notes label them. This includes
  headline/summary/status lines: any "record", "peak", "rising" or "falling"
  claim must name its measure (e.g. "fossil CO2 at a record", not "emissions at
  a record") whenever another in-scope measure disagrees.

SCOPE FOR THIS RUN: $SCOPE
Open the file with a one-line note stating the period and (if narrowed) the
scope. Write $OUT_FILE and give a brief summary of what you wrote.
EOF
)"
commit "$OUT_DIR $SECTION: draft"

# --- Stage 4: review + revise (offline subagent critique + web spot-check) ---
pi_run review "$(cat <<EOF
Review and finalize $OUT_FILE (the "$SECTION" section for $PERIOD).

1. Dispatch a reviewer subagent (subagent tool) to critique $OUT_FILE on form
   and substance: structure vs $REF_TEMPLATE, clarity, and whether every
   number/claim traces to a citation present in $RESEARCH_DIR/*.md.
2. Dispatch a coverage subagent to confirm (a) every in-scope milestone/
   challenge from README.md (within SCOPE) is covered with a justified status,
   and (b) EVERY component of the KPI definition is reported (e.g. multi-year
   trend, not just latest value).
3. YOU (main agent, you have web skills) spot-check the headline KPI value and
   1-2 load-bearing/surprising claims by visiting their cited URLs; flag any
   that don't actually support the claim, any homepage/landing-page citations
   that should be deep links, and any metric-scope conflation.
4. Apply all fixes directly to $OUT_FILE: correct or remove unsupported claims,
   fix citations to precise deep links, separate conflated metrics, tighten
   prose.
5. Run the mechanical validator and fix EVERY error it reports (undefined
   footnotes/refs, mermaid axis/series length mismatches, dead citation URLs):
       uv run validate.py $OUT_FILE --plan $PLAN_FILE --research $RESEARCH_DIR
   Re-run it until it reports 0 errors. Then report the changes you made.
EOF
)"
commit "$OUT_DIR $SECTION: review"

# --- Stage 5: validation gate (deterministic, no-LLM) ------------------------
# Mechanical checks the LLM review can't be talked out of: footnote/reference
# integrity, mermaid axis/series lengths, dead citation URLs, PLAN coverage.
# Non-fatal by default (report + record); set STRICT=1 to fail the run on errors.
echo ">>> [$SECTION/$OUT_DIR] validate"
if ! uv run validate.py "$OUT_FILE" --plan "$PLAN_FILE" --research "$RESEARCH_DIR"; then
	echo "!!! validation gate reported errors in $OUT_FILE"
	if [ -n "${STRICT:-}" ]; then exit 1; fi
fi

echo ">>> done: $OUT_FILE  (research: $RESEARCH_DIR/, manifest: $OUT_DIR/MANIFEST.txt)"
