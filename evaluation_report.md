# FinSight Budget Agent evaluation

Run date: 2026-11-10
Cases: 10 (7 edge/adversarial)
Attempts per case: 3

| Metric | Result | Definition |
|---|---:|---|
| pass@1 | 100% | Cases passing on the first run |
| pass@3 | 100% | Cases with at least one passing run out of three |
| pass^3 | 100% | Cases passing on all three runs |

## Per-case results

| Case | Type | Runs passed | Result |
|---|---|---:|---|
| `normal_surplus` | standard | 3/3 | PASS |
| `camera_one_time_demo_input` | standard | 3/3 | PASS |
| `affordable_recurring_cost` | standard | 3/3 | PASS |
| `recurring_cost_creates_shortfall` | edge | 3/3 | PASS |
| `existing_shortfall_both_runways` | edge | 3/3 | PASS |
| `shortfall_with_no_savings` | edge_adversarial | 3/3 | PASS |
| `exactly_zero_surplus` | edge | 3/3 | PASS |
| `one_time_cost_exceeds_savings_not_monthly_surplus` | edge_adversarial | 3/3 | PASS |
| `recurring_cost_exceeds_surplus` | edge_adversarial | 3/3 | PASS |
| `one_time_purchase_during_existing_shortfall` | edge_adversarial | 3/3 | PASS |

## Failure review

No failures occurred in these runs. Repeated identical results are expected because this agent is deterministic. This harness checks calculation behavior, not OCR accuracy, the Streamlit interface, or whether user-entered numbers are true.

## Interpretation

The harness checks budget totals, decision impact, savings runway, and the three-call upper bound. pass@3 is reported as at-least-one success among three attempts; pass^3 separately reports all three passing. Since the Budget Agent is deterministic, these repeat metrics should match unless the code or runtime changes.
