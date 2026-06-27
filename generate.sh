#!/bin/sh
# Grand Endeavors — report generation harness (pi-based, OpenProse-free)
# =============================================================================
#
# Generates one endeavor section for one reporting period via a small pipeline
# of granular, individually-committed `pi` invocations. No DSL: each stage is a
# plain prompt to `pi`, which orchestrates research/critique through pi-amplike
# subagents (the same machinery behind /review and /advisor).
#
# USAGE:
#   ./generate.sh <period> <section> ["scope override"]
#
#   period   reporting period dir, e.g. 26H1, 2025, 2026-W26
#   section  one of: climate fusion rockets robots-software robots-hardware
#            health knowledge-beyond society-cohesion
#   scope    OPTIONAL free-text narrowing (default: full endeavor structure).
#            Use it for toy/narrow runs, e.g.:
#              ./generate.sh 26H1 climate \
#                "ONLY the KPI (atmospheric CO2 ppm + trend) and the milestone
#                 'The Bend' (peak emissions). Cover Jan-Jun 2026 only."
#
# REPRODUCIBILITY:
#   Each run writes <period>/MANIFEST.txt capturing the exact pi version, the
#   ~/.pi/agent config commit (+dirty flag), settings.json hash, and the models
#   used. To *reproduce* a past run, check out that agent commit in ~/.pi/agent
#   (and restore settings.json) before re-running. Sessions are saved per stage
#   under <period>/.sessions/ so every step is inspectable after the fact.
#
# DURABILITY:
#   Research is persisted as committed Markdown notes under
#   <period>/research/<section>/ — the expensive, citation-bearing artifacts are
#   kept and reviewed, not thrown away inside an opaque agent run.
# =============================================================================

set -eu

PERIOD="${1:?usage: generate.sh <period> <section> [scope]}"
SECTION="${2:?usage: generate.sh <period> <section> [scope]}"
SCOPE="${3:-Cover the FULL endeavor structure: the KPI plus every milestone and every challenge defined in README.md.}"

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

OUT_DIR="$PERIOD"
RESEARCH_DIR="$OUT_DIR/research/$SECTION"
SESS_DIR="$OUT_DIR/.sessions"
OUT_FILE="$OUT_DIR/$SECTION.md"
REF_TEMPLATE="pilot-2025/climate.md"   # structural reference (format, not content)
mkdir -p "$RESEARCH_DIR" "$SESS_DIR"

AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"

# Stage runner: one granular pi invocation, saved+named session, then commit.
# $1 = stage label, $2 = prompt
run_stage() {
	label="$1"; prompt="$2"
	echo ">>> [$SECTION/$PERIOD] stage: $label"
	pi -p --approve \
		--session-dir "$SESS_DIR" \
		--name "${PERIOD}-${SECTION}-${label}" \
		"$prompt"
	git add -A
	git commit -q -m "$PERIOD $SECTION: $label" || echo "    (nothing to commit for $label)"
}

# --- Provenance manifest (durable reproduction record) ----------------------
write_manifest() {
	mkdir -p "$OUT_DIR"
	{
		echo "# Generation manifest — $PERIOD"
		echo "generated_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
		echo "pi_version:   $(pi --version 2>&1 | head -1)"
		echo "agent_commit: $(git -C "$AGENT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
		git -C "$AGENT_DIR" diff --quiet 2>/dev/null && \
			echo "agent_dirty:  no" || echo "agent_dirty:  YES (config not pinned — see settings.json/extensions)"
		echo "settings_sha: $(sha256sum "$AGENT_DIR/settings.json" 2>/dev/null | cut -c1-16)"
		echo "spec_commit:  $(git rev-parse HEAD)"
		echo "models:       main=settings default; research subagents=deep mode"
	} > "$OUT_DIR/MANIFEST.txt"
	git add "$OUT_DIR/MANIFEST.txt"
	git commit -q -m "$PERIOD: manifest for $SECTION run" || true
}

# === Pipeline ================================================================
write_manifest

# --- Stage 1: research (parallel subagents, persisted notes) -----------------
run_stage research "$(cat <<EOF
You are preparing source material for the "Five Grand Endeavors" newsletter,
section "$SECTION", reporting period "$PERIOD".

SCOPE FOR THIS RUN: $SCOPE

Steps:
1. Read ./README.md and extract the definition for this endeavor/section
   (KPI, milestones, challenges). Read $REF_TEMPLATE to see the target format.
2. Build an explicit TODO list of research items in scope: the KPI, and each
   in-scope milestone and challenge — one item each. Missing an item means it
   won't appear in the report, so be exhaustive within SCOPE.
3. For EACH item, dispatch a separate research subagent in 'deep' mode (use the
   subagent tool). Each subagent must:
     - Find concrete developments within the reporting period $PERIOD with
       authoritative, primary sources; every claim needs a precise citable URL
       (pointing at the actual data, not a generic homepage).
     - Record specific dates, numbers, project/company names.
     - Distinguish achieved vs announced vs projected; note setbacks honestly.
     - For the KPI, collect 5-10 years of historical datapoints for charting.
     - Stay within the reporting period; older datapoints only as context.
     - WRITE its findings to a Markdown note at
       $RESEARCH_DIR/<item-slug>.md with a short claims list, each claim
       followed by its source URL, plus a status assessment.
4. Do NOT write the report itself in this stage. Only produce the research
   notes under $RESEARCH_DIR/. Confirm which note files were created.
EOF
)"

# --- Stage 2: draft (compile notes into the section) -------------------------
run_stage draft "$(cat <<EOF
Write the newsletter section "$SECTION" for period "$PERIOD" into $OUT_FILE.

Inputs:
- ./README.md — the endeavor definition (KPI, milestones, challenges) to follow.
- $RESEARCH_DIR/*.md — the research notes; every factual claim and citation in
  the report MUST come from these notes (read all of them).
- $REF_TEMPLATE — the structural/formatting reference. Follow its structure:
  Executive Summary (bottom-line-upfront) -> KPI Dashboard (value + mermaid
  xychart trend + sources) -> Milestone Status (one subsection each, with
  🟢/🟡/🔴) -> Open Challenges (substantive analysis) -> Beyond the Framework ->
  Reference Data -> Footnotes. Use wiki-style [^ref] footnote citations.

SCOPE FOR THIS RUN: $SCOPE
Only cover what is in scope; do not invent items lacking research notes. Open
the section with a one-line note stating the period and (if narrowed) the scope.
Write $OUT_FILE and report a brief summary of what you wrote.
EOF
)"

# --- Stage 3: review + revise (critique form & substance, fact-check) --------
run_stage review "$(cat <<EOF
Review and finalize $OUT_FILE (the "$SECTION" section for $PERIOD).

1. Dispatch a reviewer subagent (subagent tool) to critique $OUT_FILE on BOTH
   form and substance: structure vs $REF_TEMPLATE, clarity, and whether every
   number/claim is backed by a citation traceable to $RESEARCH_DIR/*.md.
2. Dispatch a fact-check subagent to verify the headline KPI value and any
   load-bearing or surprising claims against the research notes (and the cited
   URLs if needed); flag anything unsupported or contradictory.
3. Apply the resulting fixes directly to $OUT_FILE: correct/remove unsupported
   claims, fix citations, tighten prose. Verify every in-scope milestone/
   challenge from README.md (within SCOPE) is covered with a justified status.
Report the changes you made.
EOF
)"

echo ">>> done: $OUT_FILE  (research: $RESEARCH_DIR/, manifest: $OUT_DIR/MANIFEST.txt)"
