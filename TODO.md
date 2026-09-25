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

The harness prompts were hardened against all of these (commit a53e679). **Verified
by a FRESH regen** (`FRESH=1`, original toy-run scope, run 2026-09-25, spec 768de6a,
commits a58ac87..8b7bd74; the scope is now recorded in MANIFEST.txt). No hand-patching.
Key numbers were spot-checked against live sources (NOAA co2_gr_mlo 2016–25 mean =
2.564; IEA GER 2026 PDF 38 082 Mt / +0.4%; ESSD GCB total CO₂ 42.2 Gt, "marginally
below" 2024). The gate reports 0 errors and 0 warnings.

- [x] **Reservation A:** the 10-yr trend is now in the exec summary and the dashboard:
      2.56 ppm/yr MLO / 2.53 global (2016–25), plus a half-decade split (2.51→2.61),
      *alongside* the single-year +2.23. The chart has a 10-yr mean line. The plan
      stage picked up "10-year" from README even though the scope only said "recent
      ppm/year trend".
- [x] **Reservation B:** ppm growth is attributed to La Niña/sinks (Met Office), with an
      explicit "concentration growth is not an emissions measure" note. The Bend is
      assessed separately, from inventories.
- [x] IEA is cited as the PDF deep link (iea.blob…/GlobalEnergyReview2026.pdf, pp. 13,
      36, 45).
- [x] Growth bases: each emissions estimate has its own row and scope label (GCB
      fossil, IEA energy, Carbon Monitor fossil+industry, GCB total). The two ppm
      growth definitions (NOAA Jan→Dec vs annual-mean) are also reconciled
      explicitly.
- [x] GHG vs CO₂: an explicit "Metric caveat" says no 2025 CO₂e total was published
      within 26H1, so CO₂ is used as a proxy.
- [x] Records contradiction: the report now says "every fossil and energy CO₂
      estimate" hit a record and "only total CO₂, which includes land use, dipped",
      which matches the note.
  - [ ] residual nit: the status and bottom lines still say "Emissions are on a
        near-plateau at a record level" without naming the scope. The draft prompt
        was hardened (scoped superlatives in headline/status lines) but this is
        **unverified until the next run**.

Other observations from the regen:
- [ ] Per-milestone multi-year **emissions chart** is still missing. The notes have
      no year-by-year emissions series, so the research prompt must ask for one
      for milestones too, not only for the KPI. (Related: "thinner formatting
      guidance" above.)
- Retrospective runs work: the research ran in Sep 2026 and picked up post-period
  sources (EDGAR, Climate TRACE, CREA Q2). The notes quarantined these as "published
  after 30 June", and the draft correctly left them out.

## Validation at scale

- [ ] **Full (non-narrow) Climate run** — validate full coverage of all
      milestones+challenges and get a real cost/time profile.

## Content / housekeeping

- [ ] Finish `TEMPLATE.md` (newsletter intro still ends in `..todo..`).
- [x] (low priority) clean `~/.pi/agent` so manifests stop reporting
      `agent_dirty: YES` (the 2026-09-25 run reports `agent_dirty: no`).

## Roadmap (from top-level README status)

- [ ] weekly report cadence running
- [ ] reference source list per endeavor
- [ ] publishing infra (Substack + automated Twitter)
- [ ] drafting/feedback infra for early expert review + errata
