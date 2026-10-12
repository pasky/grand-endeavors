# Status rubric (v3)

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
framework `assumes:` away never block a milestone (§4.2). KPI rules are
unchanged in both. Any change in meaning is a new rubric version (rule 4).

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
ppm/yr, need <=1.79 (tier 1)".
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

- **Assessed quantity**: for level or flow KPIs (METR horizon, $/kg, HALE,
  $/MWh), the series itself. For stock KPIs whose goal is to stop accumulating
  (CO₂ ppm), the multi-year growth rate, with goal_direction = down to ≤ 0. The
  stock level goes in the label only.
- **Window**: at least the dominant noise cycle, and at least 3 observations.
  Judge the current window against the previous non-overlapping window (or
  half-windows), never two adjacent points.
- **Benchmark**: use the first tier that is available, and cite the tier and
  source every time:
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
   measure that gap instead.
2. **Find the trend.** Collect every data point in the ledger: observations
   (`ledger.py series`) and the dated numbers in events, legacy ones included
   as context. Look in other sections too. If the milestone's quantity has no
   series, tie it to a **driver** that does, and say how the milestone maps
   onto the driver's units. For example, an AI-written 10,000-line patch maps
   onto METR task horizons (robots-software KPI); robots doing a full shift
   maps onto the software autonomy trend plus hardware unit volumes. Cite
   another section's data in `calc` (registered metric id, values, event ids);
   `evidence` lists only this section's events. Known gap: a new observation
   of a foreign driver does not re-assess the milestone (TODO.md). "No
   series in the ledger" is a gap to work around (a driver, a reference class,
   or a gather request in `blockers`), not an ETA.
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
     repeated or selected (one accepted patch, one paper, one demo), use the
     50 % horizon or success rate. Use 80 % or higher only when the milestone
     needs sustained reliability (full shifts, unattended operation).
   - **central rate**: the currently measured rate (the KPI window) is the
     median case unless a named constraint will slow it down. The slower
     long-run rate is the p90 case, not the median.
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
   deep-tech schedules, but do not ignore them), and with the previous ETA.
   When the methods disagree, explain which you weight and why.
5. **Set the median and the range.** p50 is the year you think is as likely
   to be late as early. p10 and p90 bound an 80 % interval; p90 may be null
   ("maybe never, or after 2100"). Uncertainty **widens the range; it does
   not push the median later.** Do not default to ">10 years" because the
   question is hard or the data are thin. If the median is honestly far away,
   show the calculation that puts it there. For a near ETA, one year is a
   large share of the remaining time (a third of a 3-year horizon), so every
   year added to the median needs its own line in `calc`.
6. **Name the cruxes**: what observation would move the ETA earlier or later.
   Gather can look for exactly those next time.

### 4.2 Assumed gates (`assumes:` in framework.yaml)

A milestone may stand for a capability, while its wording also passes through
a gate that is not the point: an editorial policy, or a project's rules on
AI-submitted code. The framework then names that gate in the milestone's
`assumes:` field. In that case:
- the ETA and the status are judged **as if the assumption held**. The gate
  never makes the milestone "Blocked", and it adds no policy lag to the ETA;
- `basis.eta.assumes` repeats the assumption, the label marks the ETA with an
  asterisk ("ETA ~2030*"), and `basis.blockers` reports the gate's real state;
- `achieved` still needs an event that meets the literal wording. An event
  that meets everything except the assumed gate supports green, not achieved.

ETAs come from trend extrapolation, not roadmaps: a roadmap is not a trend,
and projections alone never move a status (rule 5). But a measured
exponential *is* evidence, and it must be extrapolated as an exponential.

## 5. Stability rules (hysteresis; \* = enforced by `ledger.py check`)

1. \* A status change needs at least one evidence record with known_at after
   the previous assessment's made_at. For a KPI, a newer observation of its
   assessed metric also counts. Exceptions: a rubric correction (rule 4), and
   moves to or from `unknown`.
2. The trigger must hold for a full window (KPI) or be a verified event
   (milestone). One observation never flips a status.
3. Reverting to the previous status within 12 months requires naming the
   observation that reversed it and explaining why the earlier change was not
   a transient.
4. \* Reinterpretation under a new rubric version: a record whose previous
   assessment predates this rubric version (no rubric, or an older version)
   may re-judge it with `"rubric_correction": "v3"`, without claiming new
   evidence; it must say what the old assessment got wrong. A record that is
   already under the current version is never "corrected": changing it needs
   newer evidence (rule 1).
5. Projections alone never change a status. They may inform the label.
6. \* A change to a target's framework.yaml definition permits one re-assessment of
   that target that ignores rules 1–4 and the terminality of `achieved`. It
   sets `"definition_change": "<mechanism commit of the framework.yaml change>"` and
   judges the evidence against the new wording.

## 6. Writing the record

- **label** = "<Verdict>: <level>, <trend> vs <benchmark>", at most 100 chars.
  \* The verdict word must be one of those bound to the status (table in §1).
  It must also match the window trend: no "Worsening" when nothing worsened.
- **rationale**: prose that is consistent with the basis.
- **evidence**: the ids of the events relied on. Only `unknown` may have none.
- \* **rubric** "v3" and a structured **basis**. Its keys are listed in
  DESIGN.md §3 (Assessment); for KPIs it includes the window numbers, so the
  judgment can be checked.
- \* For a milestone that is neither achieved nor unknown, **basis.eta** is an object
  `{p10, p50, p90, method, calc, cruxes}` (§4.1). p10 ≤ p50 ≤ p90 are
  calendar years (p90 may be null), and p50 is not before made_at. The
  status must agree with p50: green ≤ made_at + 5 years, yellow ≤ made_at +
  10 years. `method` names the model (trend, driver trend, learning curve,
  S-curve, structural floor, reference class, discounted proponent date, or a
  combination). `calc` gives the numbers and arithmetic. `cruxes` says what
  would move the ETA earlier or later. For a milestone with `assumes:`, it
  also has `assumes` (§4.2).
- The milestone **label** quotes the median: "..., ETA ~2034", or "ETA
  ~2034*" under an assumed gate. `ledger.py check` warns when the latest
  assessment of a gated milestone lacks the asterisk or `basis.eta.assumes`.
