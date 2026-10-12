# TODO — Grand Endeavors

Current backlog only; finished work lives in git history and DESIGN.md.
Architecture: DESIGN.md · status rubric: gather/RUBRIC.md · views: views/EXPLORER.md ·
data: github.com/pasky/grand-endeavors-data (`./data`).
🤖 = can be done by agents without the owner in the loop.

## Owner decisions

- [ ] **Scheduling budget**: how often each section's gather runs (a full
      8-item climate gather ≈ 75 min of agent time), and which model per stage
      (e.g. a cheaper intake model, a strong verifier).
- [ ] Finish `views/newsletter-intro.md` (the newsletter intro still ends in `..todo..`).

## Operations

- [ ] Scheduling of the LLM stages: `gather/gather.sh <section>`, then
      `views/bulletin.sh` + `views/roundup.sh` after each cutoff (weekly cutoff =
      Sunday + 2 days); needs the scheduling-budget decision above. The
      deterministic collectors already run daily (`gather/collect.sh`, systemd user
      timer, DESIGN.md §4a), and so do the site refresh and the data push.
- [ ] Gather all sections. Only climate (full), fusion (KPI) and the
      re-verification pass have run; the other sections' news is all
      2025-report history.
- [ ] A hosted Datasette (`datasette publish`); the dashboard itself is published
      (pasky.or.cz/grand-endeavors/ = `build/`) and linked from the round-ups'
      Quick Reference.

## Data quality

- [ ] 🤖 103 legacy events are still unverifiable after the sequential retry of
      2026-10-12 (`gather/reverify_legacy.py`; 44 verified + 130 corrected of
      277; logs `ledger/reverify/*-wayback2.jsonl`). Left: climate 14, fusion 16,
      health 10, knowledge-beyond 8, robots-hardware 7, robots-software 17,
      rockets 11, society-cohesion 20. Mostly the cited page was fetched but does
      not state the claim, or states other figures; a few are paywalled or dead
      (Reuters 401, Science 403). Another fetch retry will not help. They need
      re-sourcing (find a source that states the claim, then `supersedes`), or
      they stay legacy background.
- [ ] Owner review of the rubric v2 ETAs (all milestones re-assessed 2026-10-06; working
      in each run's ledger/staging/assess-*/eta-notes.md, gitignored). Red→yellow:
      Linux kernel patch, Dark Line, Fukushima, all resting on METR-horizon drivers and
      an assumed ~11-month "embodied doubling" for robots.
- [ ] 🤖 assess.sh robustness: 5 of 8 runs on 2026-10-06 were blocked by a provider
      false positive ("duplicating model outputs"), 3 of them on the final turn after a
      lint-clean assessments.jsonl (merged by hand). The robots-hardware runs had read
      other runs' staging dirs (the retry read their eta-notes); a later run with those dirs
      moved aside went through. Keep agents out of other staging dirs, and consider
      merging a lint-clean staged file when only the final turn failed.
- [ ] Owner: other milestones that may deserve an `assumes:` gate (RUBRIC.md §4.2),
      e.g. robotaxi permits, Fukushima disaster-zone access. The §4.1 calibration
      amendment (50% horizon, no stacking) reaches the other milestones only on new
      evidence or a definition change.
- [ ] Cross-section ETA drivers: a milestone may rest on another section's series
      (cited in basis.eta.calc), but `ledger.py stale` does not re-assess it when
      that driver updates, and its evidence list cannot cite foreign event ids.
- [ ] Yearly upkeep: when GCB 2026 is released (around November), update
      `DATA_URL` in `gather/collectors/climate_emissions.py`. Same for the
      edition URLs in `gather/sources/` (`grep -n 'Edition URL' gather/sources/*.yaml`:
      UNEP Emissions Gap, IEA Global Energy Review, IRENA costs).
- [ ] Health KPI re-assessment: WHO's new GHE round (GHO record date 2026-10-01)
      extends HALE to 2023 and revises 2000-2021 (collected 2026-10-09). The KPI
      assessment still says "Stale (data to 2021)"; the next `gather.sh health` /
      `assess.sh health` picks it up (`ledger.py stale`).
- [ ] 🤖 Check The Bend's next assessment (yellow on 2026-09-30, label
      "Progressing: GHG 54.1 GtCO2e..."). Its rationale counted slowing **CO₂**
      growth as progress on a **total-GHG** milestone. It is re-assessed
      automatically once new Bend evidence arrives (`ledger.py stale`), and the
      assess prompt now asks for the milestone's own quantity or a named proxy.
      Verify that the new record judges it on total GHG (EDGAR).
- [ ] Rockets KPI: a `cost-to-leo-best` history (only one point). Needs a
      sourcing decision: list prices are sparse and inconsistent.
- [ ] Robots-hardware KPI ("largest single-site fleet"): no public series; it
      needs a definition that can actually be observed.

## Roadmap

- [ ] weekly cadence running · [ ] publishing (Substack, automated Twitter) ·
      [ ] expert review + errata (this maps onto `supersedes`)
