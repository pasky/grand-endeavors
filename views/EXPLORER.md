# Explorer guide

The explorer is a set of read-only **views of the ledger** (the data repo in
`./data`). Nothing in it is canonical. Everything is rebuilt from the ledger
on demand into `build/`, which is gitignored. There are two views over the same
data:

| | Dashboard (`build/dashboard.html`) | Datasette (`build/ledger.sqlite`) |
|---|---|---|
| What it is | One curated, self-contained HTML page | A browsable database with a web UI |
| Best for | "Where do we stand?" at a glance; sharing | Digging, auditing, ad-hoc questions, exports |
| Needs | Any browser; works offline; email it or host it anywhere | A local server (`uvx datasette ...`) |
| Interaction | Read and click links (older events fold open) | Filter, facet, sort, run SQL, export CSV/JSON |
| Shows | The *current* picture: effective records only | Everything, incl. superseded records and legacy rows, with flags |

## Setup (once)

```sh
git clone https://github.com/pasky/grand-endeavors.git && cd grand-endeavors
git clone https://github.com/pasky/grand-endeavors-data.git data   # or set GE_DATA=/path/to/data
```

## Dashboard

```sh
uv run views/explore.py dashboard                       # -> build/dashboard.html (as of today)
uv run views/explore.py dashboard --as-of 2026-07-14    # the world as the ledger knew it on that date
xdg-open build/dashboard.html                           # or open it in any browser
```

**Header**: the as-of date, record counts (verified vs legacy), and a **Gaps**
list: KPI metrics that are overdue (the next release is past due given the
registry's cadence and release lag) or that have never been observed. Gaps are
never hidden; an unfilled datapoint shows as unfilled.

**Per endeavor** (in README order):
- **KPI tiles**, one per required metric (others fold under "more registered
  metrics"). Each tile shows:
  - the latest value and its observation period;
  - when the value became known, and a `source` link;
  - the change **vs the previous observation**, with a ⚠ when it is not
    comparable (different calendar month: seasonal cycle not removed;
    different granularity; same observation revised);
  - for monthly series, the like-for-like change vs the same month a year ago;
  - a sparkline of one granularity;
  - "next expected by …", **OVERDUE**, or **no data yet**.

  A `legacy` badge marks values from the unverified 2025 report.
- **KPI assessment and milestone list**: the current status per gather/RUBRIC.md:
  - 🟢 green, 🟡 yellow, 🔴 red;
  - ✅ achieved (milestones only; a green dot with a check mark, as in bulletins);
  - ⚪ **Unassessed** (the rubric can't judge it: no KPI spec or no data).

  The label starts with the verdict word ("Off track", "Progressing",
  "Blocked", …), then the assessment date, the previous status (e.g. "was
  yellow on …") and the number of evidence events. Challenges are listed with
  their event counts; they are not assessed.
- **Latest events**, newest first. Each shows the claim, event date, kind
  (achievement, announcement, projection, setback, …), significance (●●○),
  when it became known, topic tags and source links. A badge shows
  verification: verified / corrected / **legacy**. Older events fold away by
  significance. Superseded and withdrawn records are not shown here; the
  current version is.

**`--as-of`** applies the ledger's time rule: only records *published* by that
date are included, and "overdue" is judged against that date. Two people
building the same as-of date from the same data commit get the same page.
That makes it the right way to answer "what did we know on date X?"

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
  at a fixed date with a frozen snapshot.

## Publishing (not set up yet)

- The dashboard is one static file: it can be pushed to GitHub Pages of the
  data repo after each gather.
- Datasette can be published read-only with `datasette publish` (Cloud Run,
  Fly, Vercel).

Both are in TODO under "Publish the explorer".
