# TODO — Grand Endeavors

Current backlog only; finished work lives in git history and DESIGN.md.
Architecture: DESIGN.md · status rubric: STATUS.md · views: EXPLORER.md ·
data: github.com/pasky/grand-endeavors-data (`./data`).
🤖 = can be done by agents without the owner in the loop.

## Owner decisions

- [ ] **A milestone beyond "The Blue Collar Shift"?** It was tightened on
      2026-10-01 (30 working days, no teleoperation, ≤1 disclosed intervention
      per shift, ≥90% throughput); it is now yellow. Open question: should
      Chinese "dark factories" count? They use special-purpose automation, not
      general-purpose robots, so not under the current wording. A possible
      later milestone is "The Dark Line": a production line staffed only by
      general-purpose robots runs a full week with no humans on the floor.
- [ ] **Scheduling budget**: how often each section's gather runs (a full
      8-item climate gather ≈ 75 min of agent time), and which model per stage
      (e.g. a cheaper intake model, a strong verifier).
- [ ] Finish `TEMPLATE.md` (the newsletter intro still ends in `..todo..`).

## Operations

- [ ] Scheduling: cron or systemd timer for `gather.sh <section>`, then
      `bulletin.sh` + `roundup.sh` after each cutoff, then `git -C data push`.
      Weekly cutoff = Sunday + 2 days.
- [ ] Gather all sections. Only climate (full), fusion (KPI) and the
      re-verification pass have run; the other sections' news is all
      2025-report history.
- [x] Dashboard published (owner symlink: pasky.or.cz/grand-endeavors/dashboard.html).
      `gather.sh` regenerates it after each run. Still open: a hosted Datasette
      (`datasette publish`), and linking the dashboard from round-ups and the
      data repo README.

## Data quality

- [ ] 🤖 Retry the legacy events that could not be verified (dead, paywalled or
      JS-only pages) via Wayback snapshots.
- [ ] 🤖 Re-verify the legacy KPI **observations** (pilot-2025 values); only events
      were re-verified.
- [ ] 🤖 Health KPI data: a collector for WHO GHE HALE (median-country +
      global). The health KPI is "Unassessed" until then.
- [ ] 🤖 The Bend: a GCB global fossil CO₂ annual series (for charts + KPI-like
      tracking of the milestone).
- [ ] Rockets KPI: a `cost-to-leo-best` history (only one point). Needs a
      sourcing decision: list prices are sparse and inconsistent.
- [ ] Robots-hardware KPI ("largest single-site fleet"): no public series; it
      needs a definition that can actually be observed.
- [ ] Observation **withdrawal** record (today a wrong value can only be
      outranked by a better one).
- [ ] Dedup is an LLM job plus a heuristic; reworded near-duplicates can slip
      through (fix with `supersedes`).

## Views / checks

- [ ] 🤖 validate.py: footnote/ref checks ignore duplicate or indented
      definitions and shortcut refs.
- [ ] Round-up Quick Reference from snapshot KPI headlines and assessments
      (today the round-up only summarizes bulletin prose).
- [ ] Bulletin gate is lexical (a number must occur in the snapshot, a URL
      must be a snapshot source). The next step is tying each footnote to a
      record id.
- [ ] Snapshot size (~136 KB per weekly section): gzip, or pin + regenerate.
- [ ] Dashboard size grows with the ledger; split per section at some point.

## Roadmap

- [ ] weekly cadence running · [ ] reference source list per endeavor (it
      would seed intake) · [ ] publishing (Substack, automated Twitter) ·
      [ ] expert review + errata (this maps onto `supersedes`)
