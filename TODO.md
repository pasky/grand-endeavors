# TODO — Grand Endeavors

Current backlog only; finished work lives in git history and DESIGN.md.
Architecture: DESIGN.md · status rubric: gather/RUBRIC.md · views: views/EXPLORER.md ·
data: github.com/pasky/grand-endeavors-data (`./data`).
🤖 = can be done by agents without the owner in the loop.

## ⚠ Known gaps (deferred on purpose)

- [ ] **Cross-section ETA drivers are not tracked** (deferred by the owner 2026-10-12).
      Milestone ETAs may rest on another section's series, e.g. all four robots-hardware
      capability milestones on robots-software's task horizons (`ledger.py drivers
      <section>` lists them). But `ledger.py stale` ignores them, so a new horizon point
      does NOT re-assess robots-hardware. Even a manual re-run cannot change a status on
      driver data alone (hysteresis wants in-section evidence), and the evidence list
      cannot cite foreign event ids. Until fixed, assess.sh and gather.sh print a WARN
      per affected milestone. Fix: milestones declare their drivers (drivers.yaml `used_by`
      now does, for the shared ones); stale + hysteresis follow them. Likewise a
      drivers.yaml edit, or an anchor moving past a gap threshold, re-assesses nothing.
- [ ] **External anchors cover 1 of 20 milestones** (2026-10-15, data
      ledger/audits/2026-10-15-anchors): a deep-mode review standing in for the owner accepted
      only strict implications (two `weaker` Manifold bounds for the-first-watt) and rejected
      near matches (e.g. the Coffee Test markets, a lunar-base market for the Moon-or-Mars
      Homestead). Owner: confirm or relax the standard; add anchors as markets appear.
      **Terms**: Metaculus community aggregates need API access granted on request
      (non-commercial projects: "get in touch"; then set METACULUS_TOKEN); Manifold's terms
      forbid systematic compilation without written permission while its API docs allow
      non-commercial use: consider asking data@manifold.markets.

- [ ] 🤖 **The task-horizon tripwire has one live source** (owner decision 2026-10-17, option D,
      data drivers.yaml): only SWE-Marathon measures hours at the ECI frontier (METR's gap
      series resumes if METR does: add the model to robots_software.py CALIBRATION_PAIRS).
      A second source needs per-trial results, hours that predict failure (METR's logistic
      slope >= 0.25 for most configurations, via `swe_marathon.fit()`) and tasks spanning the
      frontier horizon. Terminal-Bench 4.0 fails the slope test (terminal_bench.py docstring).
      Scouted 2026-10-18 (~25 benchmarks), none qualifies: per-task results but no human hours
      (FrontierSWE, DeepSWE, MirrorCode, FrontierCode, GSO, AlgoTune, ALE-Bench, ExploitBench), or
      hours but short/saturated tasks or no per-task results (SWE-bench Verified, Cybench,
      APEX-Agents, GDPval). OSWorld 2.0 (computer use, a remote-side candidate) fails too: its hours
      are annotators' range guesses (max 6 h), public only as 5 bins (paper arXiv 2606.29537
      App. G.2), and success is <=24% even on <45-min tasks, so length is not what limits agents.
      Open leads: FrontierSWE (34 long tasks, per-task results and traces public) if its
      maintainers have per-task expert-hour estimates (ask them); BRIDGE (github.com/McGill-NLP/BRIDGE,
      IRT difficulty -> human hours, R² 0.81 on METR tasks) could put hourless tasks on METR's scale,
      but that scale ends near 16 h, so it moves the extrapolation rather than removing it.

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
- [ ] Gather all sections. Only climate (full), fusion (KPI), robots-software (KPI and
      milestones, 2025-07 to 2026-10) and the re-verification pass have run; the other
      sections' news is all 2025-report history.
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
- [ ] **ETA calibration** (deferred by the 2026-10-14 audit, data ledger/audits/2026-10-14-r1..r4;
      the audit is now assess.sh's review stage, DESIGN.md step 6). Rubric v6 (2026-10-15)
      correlates the shared drivers across milestones (drivers.yaml draws) and makes failure
      scenarios of 10%+ name reference classes with counts; still open: the counts are small,
      hand-picked analogue sets (data ledger/audits/2026-10-15-v6), and joint statements
      ("P(A before B)") would need each run to store its per-draw outcome years. Watch the
      review stage's MAJOR counts and cost (it roughly doubles an assess run).
- [ ] drivers.yaml `fusion-first-watt` expires 2027-06-30 (review_by: its time-remaining model
      predicts the past once Helion's 2028 date nears): refit it with the proponents' news.
- [ ] Owner review of the rubric v6 ETAs (all milestones re-assessed 2026-10-15 under v6, then
      audited, data ledger/audits/2026-10-15-v6; working notes committed in
      ledger/assessments/notes/<section>/<run id>.md), and of data drivers.yaml (the shared
      driver fits carry over the audited v5 inputs; spreads are assumed). The robot
      capability ETAs (2027–2031) rest on the Dyna failure-rate halving (~7.6 months, ONE
      customer deployment, 2025–2026), now an explicitly assumed transfer to robot
      reliability; more dated reliability series would firm it up.
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
- [ ] Robots-hardware KPI ("largest single-site fleet"): no public series; it
      needs a definition that can actually be observed.

## Roadmap

- [ ] weekly cadence running · [ ] publishing (Substack, automated Twitter) ·
      [ ] expert review + errata (this maps onto `supersedes`)
