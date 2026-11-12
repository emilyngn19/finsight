"""Routes profile analysis through the finance specialist agents."""

from agents import budget_agent, goal_agent, spending_analysis_agent, what_if_agent
from coach import judge_agent, coach_agent


class PlannerAgent:
    name = "Planner Agent"

    def categorize(self, decision):
        text = str(decision.get("description", "")).strip()
        amount = float(decision.get("amount", 0) or 0)
        if text or amount:
            return [budget_agent.name, goal_agent.name, spending_analysis_agent.name, what_if_agent.name]
        return [budget_agent.name, goal_agent.name, spending_analysis_agent.name]


class Orchestrator:
    MAX_BUDGET_ATTEMPTS = 2

    def __init__(self):
        self.planner = PlannerAgent()

    def analyze(self, profile, decision, transactions, currency_symbol="$", available_surplus=None):
        decision["currency_symbol"] = currency_symbol
        plan = self.planner.categorize(decision)
        budget_attempts = []
        for attempt_number in range(1, self.MAX_BUDGET_ATTEMPTS + 1):
            budget = budget_agent.analyze(profile, decision)
            check_findings = {"budget": budget}
            if what_if_agent.name in plan:
                check_findings["what_if"] = what_if_agent.compare(budget, decision)
            review = judge_agent.review(profile, decision, check_findings)
            budget_attempts.append({
                "attempt": attempt_number,
                "tool_calls": budget["execution"]["tool_calls"],
                "judge_status": review["status"],
                "checks": review["checks"],
            })
            if review["status"] == "Reviewed":
                stop_reason = "judge_passed"
                break
            if attempt_number == self.MAX_BUDGET_ATTEMPTS:
                stop_reason = "maximum_attempts_reached"

        budget["execution"] = {
            "max_attempts": self.MAX_BUDGET_ATTEMPTS,
            "attempt_count": len(budget_attempts),
            "attempts": budget_attempts,
            "tool_call_count": sum(len(item["tool_calls"]) for item in budget_attempts),
            "max_tool_calls_per_attempt": budget_agent.MAX_TOOL_CALLS,
            "stop_reason": stop_reason,
        }
        goals = goal_agent.analyze(profile, decision, available_surplus)
        spending = spending_analysis_agent.analyze(transactions, budget["monthly_expenses"], currency_symbol)
        findings = {"budget": budget, "goals": goals, "spending": spending}
        if what_if_agent.name in plan:
            findings["what_if"] = what_if_agent.compare(budget, decision)
        findings["judge"] = review
        findings["coach"] = coach_agent.explain(decision, findings, review)
        return {"plan": plan, "findings": findings}


orchestrator = Orchestrator()
