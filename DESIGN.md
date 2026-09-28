# Grand Endeavors — system design

Status: adopted 2026-09 (replaces the period-centric `generate.sh` pipeline).

## 1. Principle: the ledger is the product

Grand Endeavors tracks humanity's progress on a handful of endeavors (README.md).
The primary artifact is a continuously growing, verified **ledger** of what is
known and when it became known. Everything readers see is a **view** of it:

- a live **explorer/dashboard** (latest state, history, gaps, sources), and
- **bulletins** at a fixed cadence (weekly, half-year, annual, …): a snapshot of
  the ledger at a deterministic cutoff, with a narrative on top.

Data gathering therefore runs on its own schedule. Today it is ad hoc and manual;
it becomes progressively more continuous. It is independent of bulletin frequency.
News (events) matters more than KPI numbers: KPIs move slowly, and most of the
story is what happened.

```
 sources ──► GATHER (per section, own cadence) ──► LEDGER (git, append-only) ──► VIEWS
   web        intake agents (LLM, per watch item)    events/      *.jsonl      explorer (SQLite/Datasette)
   data files collectors (deterministic scripts)     observations/*.csv        bulletins (snapshot @ cutoff
              verify (fresh agent) → merge           assessments/ *.jsonl        → draft → edit → gate)
              assess (milestone status)              state/ rejected/          round-up (period README)
```

## 2. Time semantics (one rule set everywhere)

Every record carries:
- **event/obs date**: when the thing happened, or which period a number describes.
- **published**: when it became public, with `published_basis`:
  - `source`: the source states it (article date, report date).
  - `rule`: estimated as obs end + the registry's `release_lag_days` (regular
    data releases such as NOAA monthly means), clamped to ≤ retrieved.
  - `seen`: unknown; we use the date we first retrieved it (an upper bound).
- **retrieved**: when we fetched it.

`known_at = published`. A value **as of T** is the latest record with
`known_at ≤ T`. Source revisions are appended as new rows, never overwritten.

**Bulletin cutoff** = period end + lag (weekly/`YYYY-Www`: 2 days;
monthly: 7 days; quarter/half/year: 14 days). A bulletin shows the ledger as of
its cutoff. "New in this bulletin" = records with `known_at` in
(cutoff of the previous period of the same kind, this cutoff]. Nothing
published after the cutoff back-fills an old bulletin: it is news for the next
one. A retrospective or late run produces exactly the same bulletin as an
on-time run, given the same ledger.

## 3. Ledger layout and record schemas (`ledger/`, validated by `ledger.py`)

```
ledger/events/<section>.jsonl        news/claims (one JSON object per line)
ledger/observations/<section>.csv    KPI datapoints (tabular, high volume)
ledger/assessments/<section>.jsonl   timestamped milestone/KPI status judgments
ledger/rejected/<section>.jsonl      staged records that failed verification (kept for audit)
ledger/state/<section>.json          gather bookkeeping (last window per watch item)
ledger/staging/                      (gitignored) in-flight gather output
metrics/<section>.csv                metric registry = schema/contract for observations
```

**Event** (`events/<section>.jsonl`):

| field | meaning |
|---|---|
| `id` | `YYYY-MM-DD-slug`, unique per section; date = event date |
| `date` | event date (YYYY-MM-DD; YYYY-MM or YYYY if only that is known) |
| `published`, `published_basis`, `retrieved` | see §2 |
| `kind` | `achievement` `announcement` `projection` `setback` `data` `analysis` `policy` `retraction` |
| `topics` | ≥1 of `kpi`, `milestone:<slug>`, `challenge:<slug>`, `beyond` (slugs from README) |
| `claim` | one self-contained factual sentence with numbers AND their metric scope |
| `sources` | `[{url, title, primary}]`, deep links, at least one; primary sources preferred |
| `metrics` | optional `[{metric, obs, value}]` links to registered observations |
| `significance` | 1 minor · 2 notable · 3 major |
| `relates` | optional `[{id, rel}]`, rel ∈ `update` `retraction` `confirmation` `delay` `followup` (event lifecycle) |
| `verification` | `{status, by, at, note}`, status ∈ `verified` `corrected` `legacy` |
| `collector` | provenance, e.g. `gather:climate/milestone-the-bend@2026-09-29` |

**Observation** (`observations/<section>.csv`): `metric,obs,value,unit,source,
published,published_basis,retrieved,collector,verification,note`.
`verification` ∈ `verified` `corrected` `collector` (deterministic parse of a
primary data file) `legacy`. `metric` and `unit` must match `metrics/<section>.csv`.
The registry also gives `cadence` and `release_lag_days` (enabling "expected by"
and "overdue" in views, and `rule`-basis publication dates) and
`required_from`/`retired_after` (KPI components; basis changes).

**Assessment** (`assessments/<section>.jsonl`): `{id, target ("kpi" |
"milestone:<slug>"), status ("green"|"yellow"|"red"), label, made_at, rationale,
evidence: [event ids], by}`. `made_at` is the as-of date of the evidence that was
considered, not the wall-clock time of the run (`by` records the run). Every
evidence event must be known by `made_at` (checked), so a retrospective
assessment ("status as of 14 Jul given what was public then") is honest and
reproducible. Its `known_at` is `made_at`.

`legacy` records were converted from the pilot-2025 reports. They are useful
history, but they were not verified at ingest. Views flag them, and bulletins
may use them only as background context, never as this period's news.

## 4. Gather (`gather.sh <section> [--since D] [--until D] [scope]`)

1. **plan**: watch items from README: the KPI, every milestone, every challenge,
   and always an open-ended `beyond` sweep for significant developments outside
   the framework.
2. **collect**: deterministic collectors (`collectors/<section>.py`) fetch
   machine-readable sources into staged observations. No LLM.
3. **intake** (one web-capable agent per watch item): find developments in the
   window, and stage event records and observations. It is shown the section's
   recent events so that it **dedups**: a new source for a known event is added
   to that event instead of creating a duplicate, and status changes become new
   events linked via `relates`.
4. **verify** (a fresh agent that did not do the intake): visit every staged
   record's source. Confirm the claim, dates, kind and scope. Mark it
   verified, corrected or rejected.
5. **merge** (`ledger.py merge`, deterministic): schema, registry, dedup and
   relation checks. Verified records go into the ledger; rejected ones go to
   `rejected/`.
6. **assess**: re-judge the status of each milestone that received new events,
   appending assessment records with their evidence.
7. Each step commits only its own paths; the write-scope guard applies.

## 5. Bulletin (`bulletin.sh <period-dir> <section>`)

1. **snapshot** (`ledger.py snapshot`, deterministic): the ledger as of the
   cutoff. It contains new events, background events, current and previous
   assessments, KPI headlines (required registry metrics) with deltas versus the
   previous cutoff, and chartable series. It is written to
   `<period-dir>/snapshot/<section>.json` and committed, which makes the
   bulletin's input reproducible.
2. **draft**: from the snapshot only, in the reference format. Footnotes cite
   ledger sources, and charts are rendered from the ledger as of the cutoff
   (`kpi.py chart`).
3. **edit**: editorial review (structure, clarity, metric-scope hygiene, fidelity
   to the snapshot). No research. A gap is recorded in
   `<period-dir>/gaps/<section>.md` so the next gather can pick it up.
4. **gate** (`validate.py --snapshot`): every footnote URL belongs to a
   snapshot record; every number in the prose traces to the snapshot; KPI charts
   match the ledger; the usual link, footnote and mermaid checks. Fatal by
   default (`STRICT=0` = report-only).

`roundup.sh <period-dir>` compiles the bulletins into the period README, as
before.

## 6. Verification model

Verification happens at ingest (step 4), so it is done once per fact rather
than once per report. Bulletins re-use verified facts, and their review becomes
editorial. The deterministic gates are `ledger.py check` (the ledger itself),
`kpi.py`/`validate.py` (views), and `test_harness.py` (regression tests of the
checks themselves).

## 7. Migration from the period pipeline

- Per-period `kpis/<section>.csv` vintages become `ledger/observations`.
  pilot-2025 rows become `legacy` rows known at the pilot-2025 commit date;
  pilot-26H1 rows are `verified`, and their publication dates come from the
  notes or from the `rule` basis.
- Per-period research notes: pilot-26H1 notes become verified events (they
  passed review and audit); pilot-2025 sections become `legacy` events.
  Research notes stop being canonical.
- `generate.sh` and the per-period `kpis/` stores were retired once `gather.sh`
  and `bulletin.sh` were proven end to end (first gather run: climate,
  2026-09-15..28). Both remain in git history.

## 8. Known limits / open questions

- Dedup is LLM-driven, backed only by a deterministic heuristic (same primary
  URL and date), and near-duplicates can slip through. Merging duplicates later
  needs an explicit `relates: confirmation` or a manual edit.
- The `rule`-basis publication date is an estimate. Revisions made before our
  first retrieval are invisible.
- Git as the database is fine at current volumes (thousands of records). The
  SQLite build is a derived artifact.
