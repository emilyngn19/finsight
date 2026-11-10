"""Quality review and plain-language synthesis for the prototype agents."""


class JudgeAgent:
    name = "Judge Agent"

    def review(self, profile, decision, findings):
        income = float(profile.get("income", 0) or 0)
        expense_sum = sum(float(row.get("Monthly amount ($)", 0) or 0) for row in profile.get("expenses", []))
        budget = findings.get("budget", {})
        checks = {
            "income matches profile": abs(budget.get("income", 0) - income) < 0.01,
            "expenses reconcile": abs(budget.get("monthly_expenses", 0) - expense_sum) < 0.01,
            "surplus reconciles": abs(budget.get("current_surplus", 0) - (income - expense_sum)) < 0.01,
            "scenario included when requested": not bool(decision.get("description") or decision.get("amount")) or "what_if" in findings,
        }
        passed = all(checks.values())
        return {"name": self.name, "status": "Reviewed" if passed else "Needs review", "checks": checks,
                "summary": "The budget totals reconcile with the entered profile." if passed else "One or more results did not reconcile; review the entered amounts."}


class CoachAgent:
    name = "Coach Agent"

    def explain(self, decision, findings, review):
        budget = findings["budget"]
        goal_analysis = findings["goals"]
        goals = goal_analysis.get("goals", [])
        spending = findings["spending"]
        amount = float(decision.get("amount", 0) or 0)
        currency_symbol = decision.get("currency_symbol", "$")
        recurring = decision.get("kind") == "Monthly recurring"
        change = budget["projected_monthly_surplus"] if recurring else budget["projected_savings_after_decision"]
        label = "monthly amount left" if recurring else "savings remaining after purchase"
        parts = [f"You currently have {currency_symbol}{budget['current_surplus']:,.2f} left each month after listed expenses."]
        if decision.get("description") or amount:
            if recurring:
                parts.append(f"With this {currency_symbol}{amount:,.2f} monthly cost, your estimated monthly amount left becomes {currency_symbol}{change:,.2f}.")
            else:
                parts.append(f"After a one-time {currency_symbol}{amount:,.2f} purchase, you would have about {currency_symbol}{change:,.2f} in savings remaining.")
        if budget["projected_monthly_surplus"] < 0:
            runway = budget["projected_runway_months"]
            if runway is None or runway <= 0:
                parts.append("Your budget is in a monthly shortfall, and the listed savings would not provide a runway at that burn rate.")
            else:
                parts.append(f"At the projected shortfall of {currency_symbol}{abs(budget['projected_monthly_surplus']):,.2f} per month, your savings could cover about {runway:.1f} months. This assumes the shortfall stays steady and excludes unexpected costs or income changes.")
        if goals:
            for goal in goals:
                if goal["estimated_months"] is None:
                    parts.append(f"For your {goal['goal']} goal, add a monthly contribution to estimate a target date.")
                else:
                    parts.append(f"At the suggested contribution, your {goal['goal']} goal is about {goal['estimated_months']:g} months away.")
        else:
            parts.append("Add a savings goal with a target and monthly contribution to see how this choice could affect its timeline.")
        if goal_analysis.get("available_surplus", 0) > 0:
            parts.append(f"The Goal Agent suggests directing {currency_symbol}{goal_analysis['allocated_to_goals']:,.2f} per month to unfinished goals and {currency_symbol}{goal_analysis['to_general_savings']:,.2f} to general savings.")
        if spending["transaction_count"]:
            parts.append(f"Your highest-spend category in the recent transactions is {spending['top_category']} (about {currency_symbol}{spending['categories'][0]['amount']:,.2f} across the logged period).")
        else:
            parts.append("The spending-pattern agent needs transaction entries before it can identify your top categories.")
        if not review["status"] == "Reviewed":
            parts.append("The Judge Agent flagged a reconciliation issue, so check the inputs before relying on this summary.")
        return {"name": self.name, "summary": " ".join(parts), "basis": f"{currency_symbol}{amount:,.2f} {decision.get('kind', 'decision').lower()}" if amount else "Current profile snapshot"}


judge_agent = JudgeAgent()
coach_agent = CoachAgent()
