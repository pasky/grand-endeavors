# Explorer guide

The explorer is a set of read-only **views of the ledger** (the data repo in
`./data`). Nothing in it is canonical. Everything is rebuilt from the ledger
on demand into `build/`, which is gitignored and is the published site
(pasky.or.cz/grand-endeavors/ is a symlink to the main checkout's `build/`).
There are two views over the same data:

| | Dashboard (`build/index.html`) | Datasette (`build/ledger.sqlite`) |
|---|---|---|
| What it is | One curated, self-contained HTML page: the project's front page | A browsable database with a web UI |
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
uv run views/explore.py site                            # -> build/: index.html, period pages, ledger.sqlite (gather.sh runs this)
uv run views/explore.py dashboard --as-of 2026-07-14    # just the page, as the ledger knew the world on that date
(cd data && uv run ../views/explore.py period pilot-26H1)  # freeze a period page (roundup.sh runs this)
```

The page is the **maximal source of truth** for a reader: it carries the
framework itself (`framework.yaml`: tagline, manifesto, every endeavor's intro,
KPI, milestone and challenge definitions), so a first-time visitor needs
nothing else. By default it reads like the old README with a status on every
line; every line expands to its detail.

**Header**: the tagline, the as-of date, the manifesto, and a folded "How to
read this page" (the status colours, KPI vs milestone status, verified vs
legacy, what "as of" means).

**Per endeavor** (in framework.yaml order; groups such as Robots and
Automation carry their own intro):
- **KPI**: its definition, and one summary line with the latest value of each
  required metric and the KPI status. Expanded:
  - **KPI tiles**, one per required metric (others fold under "more
    registered metrics"). Each tile shows the latest value and its
    observation period; when it became known, and a `source` link; the change
    **vs the previous observation**, with a ⚠ when it is not comparable
    (different calendar month: seasonal cycle not removed; different
    granularity; same observation revised); for monthly series, the
    like-for-like change vs the same month a year ago; a sparkline of one
    granularity; "next expected by …", **OVERDUE**, or **no data yet**. A
    `legacy` badge marks values from the unverified 2025 report.
  - the **assessment**: label, rationale and its structured basis (assessed
    quantity, window, benchmark, …), its cited evidence, and the other
    KPI-tagged events.
- **Milestone Countdown**: per milestone its status dot, name and definition,
  then the status label, assessment date and event count. Expanded: the
  precise criteria, the assessment (rationale; ETA, path, blockers; the
  previous status), the **cited evidence** (every event the assessment cites,
  whatever its topic tags; one superseded or withdrawn since is flagged), then
  the milestone's other events. Statuses follow
  gather/RUBRIC.md: 🟢 green, 🟡 yellow, 🔴 red, ✅ achieved (a green dot with a
  check mark), ⚪ unknown ("Unassessed"), dashed = not yet assessed.
- **Open challenges** (or fusion's Tech Tree): name, definition and event
  count; expanded, the details and events. Challenges are not assessed.
- Folded at the end: **Beyond the framework** events, **events under no
  current topic** (tags the framework no longer lists, e.g. after a change; never silently
  dropped) and the **latest events**.

Each event shows the claim, event date, kind (achievement, announcement,
projection, setback, …), significance (●●○), when it became known, topic tags,
source links and a verification badge (verified / corrected / **legacy**). It
is listed under every topic it is tagged with; lifecycle links (`relates`,
`supersedes`) jump to its first occurrence (or say "withdrawn"). Superseded
and withdrawn records are not shown, except as cited evidence (flagged); the
current version is.

**Footer**: record counts, the metric **gaps** (overdue or never observed;
never hidden), links to the earlier **period pages**, and the data/code repos.

**`--as-of`** applies the ledger's time rule: only records *published* by that
date are included, and "overdue" is judged against that date. Two people
building the same as-of date from the same data commit get the same page.
That makes it the right way to answer "what did we know on date X?"

### Period pages

`explore.py period <period-dir>` freezes `<period-dir>/index.html` in the data
repo (published as `build/<period-dir>/index.html`): the dashboard as of the
period's cutoff, rendered with the framework in force for that period
(`<period-dir>/framework.yaml`, copied from the mechanism repo on the first run
and kept). An existing page is never replaced silently: a re-run of roundup.sh
keeps it, and `--force` (with a `--note` saying why) regenerates it. Sections without a bulletin in that period are marked "not
covered". The page is frozen because a regenerated as-of view drifts: later
corrections of facts that were public by the cutoff, and assessments written
retrospectively, enter it. pilot-2025 and pilot-26H1 were reconstructed this
way on 2026-10-02 (with the framework of 2026-01-05) and say so; W38, a
pipeline test run, has no page.

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
- Datasette can be published read-only with `datasette publish` (Cloud Run,
  Fly, Vercel); not set up yet (TODO).
