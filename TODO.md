# TODO — Grand Endeavors

Working backlog. Architecture: **DESIGN.md**. The ledger (`ledger/`) is the
product. `gather.sh` grows it on its own schedule, and bulletins (`bulletin.sh`,
`roundup.sh`) and the explorer (`explore.py`) are views of it. Regression tests:
`uv run test_harness.py`, `test_collectors.py`, `test_explorer.py`.

## Done (2026-09 re-architecture; details in git log)

- [x] **DESIGN.md**: gather → ledger → views. Time semantics are obs/event date,
      published (+ basis `source|rule|seen`) and retrieved, with
      known_at = published. Bulletin cutoff = period end + 2d (weekly) / 7d
      (monthly) / 14d (longer). Nothing published after a cutoff back-fills a
      bulletin; it becomes the next one's news. (This settles the old "data
      vintage" and "post-period context" questions.)
- [x] **ledger.py**:
  - event / observation / assessment schemas, with README-derived topic tags;
  - check, lint (staged files), atomic merge (rejected records kept in
    `ledger/rejected/`), similarity-based dedup warnings, lifecycle `relates`;
  - assessments whose `made_at` is the evidence as-of date (hindsight
    rejected);
  - snapshot at cutoff (new vs background events, KPI headlines with change,
    comparability and year-ago values, and a chartable index).
- [x] **Metric registry** `metrics/<section>.csv`: definition, unit, cadence,
      release lag, required_from and retired_after.
- [x] **Migration** into the ledger:
  - 577 legacy events and legacy assessments converted from the 8 pilot-2025
    reports;
  - 40 verified 26H1 climate events and assessments from the audited notes;
  - KPI observations from the per-period stores.
- [x] **Deterministic collectors** (side agent): NOAA CO₂ (with derived
      5/10-yr trends), METR frontier, and JSR payload mass. `collectors/run.sh`
      runs them.
- [x] **gather.sh**: collect → one intake agent per README watch item (KPI,
      milestones, challenges and a "beyond" sweep) → fresh verifier → merge →
      assess → state. Agents may only write staging files; the write-scope
      guard enforces it.
- [x] **bulletin.sh**: committed snapshot → draft from the snapshot only →
      editorial and fidelity review (gaps are logged, not researched) → fatal
      gate `validate.py --snapshot`. The gate checks that every cited URL is a
      snapshot source, every prose number occurs in the snapshot, KPI headlines
      are reported, charts match the ledger, and every milestone and challenge
      is covered.
- [x] **explore.py** (side agent): SQLite + Datasette metadata, and a
      self-contained static dashboard with `--as-of`, visible gaps and overdue
      metrics, legacy badges and sparklines.
- [x] **Retired** `generate.sh` and the per-period `kpis/` stores.
- [x] **Deep-review fixes** (review of the re-architecture, commits 8905aba..HEAD of 2026-09-28): the
      core fixes are:
      - effective-observation precedence (legacy never shadows verified);
      - dedup against the effective row;
      - one validation path with atomic, locked, replay-idempotent merges;
      - `supersedes` for corrections;
      - self-contained snapshots (frozen series, README framework, typed
        evidence, requirements judged at the period end);
      - per-item overlapping gather windows;
      - stateless assessment triggers (`ledger.py stale`);
      - a parsed `lint --final`;
      - a guard that also covers crashes, already-dirty files and the
        append-only registry;
      - structural (heading) coverage in the gate, and URLs with parentheses.

      Side agents fixed collector revision dating (effective row) and METR's
      metric basis (new `metr-*-horizon-by-release` ids), and brought the
      explorer onto the same precedence, supersedes and comparability
      semantics. Re-verified end to end: a narrow climate gather (8 events +
      a KPI re-assessment) and the W38 bulletin + round-up, with gates green.
- [x] **Verification-review fixes** (commit d43304d): exact-replay observation
      merges, evidence-digest staleness (same-day and late-discovered
      evidence), guard coverage of restores/deletions of dirty files, a
      run-start registry baseline, lineage-aware `supersedes` with cycle
      checks, `flock`, all series frozen, and pre-freeze snapshots failing
      explicitly. `tests/test_guard.sh` was added. pilot-26H1 was regenerated
      under the final code.
- [x] Earlier harness work carried over: write-scope guard, per-section
      manifests, the fatal gate with the two-GET link probe, the round-up
      generator and its number-traceability check, and the pilot-2025
      citation-syntax fixes.

## Next: operations

- [ ] **Scheduling**: cron or a systemd timer for `gather.sh <section>`, with a
      per-section cadence (e.g. climate weekly, collectors daily), and for
      `bulletin.sh` + `roundup.sh` after each cutoff. Also decide the weekly
      bulletin day (cutoff = Sunday + 2d = Tuesday).
- [ ] **Cost profile**: a full climate gather (8 watch items + verify + assess)
      took about 75 min wall time for a 2-week window (36 events admitted, 4 corrected by the verifier). Measure tokens,
      then decide on (a) per-item cadence (e.g. milestones weekly, slow
      challenges monthly), (b) parallel intake agents, and (c) per-stage model
      choice (e.g. a cheaper intake model with the verifier kept strong).
- [ ] **Gaps loop**: gather.sh already feeds `*/gaps/<section>.md` bullets to the
      intake agents. Next, close items that were answered (mark them done in
      the file).
- [ ] Gather the remaining sections (only climate has had a real gather run).
      The legacy-only sections have no verified events yet.
- [ ] Publish the explorer (static dashboard and/or Datasette) and point the
      round-up README to it.

## Done (2026-09-30)

- [x] **Status rubric v1** (STATUS.md, co-designed with best mode):
  - KPI = pace versus need (the level is never scored); milestone = ETA on
    evidence;
  - `achieved` and `unknown` statuses, verdict-bound labels, structured basis;
  - hysteresis enforced by `ledger.py check`; per-KPI specs in
    `data/metrics/kpi-assessment.csv`;
  - `assess.sh` (FORCE / CORRECTION).

  All sections were re-assessed under v1 as of 2026-09-30. KPIs that can't be
  judged now show "Unassessed: <reason>" instead of stale colours.
- [x] **Data/mechanism split**: `./data` is its own git repo (history kept via
      filter-repo). Scripts run in it, the guard watches both repos, and
      manifests record both commits. No GitHub remote exists yet (owner decision
      below).
- [x] **Legacy re-verification** of all 577 legacy events (research-mode
      subagents): 167 verified + 83 corrected (replacements), 5 refuted
      (withdrawal tombstones), 322 unverifiable (stay legacy). A mechanical
      figure audit plus a strict quote-per-figure pass removed 17
      over-verifications. Logs are in `data/ledger/reverify/`.

## Decisions for the owner

- [x] Data repo published (public): github.com/pasky/grand-endeavors-data
      (2026-10-01). Pipeline runs don't push yet; scheduling should add
      `git -C data push` after each run.
- [ ] **Blue Collar Shift = achieved?** Under the rubric's literal-wording test,
      Figure 02's 10-hour shifts at BMW (with support staff) meet README's text.
      If the intent is an *autonomous* shift, tighten the README wording and
      reassess.
- [ ] **Fusion KPI basis**: README's intent ("if all electricity bills go to
      zero") points to the end-user price. The recommendation is to register a
      population- or consumption-weighted global household retail price, in
      real USD/MWh, and keep the wholesale and LCOE series as supporting
      context. The KPI is unassessed until it is registered.
- [ ] (superseded by rubric v1; kept for history) **Status rubric**: green/yellow/red have no written definition. For the
      climate KPI, is 🔴 about the *level* (concentration keeps setting records,
      growth far above a 1.5°C pace) or the *direction* (growth rates eased in
      26H1)? The 26H1 edit stage flagged that the 🟡→🔴 downgrade isn't
      supported by the growth-rate evidence. That backfilled assessment was
      derived from the old period report, so it isn't independent. Write a
      short rubric per target type (KPI / milestone) into DESIGN.md or README,
      and have `gather.sh` assess against it.

## Next: data quality

- [x] **Legacy re-verification** of events (2026-09-30, see Done). Still open: the
      322 unverifiable events need retries (archive.org snapshots, alternative
      sources), and the legacy **observations** (pilot-2025 KPI values) were not
      re-verified. Earlier note: the 577 legacy events were converted from
      reports, not verified at ingest. The conversion logs flagged report
      defects: source URL/date mismatches, placeholder "2025" dates for undated
      items, and weak mailing-list-root sources. A verify pass per section can
      promote them to `verified` or correct/reject them. This needs a
      supersede mechanism, next item.
- [x] Corrections of admitted events: `supersedes` (views use the effective
      events). Still open: an observation **withdrawal** record (today a bad
      value can only be outranked).
- [ ] Assessments: rename `made_at` → `as_of` and add a creation/version time
      (review suggestion; git history holds the creation time for now).
- [ ] Snapshot size: a weekly climate snapshot is about 136 KB (8 sections × 52
      weeks ≈ 55 MB/yr in git). Consider gzip, or pinning the ledger commit
      and regenerating on demand (with a checksum).
- [x] The verifier accepted one detail "from background knowledge" (first run: an
      "October 2025" date the source didn't state). The verify prompt now
      requires every field to be source-stated (not yet re-tested).
- [ ] Dedup is an LLM job plus a heuristic (claim word overlap ≥ 0.6 within 7
      days, different figures ⇒ not a duplicate). Near-duplicates with
      reworded claims can slip through (fix later with `supersedes`).
- [ ] The bulletin gate is lexical: a number must occur in the snapshot's typed
      evidence, and a URL must be a snapshot source. It does not prove that the
      cited record supports the sentence; the fidelity reviewer does. Next
      step: tie each footnote to a record id.
- [ ] The write-scope guard is cooperative, not isolation. Gitignored paths are
      invisible to it (fine for staging, but also `.pi/`, `build/`).
- [ ] `rule`-basis publication dates are estimates (obs end + registry lag).
      Source revisions made before our first retrieval are invisible.
- [ ] Registry gaps: fusion's worldwide electricity-cost KPI is unregistered
      (README basis is ambiguous, wholesale vs retail), and the health
      `hale-median-country` KPI has never been observed. The OECD trust
      category is unconfirmed.
- [ ] Per-milestone multi-year series (e.g. an emissions chart for The Bend):
      register the metrics and let the intake record observations, or write
      a collector (GCB/EDGAR publish CSVs).
- [ ] Collectors for more KPIs: IRENA LCOE, WHO GHE HALE, IEA (where
      machine-readable).
- [ ] (future) snapshot each cited URL locally (link-rot proofing).

## Next: views / checks

- [ ] Round-up doesn't read the ledger yet: its Quick Reference could be
      rendered from snapshot KPI headlines and assessments.
- [ ] Round-up number check is lexical only (it doesn't catch a right number
      on the wrong metric). The pilot-2025 README's "41% of code AI-generated"
      is untraceable (legacy, not fixed).
- [ ] validate.py: footnote/ref regexes ignore duplicate or indented
      definitions and shortcut refs. The mermaid check only length-checks
      arrays. Chart overlays (extra series) are unchecked, and the y-axis label
      is free text.
- [ ] Link liveness is a heuristic: two GET 404s = dead (cached or bot 404s can
      false-positive; STRICT=0 overrides), and HEAD-200 is trusted.
- [ ] Dashboard: the HTML grows with the ledger (older events are collapsed but
      all included). Paginate or split per section at some size.

## Content / roadmap

- [ ] Finish `TEMPLATE.md` (the newsletter intro still ends in `..todo..`).
- [ ] weekly report cadence running (README status)
- [ ] reference source list per endeavor (it would also seed the intake
      agents' watch lists)
- [ ] publishing infra (Substack + automated Twitter)
- [ ] drafting/feedback infra for early expert review + errata (this maps
      naturally onto ledger corrections)
