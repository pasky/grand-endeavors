# Explorer guide

The explorer is a set of read-only **views of the ledger** (the data repo in
`./data`). Nothing in it is canonical. Everything is rebuilt from the ledger
on demand into `build/`, which is gitignored and is the published site
(pasky.or.cz/grand-endeavors/ is a symlink to the main checkout's `build/`).
There are two views over the same data:

| | Dashboard (`build/index.html`) | Datasette (`build/ledger.sqlite`) |
|---|---|---|
| What it is | One curated, self-contained HTML page: the project's front page (plus a per-endeavor event log) | A browsable database with a web UI |
| Best for | A first-time visitor; "where do we stand?" at a glance; sharing | Digging, auditing, ad-hoc questions, exports |
| Needs | Any browser; works offline; email it or host it anywhere | A local server (`uvx datasette ...`) |
| Interaction | Read; every line expands to its detail | Filter, facet, sort, run SQL, export CSV/JSON |
| Shows | The *current* picture: effective records only | Everything, incl. superseded records and legacy rows, with flags |

## Setup (once)

```sh
git clone https://github.com/pasky/grand-endeavors.git && cd grand-endeavors
git clone https://github.com/pasky/grand-endeavors-data.git data   # or set GE_DATA=/path/to/data
```

## Dashboard

```sh
uv run views/explore.py site                            # -> build/: index.html, event logs, period pages, ledger.sqlite (gather.sh runs this)
uv run views/explore.py dashboard --as-of 2026-07-14    # just the pages (+ event logs), as the ledger knew the world on that date
(cd data && uv run ../views/explore.py period pilot-26H1)  # freeze a period page (roundup.sh runs this)
```

The page is the **maximal source of truth** for a reader: it carries the
framework itself (`framework.yaml`: tagline, manifesto, every endeavor's intro,
KPI, milestone and challenge definitions), so a first-time visitor needs
nothing else. Every line expands to its detail.

**Layout**: three columns (on narrow screens the news drops below, and on a
phone the navigation becomes a strip on top).
- **Left, the navigation**: "Introduction & overview", then one item per
  endeavor: its icon and title, and how long ago its latest news was published
  (`8d ago`; filled = within a week, tinted = within a month, outlined =
  older); the KPI status dot with the latest value of its headline metric (the
  first required one, or one required from a later period) and its series
  (labelled with the year it starts); one status dot per milestone (hover:
  name and status label), joined by a line when the milestones are a sequence. An endeavor of several sections (Robots and
  Automation) is one item with a sub-item per section (Software, Hardware);
  the supplemental sections are listed apart, under "Supplemental", by title
  and news freshness only (no KPI, so no one value stands for them).
  Clicking shows that endeavor in the middle.
- **Middle, one pane at a time**: the overview by default, or the endeavor
  clicked. Switching is pure CSS (`:target`, `:has()`; the page has no
  JavaScript), so every pane, section and target has a URL
  (`#robots-and-automation`, `#robots-software`, `#climate`,
  `#t-climate-milestone-the-bend`): a link to it opens its endeavor (and
  unfolds the target). Events have theirs in the event logs (below,
  `events-climate.html#ev-climate-<id>`, highlighted when linked). A browser
  without `:has()` shows all panes one below another.
- **Right, the news stream**: the 100 most recently *published* events across
  all endeavors, newest first, grouped by day, plus the **status changes**
  (KPI/milestone status changed, or first assessed; a same-day flip back is
  not a change) over the same span (all of them while the ledger has fewer
  events). Only endeavors with a pane are included (a period page's frozen
  framework may lack some). An event links to its entry in the endeavor's
  event log, a status change to its target in the endeavor's pane. "Major only" keeps significance-3 events and status changes;
  while an endeavor is shown, other endeavors' news is dimmed and "this
  endeavor only" hides it.

**Overview pane**: the tagline, the as-of date, the manifesto, a folded "How
to read this page" (the status colours, KPI vs milestone status, verified vs
legacy, what "as of" means), then **At a glance**: a card per endeavor (Robots
and Automation: its two sections side by side) with how fresh its news is, the
KPI definition, the latest value and its series, the KPI status label, the
milestones with their dots (a sequence: joined by a line), the event and challenge counts, and the news per
week over the last 16 weeks; the supplemental sections' cards follow apart,
with their first four indicators (latest value, the period it is for) and their
three latest major (significance 3) events instead of a KPI.

**Endeavor pane**: its event count, latest news and news per week; the intro
(Robots and Automation: the group intro, links to its sections, then each
section with its own activity line), then:
- **KPI**, top down. Shown: the headline tile (the required metric; it names
  what is measured) next to the **status line** (the latest assessment's label)
  and its **rationale**. Folded:
  - **how the KPI is built**, opened by the KPI's framework definition (its
    precise wording; without a `kpi_about`, the fold holds just that)
    (framework.yaml `kpi_about`: markdown, or
    `{summary, sections: [{title, text, chart, metrics}]}`): the derivation
    story, section by section, each with its chart (a `views/kpi_charts.py`
    id) and the tiles of the metrics it explains. Software's charts: the KPI
    and its parts over time with METR's own measurements and the raw indices
    (ECI, RLI) on right-hand scales; the ECI → METR calibration fit
    (`gather/collectors/robots_software_calibration.json`, written by the
    collector's `--calibrate --write`); the RLI conversion (METR's
    success-vs-length curve over RLI's project lengths). Static SVG; hovering a
    point shows the model and value (tooltips);
  - **how the status was judged** (the assessment basis), **evidence and
    news** (the cited evidence, newest first, then the other KPI-tagged
    events) and **more metrics we track** (the section's other metrics, in
    their `metric-labels.yaml` order; precursor series show with their milestone):
  - **KPI tiles**: a tile shows the metric's name (`views/metric-labels.yaml`;
    hover: its id and full registry definition), the latest value (minutes
    from 2 hours on shown as hours, a value in hours under 1 hour as minutes, a ladder
    metric (`_levels` in metric-labels.yaml) as "1 of 4" and the rung's name; hover: the
    recorded value), the period it is for (hover: when it was published), a `source` link and a `legacy`
    badge for values from the unverified 2025 report; for monthly series the
    like-for-like change vs the same month a year earlier (the change vs the
    previous observation is not shown: the series shows the trend, and
    consecutive months are not comparable); the series of one granularity
    (hovering shows a point's value and date in place of the axis labels; a
    long series is thinned to 60 hover points, the nav's tiny ones show them as tooltips)
    with its first and last date under it; and "next update due by …",
    "update overdue since …" (the tile is then dashed) or "no data yet".
    The change vs the previous observation, with its comparability flag,
    stays in Datasette (`latest_kpi`).
  - the **assessment basis** (a milestone's: expanded from its status line):
    the previous status if it changed, the outlook (the ETA: median year + 80%
    range, or the chance by 2100, and its cruxes; path, blockers, or why it is
    unassessed) and, folded, how it was assessed (the assessed quantity, data
    window, benchmark, rubric rule, ETA method and calculation, …), rendered as
    structure: nested objects as nested lists, a date → number object as a row
    of data cells, numbers at 4 significant digits.
- **Milestone Countdown**: whether the milestones are a **sequence** (each
  expected after the one before; `milestones_order: sequence` in
  framework.yaml: Rockets, Fusion, Climate) or **independent fronts** (the
  default), then the **timeline**: every milestone's ETA on one time axis,
  a dot at the median year (hollow: after 2100) and a bar over the 80% range,
  coloured by status (an achieved one sits at "now"; one without an ETA says
  so). A sequence keeps the framework order, with an arrow from each
  milestone to the next (pointing back when a step's median comes before its
  predecessor's); independent fronts are sorted soonest first (achieved, then
  by median year, then by the chance by 2100), in the timeline and the cards. The axis runs
  from the as-of date to 2100, compressed (log of 1 + years from now / 2), so
  near and far milestones fit: next year gets room, 2075 vs 2080 does not;
  medians after 2100 sit in a hatched zone at the right end (a range with
  no 10% year by 2100 has no bar). A phone keeps
  the 2030 and 2050 labels only. Milestone names link to their entries.
  Then the entries: a sequence as a numbered rail, independent fronts as
  cards in columns (an opened card takes a row of its own, and the cards left
  on the row before it widen to fill it; a trailing card keeps the column width). Each shows its status dot, name and
  definition, then the status label, assessment date and event count. Expanded: the
  precise criteria, **closest so far** (the tiles of its framework.yaml `precursors:`
  series), the assessment (as for the KPI), then folded, as for the KPI,
  **evidence and news**: the **cited evidence** (every event the assessment cites,
  whatever its topic tags; one superseded or withdrawn since is flagged), then
  the milestone's latest 5 other events, with a link to the rest in the event
  log. Statuses follow
  gather/RUBRIC.md: 🟢 green, 🟡 yellow, 🔴 red, ✅ achieved (a green dot with a
  check mark), ⚪ unknown ("Unassessed"), dashed = not yet assessed.
- **Open challenges** (or fusion's Tech Tree): name, definition and event
  count; expanded, the details and events. Challenges are not assessed.
- A **supplemental section** (no KPI, milestones or challenges; nothing in it
  is assessed) shows instead its **indicators** (every registry metric, tiles
  as above; series that only feed another indicator, listed under `_inputs` in
  `views/metric-labels.yaml`, e.g. the two sides of the Q-Day gap, fold under
  "Fine print" and stay off the overview card) and its **notable developments**: the 10 latest major
  (significance 3) events by event date, with a link to the rest in the event log.
- Folded at the end: **Beyond the framework** events, **events under no
  current topic** (tags the framework no longer lists, e.g. after a change; never silently
  dropped) and the **latest news** (with a link to the event log).

Every expandable line has a round chevron button in front (it turns down
when open).

Each event shows the claim, event date, kind (achievement, announcement,
projection, setback, …), significance (●●○), when it was published, topic
tags, source links and a verification badge (verified / corrected /
**legacy**). It is listed under every topic it is tagged with. Lifecycle
links (`relates`: updates, follows up on, confirms, delays, retracts) show the
linked event's date and claim and jump to its entry in the event log (to its
corrected version if it was superseded; "since withdrawn" otherwise); a
correction (`supersedes`) shows the claim it replaced, struck through.
Superseded and withdrawn records are not shown, except as cited evidence
(flagged); the current version is.

**Event logs** (`events-<section>.html`, next to the page): every effective
event of the endeavor, newest first, grouped by topic in framework order. An
event is shown in full under its first topic, with its `#ev-<section>-<id>`
anchor, and as a one-line link under later ones. Lifecycle links (`relates`,
`supersedes`) on both pages land there (or say "withdrawn"). The split keeps
the event history off the front page: it carries the assessments' cited
evidence (uncapped, it is what the status rests on) and a few latest events per
topic (about 580 KB, 120 KB gzipped, in October 2026). The sparklines still
carry each tile's whole series.

**Metric names**: `views/metric-labels.yaml` maps each metric id to a short
name. A metric without one is shown by the first clause of its definition (else
its id) and `explore.py` warns: add a label when registering a metric.

**Footer** (under every pane): record counts, the metric **gaps** (overdue or
never observed; never hidden), links to the earlier **period pages**, and the
data/code repos.

**`--as-of`** applies the ledger's time rule: only records *published* by that
date are included, and "overdue" is judged against that date. Two people
building the same as-of date from the same data commit get the same page.
That makes it the right way to answer "what did we know on date X?"

### Period pages

`explore.py period <period-dir>` freezes `<period-dir>/index.html` and its event
logs in the data repo (published as `build/<period-dir>/`): the dashboard as of the
period's cutoff, rendered with the framework in force for that period
(`<period-dir>/framework.yaml`, copied from the mechanism repo on the first run
and kept). An existing page is never replaced silently: a re-run of roundup.sh
keeps it, and `--force` (with a `--note` saying why) regenerates it. Sections without a bulletin in that period are marked "not
covered". The page is frozen because a regenerated as-of view drifts: later
corrections of facts that were public by the cutoff, and assessments written
retrospectively, enter it. pilot-2025 and pilot-26H1 were reconstructed this
way on 2026-10-02 (with the framework of 2026-01-05) and say so; they predate
the event logs (one page, every event under each topic). W38, a pipeline test
run, has no page.

Size: a weekly period page with its event logs is about 1.2 MB, but consecutive
weeks differ little, so git stores them as deltas: twelve weekly pages measured
9.4 MB on disk and 240 KB packed (snapshots: 12 weeks of all eight sections,
5 MB on disk, 150 KB packed). Keep both as plain text; gzip would defeat the deltas.

## Datasette

```sh
uv run views/explore.py build                             # -> build/ledger.sqlite + metadata.json
uvx datasette build/ledger.sqlite -m build/metadata.json  # http://127.0.0.1:8001
```

The `--as-of` flag works for `build` too. Useful starting points:
- **Canned queries** (front page):
  - *KPI dashboard*: latest value, change with comparability flag, year-ago
    change and schedule per metric;
  - *Events by milestone*: e.g. topic `milestone:the-bend`;
  - *Lifecycle threads*: event pairs linked via `relates` (update, delay,
    retraction …) or `supersedes` (corrections);
  - *Legacy vs verified*: how much of each section rests on unverified
    legacy records;
  - *Overdue metrics*.
- **Views**:
  - `current_events` / `current_obs`: effective records only, i.e. what the
    dashboard shows;
  - `latest_kpi`, `milestone_status` (latest assessment and its predecessor),
    `recent_events`, `gaps`.
- **Tables**:
  - `events`: all records, incl. superseded ones. `effective=0` and
    `superseded_by` show the correction trail; JSON columns keep nested
    fields.
  - `event_topics`, `event_sources`, `event_relates`, `event_supersedes`;
  - `observations`: every row incl. revisions and legacy values;
    `tier`/`effective` show which row wins;
  - `assessments`: the full history, incl. pre-rubric records;
  - `metrics`: the registry, with `next_expected`/`overdue`;
  - `sections`, `topics`.
- **Click-throughs**: click a column value to facet (e.g. `verification_status`
  or `kind`); use "View and edit SQL" for anything else. Every result has
  CSV/JSON export links.

Example SQL:

```sql
-- What re-verification changed in climate (old claim -> new claim)
SELECT s.event_id AS new, s.superseded_id AS old, n.verification_status, o.claim AS old_claim, n.claim AS new_claim
FROM event_supersedes s JOIN events n ON n.section = s.section AND n.id = s.event_id
JOIN events o ON o.section = s.section AND o.id = s.superseded_id
WHERE s.section = 'climate';

-- Major verified news published in September 2026, all endeavors
SELECT section, date, claim FROM current_events
WHERE significance = 3 AND verification_status != 'legacy' AND known_at >= '2026-09-01'
ORDER BY known_at DESC;
```

(Column names are in each table's page header; `explore.py` holds the schema.)

## Which one when

- A weekly look, or sending someone "where are we": **dashboard**.
- "Why is The Bend yellow?", "what did re-verification correct?", "which
  sources do we lean on most?", or exporting a series: **Datasette**.
- "What did we know when the 26H1 bulletin was cut?": either, with
  `--as-of 2026-07-14`.
- Bulletins (`data/pilot-*/<section>.md`) are the third, narrative view, cut
  at a fixed date with a frozen snapshot; the period page is the dashboard at
  that cutoff.

## Publishing

- `explore.py site` (run by gather.sh after each gather) rewrites `build/`,
  which is the published directory; the old `dashboard.html` URL redirects to
  the new front page.
- **Previews** (side-agent worktrees): after a change visible on the site, run
  `uv run views/explore.py site` in your worktree; the preview is at
  `https://pasky.or.cz/grand-endeavors/<slot>/` (`<slot>` = the worktree directory
  name minus `<repo>-agent-`, e.g. `worktree-0002`). Give the owner that URL. The
  side-agent start/finish scripts create the link and remove it after the merge,
  then rebuild the published site.
- Datasette can be published read-only with `datasette publish` (Cloud Run,
  Fly, Vercel); not set up yet (TODO).
