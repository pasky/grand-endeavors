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

- [ ] **Nothing measures task horizons at the frontier** (2026-10-18): METR stopped, and
      SWE-Marathon cannot resolve the frontier (its 80% horizon sits near 10 h for every frontier
      model), so the KPI's ECI line is unchecked where it extrapolates, and the task-horizon
      tripwire (two gap series, data drivers.yaml) cannot fire. No existing benchmark fills in
      (~25 scouted 2026-10-18, each verdict in data ledger/audits/2026-10-18-horizon-sources:
      read it before scouting again). The fix is our own time-tagged benchmark: pass/fail tasks with
      measured human hours from ~1 h to weeks (so the frontier's 80% point falls inside the
      range), run on frontier models as they ship, per-trial results public.

## Owner decisions

- [ ] **Scheduling budget**: how often each section's gather runs (a full
      8-item climate gather ≈ 75 min of agent time), and which model per stage
      (e.g. a cheaper intake model, a strong verifier).
- [ ] Finish `views/newsletter-intro.md` (the newsletter intro still ends in `..todo..`).

## Operations

- [ ] 🤖 **A gather run that aborts mid-intake cannot resume** (2026-10-18 top-up: two intake
      agents left helper scripts in the data root, the write-scope guard aborted the runs,
      and the finished items' staged files were orphaned). The prompts now ask for scratch
      files under `$STAGE/scratch/`, but nothing enforces that. The run was rescued by hand:
      re-run the remaining items, copy the old staged files into the new staging dir before
      verify, then record the old items' state. Fix: `RESUME=<staging dir>` in gather.sh that
      skips the finished items and verifies and merges their files. Possibly also move stray
      untracked files into scratch instead of aborting.
- [ ] 🤖 **The assess review cannot be re-run alone**: when the review stage fails (2026-10-18,
      rockets: the deep-mode reviewer died with "terminated"), the records are committed
      unreviewed. The only remedy is a full `FORCE=1 ONLY=...` re-assessment, which doubles
      the cost. Fix: retry a failed review once automatically, or an assess.sh mode that
      reviews the latest committed records and notes.
- [ ] Scheduling of the LLM stages: `gather/gather.sh <section>`, then
      `views/bulletin.sh` + `views/roundup.sh` after each cutoff (weekly cutoff =
      Sunday + 2 days); needs the scheduling-budget decision above. The
      deterministic collectors already run daily (`gather/collect.sh`, systemd user
      timer, DESIGN.md §4a), and so do the site refresh and the data push.
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
      reliability; more dated reliability series would firm it up. Note: Dyna's napkin
      station is a fixed arm, NOT general-purpose under the robots-hardware KPI definition
      (owner 2026-10-18), so the general-purpose milestones' ETAs lean on a non-GP robot.
      At the next rubric pass, keep it as a stated analogy or switch/blend to a GP series now in
      the ledger (Figure Helix 9% -> 56% full-task success in 30 unseen homes; Robotera's
      100 -> 1,200 parcels/h at China Post is a fixed-stand M7, not GP either).
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
- [ ] Robots-hardware KPI is provisional (owner 2026-10-18; research and board memo in data
      ledger/audits/2026-10-18-hardware-kpi/): a count of documented deployment cases
      (`gp-deployment-pairs`). Replace it with a measure of the work done (robots x hours x
      interventions) once deployments disclose that. Coverage caveat: a one-off web check
      found 2 qualifying cases the ledger had missed, mostly Chinese, where 'practical
      training' (实训) vs production work is the recurring judgment call.

## Roadmap

- [ ] weekly cadence running · [ ] publishing (Substack, automated Twitter) ·
      [ ] expert review + errata (this maps onto `supersedes`)
