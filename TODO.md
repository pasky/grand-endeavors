# TODO — Grand Endeavors

Working backlog for the report-generation project. Newest context: the harness
(`generate.sh`) is a pi-based, OpenProse-free pipeline validated on a narrow toy
run (`pilot-26H1/climate.md`). See git log for the rationale behind each piece.

## Harness / infrastructure

- [x] **Harness guardrails** (done — commit a53e679, from deep code review):
      OUT_DIR/period split, clean-worktree preflight, scoped+safe stage commits,
      surgical anti-contamination prune (+ note reuse / `FRESH=1`), slug
      validation, empty-note abort, and hardened draft/review prompts (KPI
      completeness, no cross-metric causal bridges, precise deep-link citations).
- [x] **Validation gate** (done — validate.py, commit dc25d34 + hardening): footnote/
      reference-link integrity, mermaid xychart axis/series lengths, dead-URL
      (404/410 hard-fail; 403/timeout/neterr warn), PLAN-slug coverage; wired as
      review-stage self-check + Stage-5 backstop (STRICT=1 to fail run). Known
      limitations to harden later:
  - [ ] coverage is a soft heuristic (any-URL-overlap, warn-only) — won't catch
        missing KPI sub-components, dropped slugs sharing a URL, or redirected
        URLs; not a real coverage proof
  - [ ] footnote/ref regexes ignore duplicate definitions, indented defs,
        shortcut refs, and case-insensitive label equivalence
  - [ ] mermaid check only length-checks unnamed line/bar arrays (no real parse,
        named series, or missing-series detection)
  - [ ] (future) snapshot each cited URL locally for permanence (link-rot proofing)
  - [ ] (future) KPI consistency: headline value matches research note + round-up
        README; every KPI sub-clause from README present in output
- [ ] **Round-up generator** — final stage compiling section files into the
      period `README.md` (the pilot-2025 round-up had this; not yet ported).
- [ ] **KPI time-series store** (`kpis.csv` or per-endeavor JSON) — makes charts
      reproducible and week-over-week deltas trivial; prerequisite for a cheap
      weekly cadence.
- [ ] Decide on the **regressions vs the old OpenProse RECIPE** (from deep review):
  - [ ] per-stage **model specialization** (e.g. opus research/write, cheaper
        compile) instead of one default model everywhere
  - [ ] **parallel** research instead of the serial `while read` loop (tradeoff:
        lose per-item independent retry/commit)
  - [ ] **"Beyond the Framework"** is under-resourced — plan stage emits only
        KPI+milestones+challenges, nothing researches the "beyond" section
  - [ ] thinner **formatting guidance** (we lean on the reference template;
        likely why the per-milestone emissions chart got dropped)

## Output quality (from deep reviews of pilot-26H1/climate.md)

The harness prompts are now hardened against all of these (commit a53e679), but
the EXISTING pilot-26H1 artifact still exhibits them — **regenerate with
`FRESH=1 ./generate.sh pilot-26H1 climate "…scope…"`** (FRESH=1 is required, else
the old research notes are reused and the deep-link/metric-scope research fixes
won't be retested) to both verify the guardrails work and replace the defective
artifact (don't hand-patch the toy — that defeats the harness test). Defects to
confirm are gone after regen:

- [ ] **Reservation A:** KPI defined as CO₂ ppm *and 10-year trend (ppm/yr)*;
      output reported only single-year growth (+2.23), omitting the decadal
      figure (~+2.57/yr from its own chart) — understated the trend.
- [ ] **Reservation B:** Exec summary conflated atmospheric ppm-growth
      (El-Niño-sink driven) with the emissions trajectory as one causal story.
- [ ] IEA cited at JS landing page, not the verified PDF deep link in the note.
- [ ] Mixed IEA energy-CO₂ vs GCB fossil+cement growth bases across years.
- [ ] "The Bend" is defined as global **GHG/CO₂e**; evidence was mostly CO₂
      proxies — either source GHG/CO₂e or explicitly state the proxy.
- [ ] Internal contradiction: note said total CO₂ (incl. land-use) was slightly
      *below* 2024, report said "global totals still inching to fresh records."

## Validation at scale

- [ ] **Full (non-narrow) Climate run** — validate full coverage of all
      milestones+challenges and get a real cost/time profile.

## Content / housekeeping

- [ ] Finish `TEMPLATE.md` (newsletter intro still ends in `..todo..`).
- [ ] (low priority — owner says config is generally stable) optionally pin a
      clean `~/.pi/agent` commit so manifests stop reporting `agent_dirty: YES`.

## Roadmap (from top-level README status)

- [ ] weekly report cadence running
- [ ] reference source list per endeavor
- [ ] publishing infra (Substack + automated Twitter)
- [ ] drafting/feedback infra for early expert review + errata
