# Five Grand Endeavors

Tracking humanity's progress in five grand endeavors — our biggest ongoing R&D projects:

* Robots (and Automation overall)
* Rockets (and Space overall)
* Fusion (and Energy overall)
* Health (and Lifespan overall)
* Climate (and Environment overall)

**→ [pasky.or.cz/grand-endeavors](https://pasky.or.cz/grand-endeavors/)**: the live dashboard. It covers what we track and why, every KPI, milestone and challenge definition, and where each endeavor stands today.

The initial purpose of this project is using AI to automatically compose a regular trustworthy report to "the Board of Humanity" about major progress in these areas.

**Status:** Experimental draft.
* [x] We have a draft version of the endeavors definition and reporting structure. *(We expect to still iterate on it significantly based on early experience and feedback.)*
* [ ] *(work in progress)* We are piloting the reporting structure on a summary 2025 report.
* [ ] *(work in progress)* We are building an automatic report drafting harness.
* [ ] We have the weekly report cadence running.
* [ ] We have a reference list of sources to follow for each endeavor.
* [ ] We have a publishing infrastructure set up (most likely Substack and automated Twitter account).
* [ ] We have a drafting / feedback infrastructure for early expert reviews and errata.

## This repository

- **[framework.yaml](framework.yaml)**: the endeavor definitions (manifesto, KPIs, milestones, challenges), the single source for the pipeline and the dashboard
- [DESIGN.md](DESIGN.md): system design (ledger, gather, bulletins) · [gather/RUBRIC.md](gather/RUBRIC.md): status rubric · [views/EXPLORER.md](views/EXPLORER.md): dashboard and Datasette · [TODO.md](TODO.md): backlog
- Data (ledger, bulletins): [github.com/pasky/grand-endeavors-data](https://github.com/pasky/grand-endeavors-data)
