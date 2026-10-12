# Reference source lists

One file per section (`<section>.yaml`): the primary sources worth watching for each
watch item (KPI, milestones, challenges, `beyond`). `gather/gather.sh` shows every intake
agent the entries tagged with its item, plus the section-wide ones
(`uv run gather/sources.py list <section> <topic>`). They are a starting point, not a
whitelist: agents still search the open web, and the verifier still checks every claim
at its source.

```yaml
sources:
  - name: NOAA GML — Trends in Atmospheric CO₂     # organization first
    url: https://gml.noaa.gov/ccgg/trends/         # the exact page, verified by visiting it
    items: [kpi]               # watch items (ledger topic tags), or ["*"] = section-wide
    covers: What it publishes, concretely (dataset, kind of announcements).
    cadence: monthly (~5th of the following month)   # release rhythm / typical month
    tier: primary              # primary | secondary | news
    collector: true            # optional: already fetched by gather/collectors/<section>.py
    note: bot-blocked          # optional: e.g. the page blocks plain fetches
```

Tiers: **primary** = the originating agency, lab, company, journal, regulator or
dataset; **secondary** = reputable aggregator, analyst or tracker; **news** =
specialist outlet or newsletter (no general news, no content farms).

Curation rules:
- Prefer stable pages that list new items over time (data/release pages, newsrooms,
  journal "latest" pages, preprint listings, trackers), not one-off articles. A yearly
  edition URL (e.g. a report's `-2026` page) is allowed when no series page exists;
  `covers` says so, and it is bumped when the next edition appears.
- One entry per URL; tag it with every item it serves. Use `*` sparingly.
- Every URL was visited when added (header: review date). `note: bot-blocked` marks pages
  that refuse plain fetches but were confirmed otherwise (search results, a reader proxy).
- Tags must match framework.yaml's slugs; a new milestone/challenge needs its sources
  here, a removed one must be untagged (`uv run gather/sources.py check`; `gather/tests/test_sources.py` fails
  otherwise).
