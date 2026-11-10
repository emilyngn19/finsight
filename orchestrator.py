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
    def __init__(self):
        self.planner = PlannerAgent()

    def analyze(self, profile, decision, transactions, currency_symbol="$", available_surplus=None):
        plan = self.planner.categorize(decision)
        budget = budget_agent.analyze(profile, decision)
        goals = goal_agent.analyze(profile, decision, available_surplus)
        spending = spending_analysis_agent.analyze(transactions, budget["monthly_expenses"], currency_symbol)
        findings = {"budget": budget, "goals": goals, "spending": spending}
        if what_if_agent.name in plan:
            findings["what_if"] = what_if_agent.compare(budget, decision)
        review = judge_agent.review(profile, decision, findings)
        findings["judge"] = review
        decision["currency_symbol"] = currency_symbol
        findings["coach"] = coach_agent.explain(decision, findings, review)
        return {"plan": plan, "findings": findings}


orchestrator = Orchestrator()
