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
  - `seen`: unknown; we use the date we first retrieved it (an upper bound;
    enforced: `seen` ⇒ published = retrieved).
- **retrieved**: when we fetched it.

`known_at = published`. It reconstructs *public* history from publication
dates, some of them estimated (`rule`). It does not prove that we held a value
at T.

The **effective observation** for (metric, obs) as of T is the highest-ranked
row with `known_at ≤ T`. Rank = (tier, known_at, retrieved), where tier puts any
non-legacy row above a legacy one: legacy migration dates are not source
revisions, so a report-extracted "426.5" never shadows NOAA's "426.46". Source
revisions are appended as new rows, never overwritten. A merge is a no-op for a
value that equals the current effective row (numerically, same or higher tier),
so a revision back to an earlier value is still recorded.

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
ledger/state/<section>.json          gather bookkeeping (per-watch-item watermarks, run log)
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
| `withdrawn` | optional `true`: a withdrawal tombstone (kind `retraction`, with `supersedes`). The superseded record disappears from views and the tombstone is not shown; the claim says why |
| `supersedes` | optional `[ids]`: this record replaces them (a correction, or an added/better source). Views use the effective events: a superseded record disappears once its replacement is known. The ledger itself stays append-only |
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

Statuses follow the rubric in **STATUS.md** (v1). KPI status = pace
toward the goal versus what the goal needs (never the level). Milestone status =
ETA on evidence, with `achieved` as a terminal status. Records carry `rubric`,
a structured `basis` and verdict-bound labels. Hysteresis (a status change needs
newer evidence, or a once-per-target `rubric_correction`) is enforced by
`ledger.py check`. Each KPI's assessed metric, window and benchmark are fixed in
`metrics/kpi-assessment.csv`. `assess.sh` runs the assessment stage (called by
gather.sh; standalone with FORCE=1 / CORRECTION=1 after a rubric change).

`legacy` records were converted from the pilot-2025 reports. They are useful
history, but they were not verified at ingest. Views flag them, and bulletins
may use them only as background context, never as this period's news.

## 4. Gather (`gather.sh <section>`; env UNTIL, SINCE, ITEMS, OVERLAP_DAYS)

1. **plan**: watch items from README: the KPI, every milestone, every challenge,
   and always an open-ended `beyond` sweep for significant developments outside
   the framework.
2. **collect**: deterministic collectors (`collectors/<section>.py`) fetch
   machine-readable sources into staged observations. No LLM.
3. **intake** (one web-capable agent per watch item): find developments
   published in the item's window, and stage event records and observations.
   Windows are per item: from the item's last UNTIL minus OVERLAP_DAYS (default
   3, because sources publish and index late) to UNTIL. It is shown the
   section's effective events so that it **dedups**:
   - a status change becomes a new event linked via `relates`;
   - a correction, or a better source for a known event, becomes a replacement
     record with `supersedes`.
4. **verify** (a fresh agent that did not do the intake): visit every staged
   record's source. Confirm that the claim, dates, kind and scope are stated by
   the source (never from background knowledge). Mark each record verified,
   corrected or rejected. A parsed `lint --final` then guarantees that nothing
   is left unverified.
5. **merge** (`ledger.py merge`, deterministic, one call for all staged files):
   the whole proposed ledger state goes through the same validation as
   `ledger.py check`, under a per-section lock. Nothing is written on any
   error; each file is replaced atomically. Replays are idempotent (identical =
   no-op, conflicting = error), so a crashed merge can simply be re-run.
   Rejected records go to `rejected/`.
6. **assess**: `ledger.py stale` lists targets whose evidence is newer than
   their latest assessment (effective events tagged with the target; for the
   KPI also required-metric observations), plus never-assessed targets, each
   with its next free assessment id. The trigger is stateless, so a run that
   died before assessing is caught up by the next one.
7. Each step commits only its own paths. The write-scope guard (cooperative,
   not isolation) lets agents touch only staging and the registry. It checks
   committed changes, uncommitted changes and already-dirty files, and runs
   even if the agent crashes. The registry is APPEND_ONLY: existing rows can
   never change.

## 5. Bulletin (`bulletin.sh <period-dir> <section>`)

1. **snapshot** (`ledger.py snapshot`, deterministic, **self-contained**): the
   ledger as of the cutoff. It includes:
   - new events and background events (effective events only; background
     always includes lifecycle predecessors and the evidence cited by the
     assessments);
   - current and previous assessments;
   - KPI headlines: the required registry metrics as of the PERIOD END, with
     change versus the previous cutoff, comparability caveats and same month
     last year;
   - the frozen chart series;
   - the README framework.

   It is written to `<period-dir>/snapshot/<section>.json` and committed.
   Drafting, chart rendering and validation read the snapshot, not live
   state, so a later ledger or README change cannot alter or invalidate a
   committed bulletin.
2. **draft**: from the snapshot only, in the reference format. Footnotes cite
   snapshot sources, and charts are rendered from the frozen series
   (`kpi.py chart`).
3. **edit**: editorial review (structure, clarity, metric-scope hygiene, fidelity
   to the snapshot). No research. A gap is recorded in
   `<period-dir>/gaps/<section>.md`; the next gather's intake agents see those
   bullets.
4. **gate** (`validate.py --snapshot`), fatal by default (`STRICT=0` =
   report-only). It checks that:
   - every cited URL is a snapshot source;
   - every prose number occurs in the snapshot's typed evidence text (claims,
     values, labels, dates; not ids or metadata);
   - the KPI headlines are reported;
   - charts match the frozen series;
   - every milestone and challenge has its own heading;
   - plus the usual link, footnote and mermaid checks.

`roundup.sh <period-dir>` compiles the bulletins into the period README, as
before.

## 6. Verification model

Regression tests pin every mechanical guarantee above:
- `test_harness.py`: ledger, snapshot and gate, including replay idempotency,
  precedence, supersedes lineage and cycles, staleness digests, and frozen
  snapshots;
- `tests/test_guard.sh`: the write-scope guard;
- `test_collectors.py` and `test_explorer.py`.

Verification happens at ingest (step 4), so it is done once per fact rather
than once per report. Bulletins re-use verified facts, and their review becomes
editorial. The deterministic gates are `ledger.py check` (the ledger itself),
`kpi.py`/`validate.py` (views), and `test_harness.py` (regression tests of the
checks themselves).

## 7. Two repositories: mechanism and data

- **Mechanism** (this repo): code (`ledger.py`, `kpi.py`, `validate.py`,
  `explore.py`, collectors), the pipeline scripts and their prompts, the endeavor
  framework (README.md), the schemas (this file) and the status rubric
  (STATUS.md). It is reviewed like code.
- **Data** (`$GE_DATA`, default `./data`, gitignored here; its own git repo):
  `ledger/`, `metrics/` (registry + KPI assessment specs) and the period
  directories (bulletins, frozen snapshots, gaps, manifests). The pipeline
  commits here, one commit per stage. Its history before 2026-09-30 was
  extracted from this repo with git filter-repo.
- Scripts run with cwd = the data repo and call the code as `$ROOT/<tool>`. The
  write-scope guard watches BOTH repos: agents may change only their allowed
  data paths, and nothing in the mechanism repo. Every manifest and state record
  stores `mechanism_commit` and `data_commit`, so any output can be traced to
  the exact code and prompts that produced it.
- Tests use temporary fixture ledgers (`ledger.DATA` is monkeypatched) and never
  touch the data repo.

Migration history (2026-09): the per-period `kpis/` vintages became
`ledger/observations`; the pilot-26H1 notes became verified events; the
pilot-2025 sections became `legacy` events and assessments; `generate.sh` was
retired.

## 8. Known limits / open questions

- Dedup is LLM-driven. The deterministic backstop is a warning heuristic:
  claim word overlap (Jaccard) ≥ 0.6 within 7 days, skipping pairs with
  different figures or pairs linked via relates/supersedes. Reworded
  near-duplicates can slip through; fix them later with `supersedes`.
- The `rule`-basis publication date is an estimate. Revisions made before our
  first retrieval are invisible. `known_at` reconstructs public history; it is
  not proof of what we held at the time.
- Assessments: `made_at` is the evidence as-of date (the review suggested
  renaming it to `as_of` and adding a separate creation/version time; git
  history holds the creation time for now). Evidence-date checks cannot prove
  that the judgment itself is free of hindsight.
- The bulletin gate is lexical: a number must occur somewhere in the snapshot's
  typed evidence text, and a URL must be a snapshot source. It does not prove
  that the cited record supports the sentence; the edit stage's fidelity
  reviewer does that.
- Observations have no withdrawal record yet: a wrong value can only be
  outranked by a better row.
- Git as the database is fine at current volumes (thousands of records). The
  SQLite build is a derived artifact.
