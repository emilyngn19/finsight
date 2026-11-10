"""Repeatable, dependency-free evaluation for the FinSight Budget Agent."""

from datetime import date
from pathlib import Path

from agents import budget_agent


CASES = [
    {
        "id": "normal_surplus",
        "type": "standard",
        "profile": {"income": 4000, "savings": 5000, "expenses": [{"Monthly amount ($)": 2500}]},
        "decision": {"amount": 0, "kind": "One-time"},
        "expected": {"current_surplus": 1500, "projected_monthly_surplus": 1500, "current_runway_months": None, "projected_runway_months": None, "tool_call_count": 1},
    },
    {
        "id": "camera_one_time_demo_input",
        "type": "standard",
        "profile": {"income": 2500, "savings": 2000, "expenses": [{"Monthly amount ($)": 1750}]},
        "decision": {"description": "buy a camera", "amount": 500, "kind": "One-time"},
        "expected": {"current_surplus": 750, "projected_monthly_surplus": 750, "projected_savings_after_decision": 1500, "current_runway_months": None, "projected_runway_months": None, "tool_call_count": 1},
    },
    {
        "id": "affordable_recurring_cost",
        "type": "standard",
        "profile": {"income": 4000, "savings": 6000, "expenses": [{"Monthly amount ($)": 3000}]},
        "decision": {"amount": 500, "kind": "Monthly recurring"},
        "expected": {"current_surplus": 1000, "projected_monthly_surplus": 500, "projected_runway_months": None, "tool_call_count": 1},
    },
    {
        "id": "recurring_cost_creates_shortfall",
        "type": "edge",
        "profile": {"income": 3000, "savings": 1200, "expenses": [{"Monthly amount ($)": 2800}]},
        "decision": {"amount": 250, "kind": "Monthly recurring"},
        "expected": {"current_surplus": 200, "projected_monthly_surplus": -50, "current_runway_months": None, "projected_runway_months": 24, "tool_call_count": 2},
    },
    {
        "id": "existing_shortfall_both_runways",
        "type": "edge",
        "profile": {"income": 2500, "savings": 1500, "expenses": [{"Monthly amount ($)": 3000}]},
        "decision": {"amount": 0, "kind": "One-time"},
        "expected": {"current_surplus": -500, "projected_monthly_surplus": -500, "current_runway_months": 3, "projected_runway_months": 3, "tool_call_count": 3},
    },
    {
        "id": "shortfall_with_no_savings",
        "type": "edge_adversarial",
        "profile": {"income": 1000, "savings": 0, "expenses": [{"Monthly amount ($)": 1200}]},
        "decision": {"amount": 0, "kind": "One-time"},
        "expected": {"current_surplus": -200, "projected_monthly_surplus": -200, "current_runway_months": 0, "projected_runway_months": 0, "tool_call_count": 3},
    },
    {
        "id": "exactly_zero_surplus",
        "type": "edge",
        "profile": {"income": 2000, "savings": 500, "expenses": [{"Monthly amount ($)": 2000}]},
        "decision": {"amount": 0, "kind": "One-time"},
        "expected": {"current_surplus": 0, "projected_monthly_surplus": 0, "current_runway_months": None, "projected_runway_months": None, "tool_call_count": 1},
    },
    {
        "id": "one_time_cost_exceeds_savings_not_monthly_surplus",
        "type": "edge_adversarial",
        "profile": {"income": 3500, "savings": 400, "expenses": [{"Monthly amount ($)": 3000}]},
        "decision": {"amount": 600, "kind": "One-time"},
        "expected": {"current_surplus": 500, "projected_monthly_surplus": 500, "projected_savings_after_decision": -200, "projected_runway_months": None, "tool_call_count": 1},
    },
    {
        "id": "recurring_cost_exceeds_surplus",
        "type": "edge_adversarial",
        "profile": {"income": 4000, "savings": 100, "expenses": [{"Monthly amount ($)": 3000}]},
        "decision": {"amount": 1250, "kind": "Monthly recurring"},
        "expected": {"current_surplus": 1000, "projected_monthly_surplus": -250, "projected_runway_months": 0.4, "tool_call_count": 2},
    },
    {
        "id": "one_time_purchase_during_existing_shortfall",
        "type": "edge_adversarial",
        "profile": {"income": 2500, "savings": 1600, "expenses": [{"Monthly amount ($)": 3000}]},
        "decision": {"amount": 500, "kind": "One-time"},
        "expected": {"current_surplus": -500, "projected_monthly_surplus": -500, "projected_savings_after_decision": 1100, "current_runway_months": 3.2, "projected_runway_months": 2.2, "tool_call_count": 3},
    },
]

REPEATS = 3
FIELDS = sorted({field for case in CASES for field in case["expected"]})


def matches(result, expected):
    for key, target in expected.items():
        actual = result.get("execution", {}).get(key) if key == "tool_call_count" else result.get(key)
        if target is None:
            if actual is not None:
                return False, f"{key}: expected None, got {actual!r}"
        elif isinstance(target, (int, float)) and not isinstance(target, bool):
            if actual is None or abs(float(actual) - target) > 1e-6:
                return False, f"{key}: expected {target}, got {actual!r}"
        elif actual != target:
            return False, f"{key}: expected {target!r}, got {actual!r}"

    execution = result.get("execution", {})
    if execution.get("tool_call_count", 0) > execution.get("max_tool_calls", 0):
        return False, "tool-call hard cap exceeded"
    return True, ""


def run_case(case):
    result = budget_agent.analyze(case["profile"], case["decision"])
    passed, detail = matches(result, case["expected"])
    return passed, result, detail


def main():
    runs = {}
    failures = []
    for case in CASES:
        outcomes = []
        for attempt in range(1, REPEATS + 1):
            passed, result, mismatch = run_case(case)
            outcomes.append(passed)
            if not passed:
                failures.append(f"{case['id']} run {attempt}: {mismatch}")
        runs[case["id"]] = outcomes

    pass_at_1 = sum(flags[0] for flags in runs.values()) / len(CASES)
    pass_at_3 = sum(any(flags) for flags in runs.values()) / len(CASES)
    pass_all_3 = sum(all(flags) for flags in runs.values()) / len(CASES)

    lines = [
        "# FinSight Budget Agent evaluation",
        "",
        f"Run date: {date.today().isoformat()}",
        f"Cases: {len(CASES)} ({sum('edge' in case['type'] for case in CASES)} edge/adversarial)",
        f"Attempts per case: {REPEATS}",
        "",
        "| Metric | Result | Definition |",
        "|---|---:|---|",
        f"| pass@1 | {pass_at_1:.0%} | Cases passing on the first run |",
        f"| pass@3 | {pass_at_3:.0%} | Cases with at least one passing run out of three |",
        f"| pass^3 | {pass_all_3:.0%} | Cases passing on all three runs |",
        "",
        "## Per-case results",
        "",
        "| Case | Type | Runs passed | Result |",
        "|---|---|---:|---|",
    ]
    for case in CASES:
        flags = runs[case["id"]]
        label = "PASS" if all(flags) else "FAIL"
        lines.append(f"| `{case['id']}` | {case['type']} | {sum(flags)}/{REPEATS} | {label} |")
    lines.extend(["", "## Failure review", ""])
    if failures:
        lines.extend(["Failures were inspected; each mismatch is listed below:", ""])
        lines.extend(f"- {failure}" for failure in failures)
    else:
        lines.append("No failures occurred in these runs. Repeated identical results are expected because this agent is deterministic. This harness checks calculation behavior, not OCR accuracy, the Streamlit interface, or whether user-entered numbers are true.")
    lines.extend([
        "",
        "## Interpretation",
        "",
        "The harness checks budget totals, decision impact, savings runway, and the three-call upper bound. pass@3 is reported as at-least-one success among three attempts; pass^3 separately reports all three passing. Since the Budget Agent is deterministic, these repeat metrics should match unless the code or runtime changes.",
        "",
    ])
    report = "\n".join(lines)
    Path(__file__).with_name("evaluation_report.md").write_text(report)
    print(report)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
