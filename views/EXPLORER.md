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
  endeavor (under its group, e.g. Robots and Automation): its icon and title;
  the KPI status dot with the latest value of its headline metric (the first
  required one, or one required from a later period) and a sparkline; one
  status dot per milestone (hover: name and status label); `+N` = events that
  became known in the last 30 days. Clicking shows that endeavor in the middle.
- **Middle, one pane at a time**: the overview by default, or the endeavor
  clicked. Switching is pure CSS (`:target`, `:has()`; the page has no
  JavaScript), so every pane and event has a URL (`#climate`,
  `#ev-climate-<id>`, `#t-climate-milestone-the-bend`): a link to an event
  opens its endeavor, unfolds the event and highlights it. A browser without
  `:has()` shows all panes one below another.
- **Right, the news stream**: the 100 most recently *known* events across all
  endeavors, newest first, grouped by day, plus the **status changes**
  (KPI/milestone status changed, or first assessed; a same-day flip back is
  not a change) over the same span. Each item links to the event or target
  in its pane. "Major only" keeps significance-3 events and status changes;
  while an endeavor is shown, other endeavors' news is dimmed and "this
  endeavor only" hides it.

**Overview pane**: the tagline, the as-of date, the manifesto, a folded "How
to read this page" (the status colours, KPI vs milestone status, verified vs
legacy, what "as of" means), then **At a glance**: a card per endeavor (KPI
definition, latest value + sparkline, KPI status label, milestones with their
dots, event count, new events, and a bar chart of events per week over the
last 16 weeks).

**Endeavor pane** (groups such as Robots and Automation show their intro on
each of their sections' panes): event count, new events, the date the latest
became known and the weekly activity bars; the intro, then:
- **KPI**: its definition, and its status line (the latest assessment's
  label), which expands to the assessment and the KPI-tagged events (below);
  then, always shown:
  - **KPI tiles**, one per required metric (others fold under "more
    registered metrics"). Each tile shows the latest value and its
    observation period; when it became known, and a `source` link; the change
    **vs the previous observation**, with a ⚠ when it is not comparable
    (different calendar month: seasonal cycle not removed; different
    granularity; same observation revised); for monthly series, the
    like-for-like change vs the same month a year ago; a sparkline of one
    granularity; "next expected by …", **OVERDUE**, or **no data yet**. A
    `legacy` badge marks values from the unverified 2025 report.
  - the **assessment** (expanded from the status line): label, rationale and
    its structured basis (assessed quantity, window, benchmark, …), its cited
    evidence, and the other KPI-tagged events.
- **Milestone Countdown**: per milestone its status dot, name and definition,
  then the status label, assessment date and event count. Expanded: the
  precise criteria, the assessment (rationale; ETA, path, blockers; the
  previous status), the **cited evidence** (every event the assessment cites,
  whatever its topic tags; one superseded or withdrawn since is flagged), then
  the milestone's latest 5 other events, with a link to the rest in the event
  log. Statuses follow
  gather/RUBRIC.md: 🟢 green, 🟡 yellow, 🔴 red, ✅ achieved (a green dot with a
  check mark), ⚪ unknown ("Unassessed"), dashed = not yet assessed.
- **Open challenges** (or fusion's Tech Tree): name, definition and event
  count; expanded, the details and events. Challenges are not assessed.
- Folded at the end: **Beyond the framework** events, **events under no
  current topic** (tags the framework no longer lists, e.g. after a change; never silently
  dropped) and the **latest events** (with a link to the event log).

Each event shows the claim, event date, kind (achievement, announcement,
projection, setback, …), significance (●●○), when it became known, topic tags,
source links and a verification badge (verified / corrected / **legacy**). It
is listed under every topic it is tagged with. Superseded and withdrawn
records are not shown, except as cited evidence (flagged); the current
version is.

**Event logs** (`events-<section>.html`, next to the page): every effective
event of the endeavor, newest first, grouped by topic in framework order. An
event is shown in full under its first topic, with its `#ev-<section>-<id>`
anchor, and as a one-line link under later ones. Lifecycle links (`relates`,
`supersedes`) on both pages land there (or say "withdrawn"). The split keeps
the event history off the front page: it carries the assessments' cited
evidence (uncapped, it is what the status rests on) and a few latest events per
topic (about 580 KB, 120 KB gzipped, in October 2026). The sparklines still
carry each tile's whole series.

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
