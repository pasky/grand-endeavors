#!/bin/sh
# Grand Endeavors — report generation harness (pi-based, OpenProse-free)
# =============================================================================
#
# Generates one endeavor section for one reporting period via a small pipeline
# of granular, individually-committed `pi` invocations. No DSL: each stage is a
# plain prompt to `pi`.
#
# USAGE:
#   ./generate.sh <period> <section> ["scope override"]
#
#   period   reporting-period dir, e.g. 26H1, 2025, 2026-W26
#   section  one of: climate fusion rockets robots-software robots-hardware
#            health knowledge-beyond society-cohesion
#   scope    OPTIONAL free-text narrowing (default: full endeavor structure).
#            For toy/narrow runs, e.g.:
#              ./generate.sh 26H1 climate \
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
#   - A generation-specific agent config (.gen-agent/) symlinks the live
#     ~/.pi/agent but DROPS pi-session-summary, whose widget callback crashes
#     headless runs on subagent session replacement (stale-ctx bug).
#
# REPRODUCIBILITY:
#   <period>/MANIFEST.txt records pi version, the ~/.pi/agent commit (+dirty
#   flag), settings hash, and the generation-config hash. To reproduce, check
#   out that agent commit (restore settings.json) and re-run. Per-stage sessions
#   are saved under <period>/.sessions/ (gitignored) for after-the-fact audit.
#
# DURABILITY:
#   Research is persisted as committed Markdown notes under
#   <period>/research/<section>/ — the citation-bearing artifacts are kept and
#   reviewable, not buried inside an opaque agent run.
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
PLAN_FILE="$RESEARCH_DIR/PLAN.txt"
OUT_FILE="$OUT_DIR/$SECTION.md"
REF_TEMPLATE="pilot-2025/climate.md"   # structural reference (format, not content)
mkdir -p "$RESEARCH_DIR" "$SESS_DIR"

AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
GEN_AGENT="$ROOT/.gen-agent"           # gitignored; rebuilt each run

# --- Build the generation agent config (live config minus session-summary) ---
build_gen_agent() {
	rm -rf "$GEN_AGENT"; mkdir -p "$GEN_AGENT"
	for f in "$AGENT_DIR"/* "$AGENT_DIR"/.[!.]*; do
		b="$(basename "$f")"
		[ "$b" = "settings.json" ] && continue
		[ -e "$f" ] && ln -s "$f" "$GEN_AGENT/$b"
	done
	python3 - "$AGENT_DIR/settings.json" "$GEN_AGENT/settings.json" <<-'PY'
		import json, sys
		s = json.load(open(sys.argv[1]))
		s["packages"] = [p for p in s.get("packages", []) if "session-summary" not in p]
		json.dump(s, open(sys.argv[2], "w"), indent=2)
	PY
}

# Run one granular pi stage with the generation config; saved+named session.
# $1 = stage label, $2 = prompt
pi_run() {
	label="$1"; prompt="$2"
	echo ">>> [$SECTION/$PERIOD] $label"
	# </dev/null: keep pi from consuming the caller's stdin (e.g. the research
	# loop reading PLAN.txt) — otherwise pi slurps it and the loop ends early.
	PI_CODING_AGENT_DIR="$GEN_AGENT" pi -p --approve \
		--session-dir "$SESS_DIR" \
		--name "${PERIOD}-${SECTION}-${label}" \
		"$prompt" </dev/null
}

commit() { git add -A; git commit -q -m "$1" || echo "    (nothing to commit)"; }

write_manifest() {
	{
		echo "# Generation manifest — $PERIOD"
		echo "generated_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
		echo "pi_version:   $(pi --version 2>&1 | head -1)"
		echo "agent_commit: $(git -C "$AGENT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
		git -C "$AGENT_DIR" diff --quiet 2>/dev/null \
			&& echo "agent_dirty:  no" \
			|| echo "agent_dirty:  YES (config not pinned — capture settings/extensions to reproduce)"
		echo "settings_sha: $(sha256sum "$AGENT_DIR/settings.json" 2>/dev/null | cut -c1-16)"
		echo "gencfg_sha:   $(sha256sum "$GEN_AGENT/settings.json" 2>/dev/null | cut -c1-16) (live config minus session-summary)"
		echo "spec_commit:  $(git rev-parse HEAD)"
	} > "$OUT_DIR/MANIFEST.txt"
}

# === Pipeline ================================================================
build_gen_agent
write_manifest
commit "$PERIOD $SECTION: manifest + run setup"

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

Write the plan to $PLAN_FILE, ONE ITEM PER LINE, exactly in the form:
    slug | one-sentence description of what to research for this item
where slug is short, lowercase, hyphenated, and unique (e.g.
"kpi-co2-ppm", "milestone-the-bend"). Write ONLY that file. No prose report.
EOF
)"
commit "$PERIOD $SECTION: research plan"

[ -s "$PLAN_FILE" ] || { echo "ERROR: no plan produced at $PLAN_FILE"; exit 1; }

# --- Stage 2: research (one web-capable main-agent pi PER item) --------------
while IFS= read -r line <&3; do
	case "$line" in ""|\#*) continue ;; esac
	slug="$(printf '%s' "$line" | cut -d'|' -f1 | tr -d ' ')"
	desc="$(printf '%s' "$line" | cut -d'|' -f2-)"
	[ -n "$slug" ] || continue
	note="$RESEARCH_DIR/$slug.md"
	pi_run "research-$slug" "$(cat <<EOF
Research ONE item for the "Five Grand Endeavors" newsletter, section
"$SECTION", reporting period "$PERIOD".

ITEM: $slug
WHAT TO FIND: $desc
OVERALL RUN SCOPE (context): $SCOPE

Use your web-search and visit-webpage skills to find concrete developments
WITHIN the reporting period $PERIOD from authoritative PRIMARY sources.
- Every claim needs a precise, citable URL pointing at the actual data/figure
  (not a generic homepage). VISIT each source to confirm it really states the
  claim — do not cite from memory or from a search snippet alone.
- Record specific dates, numbers, project/company names.
- Distinguish achieved vs announced vs projected; note setbacks honestly.
- If this item is the KPI, collect 5-10 years of historical datapoints for a
  trend chart, with the data-source URL.
- Stay within $PERIOD; older datapoints only as historical context.

Write findings to $note as a short claims list — each claim immediately
followed by its verified source URL — plus a one-line status assessment
(achieved / approaching / distant / improving / worsening). Write ONLY that
file, then report which claims you actually verified by visiting the source.
EOF
)"
	commit "$PERIOD $SECTION: research $slug"
done 3< "$PLAN_FILE"

# --- Stage 3: draft ----------------------------------------------------------
pi_run draft "$(cat <<EOF
Write the newsletter section "$SECTION" for period "$PERIOD" into $OUT_FILE.

Inputs:
- ./README.md — the endeavor definition to follow.
- $RESEARCH_DIR/*.md — research notes; EVERY factual claim and citation in the
  report MUST come from these notes (read all of them). Do not add unsupported
  claims.
- $REF_TEMPLATE — structural/formatting reference. Follow its structure:
  Executive Summary (bottom-line-upfront) -> KPI Dashboard (value + mermaid
  xychart trend + sources) -> Milestone Status (one subsection each, 🟢/🟡/🔴)
  -> Open Challenges (substantive analysis) -> Beyond the Framework ->
  Reference Data -> Footnotes. Use wiki-style [^ref] footnote citations.

SCOPE FOR THIS RUN: $SCOPE
Cover only in-scope items that have a research note; do not invent items. Open
the file with a one-line note stating the period and (if narrowed) the scope.
Write $OUT_FILE and give a brief summary of what you wrote.
EOF
)"
commit "$PERIOD $SECTION: draft"

# --- Stage 4: review + revise (offline subagent critique + web spot-check) ---
pi_run review "$(cat <<EOF
Review and finalize $OUT_FILE (the "$SECTION" section for $PERIOD).

1. Dispatch a reviewer subagent (subagent tool) to critique $OUT_FILE on form
   and substance: structure vs $REF_TEMPLATE, clarity, and whether every
   number/claim traces to a citation present in $RESEARCH_DIR/*.md.
2. Dispatch a coverage subagent to confirm every in-scope milestone/challenge
   from README.md (within SCOPE) is covered with a justified status indicator.
3. YOU (main agent, you have web skills) spot-check the headline KPI value and
   1-2 load-bearing/surprising claims by visiting their cited URLs; flag any
   that don't actually support the claim.
4. Apply all fixes directly to $OUT_FILE: correct or remove unsupported claims,
   fix citations, tighten prose. Report the changes you made.
EOF
)"
commit "$PERIOD $SECTION: review"

echo ">>> done: $OUT_FILE  (research: $RESEARCH_DIR/, manifest: $OUT_DIR/MANIFEST.txt)"
