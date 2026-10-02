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

- [ ] Scheduling: cron or systemd timer for `gather/gather.sh <section>`, then
      `views/bulletin.sh` + `views/roundup.sh` after each cutoff, then `git -C data push`.
      Weekly cutoff = Sunday + 2 days.
- [ ] Gather all sections. Only climate (full), fusion (KPI) and the
      re-verification pass have run; the other sections' news is all
      2025-report history.
- [x] Dashboard published as the front page (owner symlink: pasky.or.cz/grand-endeavors/
      = `build/`; `index.html` + frozen period pages; `gather.sh` runs `explore.py site`).
      Still open: a hosted Datasette (`datasette publish`), and linking the
      dashboard from the round-ups.

## Data quality

- [ ] 🤖 Retry the legacy events that are still unverifiable, **sequentially with
      backoff**. The 2026-10-01 Wayback pass recovered 45 (21 verified, 22
      corrected, 2 refuted), but 8 parallel agents hit archive.org rate limits;
      rockets got none.
- [ ] 🤖 Re-verify the legacy KPI **observations** (pilot-2025 values); only events
      were re-verified.
- [ ] Yearly upkeep: when GCB 2026 is released (around November), update
      `DATA_URL` in `gather/collectors/climate_emissions.py`. Watch for WHO's next GHE
      round; health data ends in 2021, so its KPI is labelled "Stale".
- [ ] 🤖 Check The Bend's next assessment (yellow on 2026-09-30, label
      "Progressing: GHG 54.1 GtCO2e..."). Its rationale counted slowing **CO₂**
      growth as progress on a **total-GHG** milestone. It is re-assessed
      automatically once new Bend evidence arrives (`ledger.py stale`), and the
      assess prompt now asks for the milestone's own quantity or a named proxy.
      Verify that the new record judges it on total GHG (EDGAR).
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
- [ ] Observation **withdrawal** record (today a wrong value can only be
      outranked by a better one).
- [ ] Dedup is an LLM job plus a heuristic; reworded near-duplicates can slip
      through (fix with `supersedes`).

## Views / checks

- [ ] Round-up Quick Reference from snapshot KPI headlines and assessments
      (today the round-up only summarizes bulletin prose).
- [ ] Bulletin gate is lexical (a number must occur in the snapshot, a URL
      must be a snapshot source). The next step is tying each footnote to a
      record id.
- [ ] Snapshot size (~136 KB per weekly section): gzip, or pin + regenerate.
- [ ] Dashboard size grows with the ledger (~830 KB live; events repeat under each
      of their topics), and every period page is a frozen copy (~650-700 KB each,
      committed to the data repo): fine for half-years, too much for weekly
      periods. Split per section, or gzip/trim period pages, before weekly roundups.

## Roadmap

- [ ] weekly cadence running · [ ] reference source list per endeavor (it
      would seed intake) · [ ] publishing (Substack, automated Twitter) ·
      [ ] expert review + errata (this maps onto `supersedes`)
