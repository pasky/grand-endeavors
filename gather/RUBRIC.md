# Status rubric (v6)

Every KPI and milestone in framework.yaml carries a **status**: a colour plus a
one-line label such as "Off track: 421 ppm, +2.4 ppm/yr vs ≤0 needed". This
file defines how that status is chosen, so it means the same thing across
sections and runs and does not flap.

- **Who applies it**: the assess stage of a gather run (`gather/assess.sh`, an
  LLM assessor that must follow this file). The resulting assessment records
  are stored in the ledger (`ledger/assessments/<section>.jsonl`). Their fields
  are listed in DESIGN.md §3.
- **Who enforces it**: `ledger.py check` mechanically enforces the rules marked \*.
- **Who shows it**: bulletins and the dashboard. They display stored statuses
  and never judge anything themselves.

Co-designed 2026-09-30 (v1). v2 (2026-10-06): milestone ETAs are reasoned
forecasts with a median and an 80% range (§4.1), no longer a status bucket
restated. v3 (2026-10-12): drivers are calibrated to what the milestone needs
and adjustments need evidence of their own (§4.1 step 3); gates that the
framework `assumes:` away never block a milestone (§4.2). v4 (2026-10-13): a
measurement gap is not a slowdown, the most current series of the outcome
sets the rate, and an ETA states the chance the milestone happens at all
(`p_achieved`; quantiles past 2100 are null). v5 (2026-10-14, after an audit
of the v4 ETAs): a re-assessment updates the previous model instead of
re-deriving it (rule 7), every input is labelled measured, sourced or
assumed, with its sensitivity (§4.1 step 7), a driver's mapping onto the
milestone is an assumption unless measured, the chance of failure comes from
named scenarios, and only effective records are cited (clarified after
audit round 2: what counts as measured, calendar-year quantiles, and that
replacing a disclosed judgment is not an error fix). v6 (2026-10-15): a
driver that several milestones share has one fitted distribution, whose
draws they all sample (§4.1 step 2); the forecast is compared with external
community forecasts (anchors) only after it is written down, and a gap is
explained, not closed (§4.1 step 4; anchors of the same, a bounding or a
similar event); every failure scenario of 10 % or more
names its reference class with counts (§4.1 step 5); clarified 2026-10-16
(owner): attempts that cost a gatekeeper's goodwill, such as AI patches and
papers, are not freely repeatable, so they use the 80 % level (§4.1 step 3).
KPI rules are
unchanged in v2–v6. Any change in meaning is a new rubric version (rule 4).

## 1. What the colours mean

A status answers a different question for each kind of target:
- **KPI**: is the needle moving toward the goal at the pace the goal needs? The
  status scores the **trend**, never the level.
- **Milestone**: on today's evidence, **when** do we get there? The answer is
  the median of a reasoned forecast (§4.1), not a pessimistic bound.

| status | KPI | milestone | label starts with |
|---|---|---|---|
| green | moving toward the goal at or above the needed pace | median ETA ≤ 5 years on an evidenced path | Ahead, On track |
| yellow | clearly moving toward the goal, but too slowly | measurable progress, median ETA ≤ 10 years (≤ 5 years when the path is not yet fully evidenced) | Behind pace, Progressing |
| red | flat (stalled) or moving the wrong way | > 10 years, no path, stalled, regressing or blocked | Off track, Stalled, Regressing, Distant, Blocked |
| achieved | (not used) | done: a verified achievement meets the literal wording | Achieved |
| unknown | the rubric cannot judge it (no KPI spec, or no data covering the window) | same | Unassessed |

- The absolute level and the distance to the goal are **reported** in the
  label but never **scored**.
- `unknown` replaces a stale pre-rubric colour. Never use yellow to encode
  ignorance or "mixed" evidence.
- Old data keeps its verdict behind a prefix: "Stale (data to 2021): Behind
  pace: ...".

## 2. Examples

These are real assessments made on 2026-09-30.

**Climate KPI (red).** Label: "Regressing: 427.35 ppm (2025); 10-yr growth 2.56 vs 2.15
ppm/yr, need <=1.79" (its benchmark tier, 1, is in basis.benchmark).
- The goal is for atmospheric CO₂ to stop accumulating, so the assessed
  quantity is its growth rate, not the ppm level.
- The 10-year mean growth was 2.56 ppm/yr for 2016–2025, against 2.15 for
  2006–2015. It is moving the wrong way, so the status is red. It does not
  matter how far the level is from the goal.
- The benchmark (tier 1: ≤ 1.79 ppm/yr for IPCC 1.5 °C pathways) is cited for
  context.
- The Jan–Aug 2026 monthly swings (La Niña giving way to El Niño) were
  discounted as a transient. The record 427.35 ppm appears in the label only.

**Rockets milestone "The Deluge" (yellow).** The milestone is 100,000 tonnes
delivered to orbit in a single year. Label: "Progressing: 3,194 t to orbit in
2025 (3.2% of 100 kt/yr); +45%/yr 5-yr trend, ETA ~2034".
- The milestone's own quantity, annual payload mass to orbit, grew about 45 %/yr
  over 2021–2025, up from about 11 %/yr over 2016–2020.
- Extrapolating that trend reaches 100,000 t/yr around 2034, inside the 5–10
  year band, so the status is yellow. As a `basis.eta`: p50 2034; p10 2032
  (Starship at operational cadence lifts growth to ~60 %/yr: 7.3 yr); p90
  2040 (growth halves to ~25 %/yr: 15.4 yr); method trend (log-linear);
  calc "gap 100000/3194 = 31×; log(31.3)/log(1.45) = 9.3 yr after 2025".
- It is not green because the path depends on Starship flying at operational
  cadence, and no precursor at that scale has been demonstrated yet.
- The slower 2025 step (+22 %) is a single observation, so it does not flip
  the status.

**Unknown.** The rockets KPI is "Unassessed: only one cost-to-leo-best
observation (2025, legacy)...". The 5-year window needs at least 3 points, and
a narrative cannot stand in for numbers.

## 3. KPI rules (pace vs need)

`metrics/kpi-assessment.csv` fixes, per section, the assessed metric,
goal_direction, trend window, pace benchmark and benchmark source. Assessors do
not choose these; changing one is a reviewed registry edit. Without a row there
is no KPI assessment (status unknown).

- **Assessed quantity**: for level or flow KPIs (AI task horizon, $/kg, HALE,
  $/MWh), the series itself. For stock KPIs whose goal is to stop accumulating
  (CO₂ ppm), the multi-year growth rate, with goal_direction = down to ≤ 0. The
  stock level goes in the label only.
- **Window**: at least the dominant noise cycle, and at least 3 observations.
  Judge the current window against the previous non-overlapping window (or
  half-windows), never two adjacent points.
- **Benchmark**: use the first tier that is available, and cite the tier and
  source every time (in basis.benchmark and basis.benchmark_source):
  1. an external required path for the endeavor goal;
  2. the pace implied by the nearest milestone at its stated horizon;
  3. the KPI's own long-run trend (≥ 5 years).
- **green**: the window trend moves in the goal direction at or above the
  benchmark pace.
- **yellow**: the window trend moves clearly in the goal direction (beyond
  noise), but below the benchmark pace.
- **red**: the window trend is flat within noise (stalled), or moves in the
  wrong direction (regressing).
- **Transients**: a deviation is transient if and only if it spans less than one
  window AND has a named cause with an expected reversal (ENSO, a pandemic, a
  one-off). A transient moves the status in neither direction. It becomes real
  when the next scheduled observation confirms it, or when that observation is
  overdue by more than one cadence plus the release lag.
- **Stale or missing data**: data_as_of is the latest effective observation.
  If made_at − data_as_of > 2 cadences + lag (for irregular series: more than
  3 years), the label starts "Stale (data to YYYY): " followed by the verdict,
  and the status is carried over. If no registered series covers the window,
  there is no KPI assessment (status unknown); narrative cannot substitute for
  numbers.

## 4. Milestone rules (ETA on evidence)

The status follows the median ETA (`basis.eta.p50`, made by §4.1) and the
evidence behind the path:

- **achieved**: at least one verified (non-legacy) event of kind `achievement`,
  from a primary source, that meets the milestone's literal wording, including
  any "definitively" clause. It is terminal: only a retraction event reopens it.
- **green**: median ETA ≤ 5 years on a specific evidenced path. That means all
  three of: a funded programme, a demonstrated precursor at relevant scale, and
  corroboration from someone other than the proponent.
- **yellow**: measurable progress on the milestone's quantity (or on a driver
  it is tied to, §4.1), with a median ETA ≤ 10 years; a median ≤ 5 years whose
  path lacks one of green's three conditions is yellow too.
- **red**: any of:
  - a median ETA over 10 years;
  - no path: nothing measurable moves toward it, not even a driver;
  - stalled (no progress over two windows);
  - regressing;
  - structurally blocked (policy, legal or definitional), whatever the
    technical readiness. Name the block and its type. A gate that the
    milestone's framework `assumes:` away never blocks it (§4.2).
- Events of kind `announcement` or `projection` never lift a status by
  themselves.

### 4.1 Estimating the ETA

An ETA is a forecast, and forecasting is hard. It is still the assessor's job:
reason it through with all the data in the ledger, do the arithmetic, and
write down the reasoning so a reader can check it and disagree. The
failure to avoid is a gut guess, especially one that extrapolates in a
straight line or sounds cautious. Work through these steps:

1. **Measure the gap.** State the milestone's quantity, its latest evidenced
   value and its target, then the gap as a ratio: "3,194 t vs 100,000 t =
   31×, 5 doublings". For a qualitative milestone (a first demonstration, a
   test passed), find the measurable capability or deployment it needs and
   measure that gap instead. When the wording leaves a boundary open (who
   counts as "one person", which journals, how long "sustained" is), state
   the reading you use in `basis.path`, choose the most natural one, and if
   another reasonable reading moves p50 by more than 2 years, report it as a
   sensitivity and a definition crux (the owner decides the wording).
2. **Find the trend.** Collect every data point in the ledger: observations
   (`ledger.py series`) and the dated numbers in events, legacy ones included
   as context. Look in other sections too. If the milestone's quantity has no
   series, tie it to a **driver** that does, and say how the milestone maps
   onto the driver's units. For example, an AI-written 10,000-line patch maps
   onto AI task horizons (robots-software KPI); robots doing a full shift
   maps onto the software autonomy trend plus hardware unit volumes. Cite
   another section's data in `calc` (registered metric id, values, event ids);
   `evidence` lists only this section's events. Known gap: a new observation
   of a foreign driver does not re-assess the milestone (TODO.md). "No
   series in the ledger" is a gap to work around (a driver, a reference class,
   or a gather request in `blockers`), not an ETA.
   Use only **effective records**: a superseded record's claim is replaced
   by its replacement's (an `-rv` correction often narrows it: "$3.5M
   revenue" where the original said "solo, $3.5M ARR"). Reason from the
   replacement's wording and cite its id, also in `calc` when explaining
   what changed; a withdrawal tombstone means the claim is wrong.
   **Shared drivers**: a driver that several milestones rest on has one
   fitted distribution in the data repo's `drivers.yaml` (sources, fit
   window, and what is measured and what assumed). A milestone in a
   driver's `used_by` samples its draws (`ledger.py driver-draws <driver>
   --as-of <made_at>`, the canonical seed and count: draw i of the driver
   goes into draw i of the milestone's own simulation) and never refits
   it, and `calc` names the driver id (\*: `ledger.py check` warns
   otherwise). Draw i is the same for every milestone, so milestones that
   share a driver agree on it draw by draw. The mapping of the driver onto
   the milestone stays the milestone's own assumption (step 3). A driver fit
   that looks wrong is a finding for the owner (a reviewed `drivers.yaml`
   edit), never a reason for a private fit. A series that several
   milestones use but no driver covers gets the same fit in each unless the
   difference is argued in `calc`.
3. **Pick the growth model the quantity actually follows**, and justify it:
   - capability metrics (task horizons, benchmark scores, energy gain), deployed
     fleets, launch mass and revenue usually grow **exponentially**: fit in log
     space, quote the doubling time, and compute time-to-target as
     log(gap) / log(1 + growth). A 30× gap at +45 %/yr closes in 9 years, not
     in "decades"; at 3×/yr it closes in about 3 years.
   - costs usually follow **learning curves**: a fixed % drop per doubling of
     cumulative production (Wright's law), so they fall faster as volume ramps.
   - adoption and market share follow **S-curves**: roughly exponential until
     about 10–20 % saturation, then slowing down. Do not slow down early growth
     without naming the constraint that will cause it.
   - **structural floors** cannot be compressed by any exponential: a 10-year
     survival endpoint needs 10 years of follow-up; a power plant needs years
     of construction; a regulatory approval needs trials. The ETA is at least
     the floor, starting from when the step could begin.
   Use linear extrapolation only when the quantity really is additive (e.g.
   one-off construction projects with no learning).
   Calibrate the driver to what the milestone actually needs:
   - **reliability level**: when one success is enough and attempts can be
     repeated or selected cheaply (one demo, one benchmark run), use the
     50 % horizon or success rate. Use 80 % or higher when the milestone
     needs sustained reliability (full shifts, unattended operation), or when
     failed attempts are costly to a gatekeeper and so cannot be repeated
     freely. AI submissions to maintainers, editors or reviewers who are
     flooded by AI slop (one accepted patch, one paper) become feasible only
     once the AI is reliable.
   - **central rate**: the currently measured rate (the KPI window) is the
     median case unless a named constraint will slow it down. The slower
     long-run rate is the p90 case, not the median.
   - **a measurement gap is not a slowdown**: when a series is updated
     irregularly (benchmark evaluations) or with a lag (survival cohorts),
     the time since its last point is unmeasured, not flat. Fit the trend
     through the measured points and extrapolate from the last one. A gap
     counts as a stall or a slowdown only on evidence: newer measurements
     below trend, things that should have been measured and were not
     (releases left unevaluated, an evaluation programme stopped), or a named
     constraint. An expected reporting lag is not such evidence.
   - **the most current comparable series**: when the milestone's own series
     lags its drivers by years (e.g. 10-year survival reported for patients
     diagnosed a decade ago), look for a faster-reporting estimate of the
     same outcome in a comparable population (e.g. period-analysis survival).
     A different outcome (e.g. cancer mortality, which also falls when
     incidence falls) may only inform the rate through an explicit
     quantitative mapping in `calc`. Say which rate the median uses and why.
     A structural floor (e.g. 10 years of follow-up) still applies to the
     milestone's own measurement.
   - **mapping a driver onto the milestone is an assumption** unless a
     measurement links the two (e.g. a task horizon and the oversight hours
     of a running business; a product-quality reject rate and robot
     interventions; offshore-wind learning and fusion plant costs). Say
     whether the mapping is measured; if it is not, give an alternative
     mapping as a sensitivity and list the mapping first among the cruxes. A
     series of a different failure or outcome (rejected napkins are not robot
     interventions) can set the rate only through such an explicit, labelled
     mapping; never silently as if it measured the milestone.
   - **durations** (review, disclosure, integration, construction lags) are
     structural floors only when measured or sourced; an assumed lag is an
     assumed input like any other (step 7).
   - **core assumptions vs optional adjustments**: a forecast needs a
     central value for every link it cannot do without (the mapping from the
     driver's units to the milestone's, a step that must physically happen).
     When that link is unmeasured, use your best central estimate, label it
     assumed and show the alternatives (step 7): an unmeasured delay is not
     zero by default, nor is an unmeasured penalty. The two rules below are
     about **optional adjustments** layered on a forecast that is already
     complete (a discount on a measured driver, a safety margin): those need
     evidence to enter the median.
   - **no stacking**: each adjustment (benchmark-to-reality gap, review lag,
     adoption lag) needs its own evidence. Do not put every pessimistic
     adjustment in the median and leave the optimistic ones for p10.
   - **evidence that measures the adjustment**: a benchmark-to-reality
     discount needs data on that capability gap (e.g. horizons on messier task
     subsets, success rates on real repositories or real homes), not a
     neighbouring quantity (e.g. a study of how fast humans work with AI
     tools). An adjustment without such evidence stays out of the median; it
     may only widen the range.
4. **Cross-check.** Compare with a reference class (how long comparable
   transitions took from first demonstration to the milestone's level), with
   proponents' dates (historically optimistic: discount them, e.g. 1.5–3× on
   deep-tech schedules, but do not ignore them; discount the time remaining
   from the assessment date), and with the previous ETA.
   When the methods disagree, explain which you weight and why.
   **External anchors**: framework.yaml may list `anchors:` for the
   milestone, community forecasts (Manifold, Metaculus) of the same event
   (`same`) or of a bounding one: `weaker` is an easier event that comes no
   later than ours (its date is a lower bound on our ETA: our P(by its
   deadline) ≤ its probability), `stronger` a harder event that implies
   ours (an upper bound), and `similar` the same underlying capability or
   outcome under resolution criteria that neither imply nor are implied
   by ours (framework.yaml notes the differences and the direction they push
   its date). They are observations of the section
   (`ledger.py anchors <section>` lists their metric ids; read them with
   `series`). First finish the forecast without them and write its
   **pre-anchor p50** (with p10–p90 and p_achieved) into the notes; only
   then read the anchors. A **gap** is a same-event median more than 5
   years from ours or outside our p10–p90, a same-event probability more
   than 0.25 from ours at its deadline, a violated weaker/stronger bound
   (by more than a year, or more than 0.15 in probability), or for a
   `similar` anchor a median more than 10 years from ours or a probability
   more than 0.35 from ours. A gap is
   **explained, not closed**: name in `calc` the crux on which we and the
   market differ (an input, a mapping, a reading of the wording) and the
   observation that would settle it, citing the anchor's metric id (for a
   `similar` anchor, first how much of the gap its wording differences
   explain, in the direction framework.yaml notes). Move
   the forecast only for a reason you would accept without the anchor (an
   error the comparison exposed, evidence the market's reasoning points
   to), attributed like any other move (rule 7). Thin markets (a few dozen
   forecasters or fewer: forecasters=n in the observation's note) and loose
   resolution criteria count for less; say so. \* `ledger.py check` warns
   when a current record diverges beyond these thresholds without citing
   the anchor's metric id, or when its notes state no pre-anchor p50.
5. **Set the chance, the median and the range.** `p_achieved` is the
   probability that the milestone is achieved by 2100 at all. p10, p50 and
   p90 are the years by which it is achieved with 10 %, 50 % and 90 %
   probability (unconditional), and all three are ≤ 2100. A quantile past
   2100 is null, so p90 is null when `p_achieved` < 0.9, and p50 is null
   when it is < 0.5: a milestone that is unlikely by 2100 (e.g. a
   peak-warming limit that the trend overshoots) has no median year by 2100,
   and must not report one conditional on success. Derive the quantiles from
   the whole forecast distribution, including the chance of failure: with
   `p_achieved` 0.6 the unconditional median is later than the median of the
   successful outcomes. Put the conditional timing ("if achieved, ~2100") in
   `calc`. The chance of failure comes from **named failure scenarios**
   (what would stop it: a programme cancelled, a physical limit, a legal
   wall), each with a reference class where one exists, else its reasoning;
   its probability is an assumed input with a sensitivity (step 7). Every
   scenario of 10 % or more names its reference class **with counts**
   ("4 of 11 crewed exploration programmes since 1960 were cancelled before
   their first landing") and says how the probability follows from them;
   one with no countable class says why none exists, and its probability
   is then a disclosed judgment with a sensitivity. No generic
   "non-completion" mass. p_achieved and all quantiles come from **one
   distribution**: do not report a deterministic central case as the
   median, or widen a quantile by hand outside the model. A quantile year
   is the calendar year in which the quantile falls (2031.4 and 2031.9 are
   both 2031, "during 2031"), the same for p10, p50, p90 and the label.
   Beyond that, uncertainty **widens the range; it does not push the
   median later**: no padding without evidence. Do not default to ">10 years" because the
   question is hard or the data are thin. If the median is honestly far away,
   show the calculation that puts it there. For a near ETA, one year is a
   large share of the remaining time (a third of a 3-year horizon), so every
   year added to the median needs its own line in `calc`.
6. **Name the cruxes**: what observation would move the ETA earlier or later.
   Gather can look for exactly those next time.
7. **Register the inputs.** Every number the model uses is one of:
   *measured* (an event id or series point), *sourced* (a published
   estimate: cite it), or *assumed* (your judgment: give the reasoning).
   The working notes list them in a table with that label. For each assumed
   input, report what its plausible low and high values do to p50 and
   p_achieved; one that moves p50 by more than 2 years or p_achieved by more
   than 0.1 is a crux. A forecast that rests on assumed inputs is legitimate
   (this is forecasting); hiding which inputs are assumed is not. Only what
   the source states is measured: a fitted rate is measured, but the spread
   you put around it for the forecast (which rate the fast and slow cases
   take) is assumed unless the source reports it; a distribution spanning
   two reported points is assumed; an outcome the source does not report is
   unknown, not a failure (eight rounds with one reported success are not
   "1 of 8"). A sensitivity must compute the milestone's own event (all
   three homes, if the alternative reading needs three).

### 4.2 Assumed gates (`assumes:` in framework.yaml)

A milestone may stand for a capability, while its wording also passes through
a gate that is not the point: an editorial policy, or a project's rules on
AI-submitted code. The framework then names that gate in the milestone's
`assumes:` field. In that case:
- the ETA and the status are judged **as if the assumption held**. The gate
  never makes the milestone "Blocked", and it adds no policy lag to the ETA;
- `basis.eta.assumes` repeats the assumption, the label marks the ETA with an
  asterisk ("ETA ~2030*", or "P(by 2100) 20%*" without a median), and
  `basis.blockers` reports the gate's real state;
- `achieved` still needs an event that meets the literal wording. An event
  that meets everything except the assumed gate supports green, not achieved.

ETAs come from trend extrapolation, not roadmaps: a roadmap is not a trend,
and projections alone never move a status (rule 5). But a measured
exponential *is* evidence, and it must be extrapolated as an exponential.

## 5. Stability rules (hysteresis; \* = enforced by `ledger.py check`)

1. \* A status change needs at least one evidence record with known_at after
   the previous assessment's made_at. For a KPI, a newer observation of its
   assessed metric also counts. Exceptions: a rubric correction (rule 4), an
   audit correction (rule 8), and moves to or from `unknown`.
2. The trigger must hold for a full window (KPI) or be a verified event
   (milestone). One observation never flips a status.
3. Reverting to the previous status within 12 months requires naming the
   observation that reversed it and explaining why the earlier change was not
   a transient.
4. \* Reinterpretation under a new rubric version: a record whose previous
   assessment predates this rubric version (no rubric, or an older version)
   may re-judge it with `"rubric_correction": "<current version>"`, without claiming new
   evidence; it must say what the old assessment got wrong. A record that is
   already under the current version is never "corrected": changing it needs
   newer evidence (rule 1).
5. Projections alone never change a status. They may inform the label.
6. \* A change to a target's framework.yaml definition permits one re-assessment of
   that target that ignores rules 1–4 and the terminality of `achieved`. It
   sets `"definition_change": "<mechanism commit of the framework.yaml change>"` and
   judges the evidence against the new wording.
7. **ETA stability.** A re-assessment of a milestone starts from the
   previous assessment's model and inputs (its working notes). First check
   them: reproduce the previous result, and test each input and mapping
   against the effective evidence and this rubric. Keep what holds; replace
   what does not, the whole model if need be. Do not re-derive a sound
   forecast from scratch. An input changes only for (a) new evidence (cite
   it), (b) an error in the previous working (name it), (c) a rubric change,
   or (d) an audit finding. The change_note attributes every move of p10,
   p50 or p90 by a year or more (or between a year and null), and of
   p_achieved by 0.05 or more, to one of these (old vs new input and its
   effect), and says what the new evidence that triggered the re-assessment
   changed (possibly nothing). Re-modelling the same evidence with different
   judgments is noise, not an update: a disclosed assumed input is not an
   "error" because another value seems better now. Change it only when
   evidence or the rubric contradicts it, and say how. Without previous working (a first
   assessment), the rule constrains nothing. A fix that changes the status
   still needs rule 1, 4 or 8.
8. \* **Audit correction**: an assessment that addresses the findings of an
   ETA audit (reports in the data repo's `ledger/audits/<audit id>/`) sets
   `"audit_correction": "<audit id>"` and may re-judge without new evidence,
   once per target per audit. Its change_note names the findings it fixes.

## 6. Writing the record

- **label** = "<Verdict>: <level>, <trend> vs <benchmark>", at most 100 chars.
  \* The verdict word must be one of those bound to the status (table in §1).
  It must also match the window trend: no "Worsening" when nothing worsened.
  Write it for a reader who knows only the KPI's name: plain units and words
  ("Ahead: 1.8 h (Sep 2026), doubling every ~3 months vs ≤7 needed"), no
  metric ids, no "OLS", no "(tier 3)" (the tier is in basis.benchmark).
- **rationale**: the dashboard shows it, always visible, under the label, as
  the answer to "why this status?". Write it for a general reader, in 2–4
  sentences, consistent with the basis: (1) where the quantity stands and how
  fast it moves, in plain units; (2) the pace needed (the benchmark, by name)
  and hence the status; (3) only if something moved the numbers or the status
  since the previous assessment, what (otherwise say nothing about it: "no new
  measurements" tells the reader nothing); (4) the one caveat that matters most. Name a source by what it is
  ("Epoch's capability index"), not by an event id. No metric or event ids,
  commit hashes, file names, commands, CI arithmetic or robustness lists, and
  no run bookkeeping ("nothing new since…", "the same points give the same
  statistics"): those go in the basis (`window`, `change_note`), which the
  dashboard folds under "How the status was judged".
- **basis.window** (KPI) is rendered as structure: nested objects as nested
  lists, an object of date (or period) → number as a row of data cells. Keep
  the data points in such an object, statistics as numbers (not numbers inside
  strings) under short snake_case keys (`doubling_months_ols`), and prose
  (method, robustness, source) in its own keys.
- **change_note**: what moved since the previous assessment and why (or that
  nothing did); process detail (series byte-identical, ids, gaps) belongs here.
- **evidence**: the ids of the events relied on. Only `unknown` may have none.
  \* Cite effective records only (§4.1 step 2), here and in `basis.eta.calc`:
  never one superseded by the made_at date, and no withdrawal tombstone as evidence.
- \* **rubric** "v6" and a structured **basis**. Its keys are listed in
  DESIGN.md §3 (Assessment); for KPIs it includes the window numbers, so the
  judgment can be checked.
- \* For a milestone that is neither achieved nor unknown, **basis.eta** is an object
  `{p_achieved, p10, p50, p90, method, calc, cruxes}` (§4.1). `p_achieved`
  is a probability (0–1). p10 ≤ p50 ≤ p90 are calendar years, each null
  exactly when `p_achieved` is below its level (0.1, 0.5, 0.9), and p50 is
  not before made_at. The status must agree with p50: green ≤ made_at + 5
  years, yellow ≤ made_at + 10 years, and a null p50 is red. `method` names
  the model (trend, driver trend, learning curve,
  S-curve, structural floor, reference class, discounted proponent date, or a
  combination). `calc` gives the numbers and arithmetic. `cruxes` says what
  would move the ETA earlier or later. For a milestone with `assumes:`, it
  also has `assumes` (§4.2).
- **Working notes** (milestones): the assess run commits its `eta-notes.md`
  next to the records. Per milestone: the gap, the input register (step 7),
  the calculation including the script you ran (with the shared driver
  draws it sampled), the sensitivities, the cross-checks (the pre-anchor
  p50, then the anchors, step 4) and the cruxes. `calc` is its summary; the notes let a reader
  (and the next assessment, rule 7) reproduce it.
- The milestone **label** quotes the median: "..., ETA ~2034" ("ETA
  ~2034*" under an assumed gate); without a median it quotes the chance:
  "..., P(by 2100) 20%". `ledger.py check` warns when the latest
  assessment of a gated milestone lacks the asterisk or `basis.eta.assumes`.
