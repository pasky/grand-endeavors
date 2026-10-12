# TODO — Grand Endeavors

Current backlog only; finished work lives in git history and DESIGN.md.
Architecture: DESIGN.md · status rubric: gather/RUBRIC.md · views: views/EXPLORER.md ·
data: github.com/pasky/grand-endeavors-data (`./data`).
🤖 = can be done by agents without the owner in the loop.

## ⚠ Known gaps (deferred on purpose)

- [ ] **Cross-section ETA drivers are not tracked** (deferred by the owner 2026-10-12).
      Milestone ETAs may rest on another section's series, e.g. all four robots-hardware
      capability milestones on robots-software's METR horizons (`ledger.py drivers
      <section>` lists them). But `ledger.py stale` ignores them, so a new METR point
      does NOT re-assess robots-hardware. Even a manual re-run cannot change a status on
      driver data alone (hysteresis wants in-section evidence), and the evidence list
      cannot cite foreign event ids. Until fixed, assess.sh and gather.sh print a WARN
      per affected milestone. Fix: milestones declare their drivers; stale + hysteresis
      follow them.

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
- [ ] 🤖 Retry the legacy events that are still unverifiable, **sequentially with
      backoff**. The 2026-10-01 Wayback pass recovered 45 (21 verified, 22
      corrected, 2 refuted), but 8 parallel agents hit archive.org rate limits;
      rockets got none.
- [ ] 🤖 Re-verify the legacy KPI **observations** (pilot-2025 values); only events
      were re-verified.
- [ ] Yearly upkeep: when GCB 2026 is released (around November), update
      `DATA_URL` in `gather/collectors/climate_emissions.py`. Watch for WHO's next GHE
      round; health data ends in 2021, so its KPI is labelled "Stale".
- [ ] Fusion KPI caveats (independent spot-check of 2025-Q4 matched exactly;
      2021-Q4 couldn't be independently parsed):
      - exchange-rate swings move the series;
      - it is deflated with US CPI only;
      - it is weighted by population, not by consumption;
      - coverage is about 94%.

      Consider adding a local-currency or PPP variant.
- [ ] Rockets KPI: a `cost-to-leo-best` history (only one point). Needs a
      sourcing decision: list prices are sparse and inconsistent.
- [ ] Robots-hardware KPI ("largest single-site fleet"): no public series; it
      needs a definition that can actually be observed.

## Roadmap

- [ ] weekly cadence running · [ ] publishing (Substack, automated Twitter) ·
      [ ] expert review + errata (this maps onto `supersedes`)
