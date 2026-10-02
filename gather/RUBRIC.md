# Status rubric (v1)

Every KPI and milestone in README.md carries a **status**: a colour plus a
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

Co-designed 2026-09-30. Any change in meaning is a new rubric version (rule 4).

## 1. What the colours mean

A status answers a different question for each kind of target:
- **KPI**: is the needle moving toward the goal at the pace the goal needs? The
  status scores the **trend**, never the level.
- **Milestone**: on today's evidence, **when** do we get there?

| status | KPI | milestone | label starts with |
|---|---|---|---|
| green | moving toward the goal at or above the needed pace | ≤ 5 years on an evidenced path | Ahead, On track |
| yellow | clearly moving toward the goal, but too slowly | measurable progress, ETA 5–10 years (or ≤ 5 years claimed only by the proponent) | Behind pace, Progressing |
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

These are the climate assessments made on 2026-09-30.

**KPI (red).** Label: "Regressing: 427.35 ppm (2025); 10-yr growth 2.56 vs 2.15
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

**Milestone "The Bend" (yellow).** Label: "Progressing: GHG 54.1 GtCO2e (2025,
+0.7%), +0.3% Jan-Jul 2026, plateau; ETA 5-10 yrs".
- It is not achieved: emissions still rose in 2025, and no verified event shows
  the peak "definitively" behind us.
- There is measurable progress on the milestone's own quantity: CO₂ growth
  slowed from 1.9 %/yr (2005–2014) to 0.3 %/yr (2015–2024).
- That gives a credible ETA of 5–10 years, so the status is yellow.
- A projected fall in 2026 is only a projection, so it cannot lift the status.

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

- **achieved**: at least one verified (non-legacy) event of kind `achievement`,
  from a primary source, that meets the milestone's literal wording, including
  any "definitively" clause. It is terminal: only a retraction event reopens it.
- **green**: a specific evidenced path with ETA ≤ 5 years. That means all three
  of: a funded programme, a demonstrated precursor at relevant scale, and
  corroboration from someone other than the proponent.
- **yellow**: measurable progress on the milestone's own quantity, with a
  credible ETA of 5–10 years; or an ETA ≤ 5 years asserted only by the
  proponent (announced but not achieved).
- **red**: any of:
  - an ETA over 10 years on any evidenced path (judged by trend extrapolation,
    not roadmaps);
  - no path;
  - stalled (no progress over two windows);
  - regressing;
  - structurally blocked (policy, legal or definitional), whatever the
    technical readiness. Name the block and its type.
- Events of kind `announcement` or `projection` never lift a status by
  themselves.

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
   assessment predates this rubric version may re-judge it with
   `"rubric_correction": "v1"`, without claiming new evidence; it must say
   what the old assessment got wrong. A record that is already under v1 is
   never "corrected": changing it needs newer evidence (rule 1).
5. Projections alone never change a status. They may inform the label.
6. \* A change to a target's README definition permits one re-assessment of
   that target that ignores rules 1–4 and the terminality of `achieved`. It
   sets `"definition_change": "<mechanism commit of the README change>"` and
   judges the evidence against the new wording.

## 6. Writing the record

- **label** = "<Verdict>: <level>, <trend> vs <benchmark>", at most 100 chars.
  \* The verdict word must be one of those bound to the status (table in §1).
  It must also match the window trend: no "Worsening" when nothing worsened.
- **rationale**: 2–4 sentences of prose, consistent with the basis.
- **evidence**: the ids of the events relied on. Only `unknown` may have none.
- \* **rubric** "v1" and a structured **basis**. Its keys are listed in
  DESIGN.md §3 (Assessment); for KPIs it includes the window numbers, so the
  judgment can be checked.
