# Status rubric v1

Co-designed 2026-09-30 (best-mode draft, adapted). Applies to assessment records
in `ledger/assessments/<section>.jsonl` (DESIGN.md §3). Can be fine-tuned later;
any change is a new rubric version.

The status answers one Board question per target type:
- **KPI**: is the needle moving at the pace the goal needs?
- **Milestone**: on today's evidence, when do we get there?

The absolute level, and the distance to the goal, are REPORTED in the label but
never SCORED. Values: `green` | `yellow` | `red` for both types, and `achieved`
for milestones only. No assessment means unknown: never encode ignorance or
"mixed" as yellow.

## KPI (pace vs need)

`metrics/kpi-assessment.csv` fixes per section: the assessed metric,
goal_direction, trend window, pace benchmark and benchmark source. Assessors do
not choose these; changing one is a reviewed registry edit.
- **Assessed quantity**: the series itself for level or flow KPIs (METR horizon,
  $/kg, HALE, $/MWh). For stock KPIs whose goal is to stop accumulating (CO₂ ppm)
  it is the multi-year growth rate, with goal_direction = down to ≤ 0. The stock
  level goes in the label only.
- **Window**: at least the dominant noise cycle, and at least 3 observations. Judge
  the current window against the previous non-overlapping window (or
  half-windows), never two adjacent points.
- **Benchmark**, first available tier:
  1. an external required path for the endeavor goal;
  2. the pace implied by the nearest milestone at its stated horizon;
  3. the KPI's own long-run trend (≥ 5 years).

  Cite the tier and source every time.
- **green**: the window trend moves in the goal direction at ≥ the benchmark pace.
- **yellow**: the window trend moves clearly in the goal direction (beyond noise), but
  below the benchmark pace.
- **red**: the window trend is flat within noise (stalled), or moves in the wrong
  direction (regressing).
- **Transients**: a deviation is transient iff it spans less than one window AND has
  a named cause with an expected reversal (ENSO, pandemic, a one-off). Transients
  move the status in NEITHER direction. A transient becomes real when the next
  scheduled observation confirms it, or when that observation is overdue by more
  than one cadence plus the release lag.
- **Stale or missing data**: data_as_of = the latest effective observation. If
  made_at − data_as_of > 2 cadences + lag, the label starts "Stale (data to
  YYYY):" and the status is carried. With no registered series covering the
  window there is no KPI assessment; narrative cannot substitute for numbers.

## Milestone (ETA on evidence)

- **achieved**: at least one verified (non-legacy) event of kind `achievement`, from
  a primary source, that meets the milestone's literal wording, including any
  "definitively" clause. Terminal; reopened only via a retraction event.
- **green**: a specific evidenced path with ETA ≤ 5 years: a funded programme, plus a
  demonstrated precursor at relevant scale, plus non-proponent corroboration.
- **yellow**: measurable progress on the milestone's own quantity, with a credible
  ETA of 5–10 years; or an ETA ≤ 5 years asserted only by the proponent
  (announced but not achieved).
- **red**: an ETA over 10 years on any evidenced path (trend extrapolation, not
  roadmaps); no path; stalled (no progress over two windows); regressing; or
  structurally blocked (policy, legal or definitional), whatever the technical
  readiness. Name the block and its type.
- Events of kind `announcement` or `projection` never lift a status by themselves.

## Hysteresis (\* = enforced by `ledger.py check`)

1. \* A status change needs at least one evidence record with known_at after the
   previous assessment's made_at, unless it is a rubric correction (rule 4).
2. The trigger must hold for a full window (KPI) or be a verified event
   (milestone). One observation never flips a status.
3. Reverting to the previous status within 12 months requires naming the
   observation that reversed and why the earlier change was not a transient.
4. \* Reinterpretation under a new rubric version is allowed once per target and
   version: `"rubric_correction": "v1"`, with no claim of new evidence, and it
   must say what the old assessment got wrong.
5. Projections alone never change a status; they may inform the label.

## Label and basis

- **label** = "<Verdict>: <level>, <trend> vs <benchmark>" (≤ 100 chars). \* The
  verdict word is bound to the status:

  | status | verdict words |
  |---|---|
  | green | Ahead, On track |
  | yellow | Behind pace, Progressing |
  | red | Off track, Stalled, Regressing, Distant, Blocked |
  | achieved | Achieved |

  The verdict must match the window trend (no "Worsening" when nothing worsened).
- \* **`rubric`**: "v1".
- \* **`basis`**: {rule, assessed_quantity, window: {current, previous}, benchmark,
  benchmark_source, transients_discounted, data_as_of, prev: {status, made_at},
  change_note}. For milestones: rule, eta, path, blockers, prev, change_note
  (window/benchmark may be null).
- **rationale**: prose that is consistent with the basis; evidence = event ids.
