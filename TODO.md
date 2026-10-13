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
- [ ] **Audit the ETAs before trusting them further** (next step after the 2026-10-13 merge):
      deep-mode reviewers per section read each run's committed ETA notes
      (ledger/assessments/notes/<section>/<run id>.md) + the ledger against a fixed
      checklist (right quantity for the wording; definitions resolved; data recency and
      measurement gaps; ledger vs background numbers, spot-checked; meaningful median /
      p_achieved; the single assumption that moves the median most; consistency across
      milestones sharing a driver). Sort findings into rubric-wide / milestone / definition;
      decide the obvious ones, then ONE fix + re-run, repeat until nothing major. Then make
      it permanent: a fresh-agent review stage in assess.sh (like gather's verify).
- [ ] Owner review of the rubric v4 ETAs (all milestones re-assessed 2026-10-13; working
      notes committed in ledger/assessments/notes/<section>/<run id>.md). The robot
      capability ETAs (2028–2030) now rest on a measured ~7.6-month failure-rate halving,
      but its central value is ONE customer deployment (Dyna napkin folding, 2025–2026);
      more dated reliability series would firm it up (FOCUS gather, 2026-10-12, found 55 events).
- [ ] 🤖 Provider false-positive blocks ("duplicating model outputs") still hit assess runs
      (2026-10-12: 2 of 8). assess.sh now salvages a complete file, else retries, then falls
      back to the `deep` mode; commit messages record each block. The trigger is unknown (the
      blocked climate session had read only climate data); count blocks in the commit log and
      report the false positive to Anthropic (example: the 2026-10-12T17-05 climate session).
      gather.sh's intake/verify stages have no retry yet.
- [ ] 🤖 Retry the legacy events that are still unverifiable, **sequentially with
      backoff**. The 2026-10-01 Wayback pass recovered 45 (21 verified, 22
      corrected, 2 refuted), but 8 parallel agents hit archive.org rate limits;
      rockets got none.
- [ ] 🤖 Re-verify the legacy KPI **observations** (pilot-2025 values); only events
      were re-verified.
- [ ] Yearly upkeep: when GCB 2026 is released (around November), update
      `DATA_URL` in `gather/collectors/climate_emissions.py`. Same for the
      edition URLs in `gather/sources/` (`grep -n 'Edition URL' gather/sources/*.yaml`:
      UNEP Emissions Gap, IEA Global Energy Review, IRENA costs).
- [ ] Health KPI re-assessment: WHO's new GHE round (GHO record date 2026-10-01)
      extends HALE to 2023 and revises 2000-2021 (collected 2026-10-09). The KPI
      assessment still says "Stale (data to 2021)"; the next `gather.sh health` /
      `assess.sh health` picks it up (`ledger.py stale`).
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
