# TODO — Grand Endeavors

Working backlog for the report-generation project. Newest context: the harness
(`generate.sh`) is a pi-based, OpenProse-free pipeline validated on a narrow toy
run (`pilot-26H1/climate.md`). See git log for the rationale behind each piece.

## Harness / infrastructure

- [ ] **Validation gate** — a deterministic, no-LLM check script run after the
      `review` stage (complements, doesn't replace, the LLM review):
  - [ ] link resolution: every URL non-404 (Jina/archive fallback for
        Cloudflare-blocked hosts); optionally snapshot each cited URL locally
  - [ ] footnote/reference integrity: every `[^ref]`/`[label]` used has a
        definition and vice versa; no orphans/dangling
  - [ ] mermaid lint: each block parses; x-axis length == data-series length
  - [ ] KPI consistency: headline value matches research note + round-up README
  - [ ] coverage: every in-scope `PLAN.txt` slug present with a status icon;
        every KPI sub-clause from README present (would catch reservation A)
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

## Output quality (from deep-mode review of pilot-26H1/climate.md)

- [ ] **Reservation A (borderline blocker):** KPI is defined as CO₂ ppm *and
      10-year trend (ppm/yr)*; output reports only single-year growth (+2.23) and
      omits the decadal figure (~+2.57/yr from its own chart) — understates the
      trend. Fix draft prompt to require all KPI sub-clauses.
- [ ] **Reservation B (major-ish):** Exec summary conflates atmospheric
      ppm-growth (El-Niño-sink driven) with the emissions trajectory as one
      causal story. Tighten draft prompt to forbid causal bridges across distinct
      metrics.
- [ ] Cite verifiable IEA PDF artifact, not the JS landing page.
- [ ] Avoid mixing IEA energy-CO₂ vs GCB fossil+cement growth bases across years.

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
