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
        amount = float(decision.get("amount", 0) or 0)
        symbol = decision.get("currency_symbol", "$")
        recurring = decision.get("kind") == "Monthly recurring"
        emergency_target = max(0.0, float(decision.get("emergency_reserve_target", 0) or 0))
        current_savings = float(budget.get("current_savings", 0) or 0)
        reserve_gap = max(0.0, emergency_target - current_savings)
        if amount > 0:
            if recurring:
                available = float(budget.get("current_surplus", 0) or 0)
                projected = float(budget.get("projected_monthly_surplus", 0) or 0)
                if projected < -0.005:
                    affordability = "Not affordable"
                    assessment = (
                        f"NO — this {symbol}{amount:,.2f} monthly payment is above the amount left after listed expenses. "
                        f"It would leave a shortfall of {symbol}{abs(projected):,.2f} each month."
                    )
                    if reserve_gap > 0.005:
                        assessment += f" Your emergency savings are also {symbol}{reserve_gap:,.2f} below the selected target."
                elif projected <= 0.005:
                    affordability = "Tight"
                    assessment = (
                        f"TIGHT — this payment fits exactly within the {symbol}{available:,.2f} currently left each month, "
                        "leaving no monthly margin for unexpected costs or changes."
                    )
                    if reserve_gap > 0.005:
                        assessment += f" Your emergency savings are {symbol}{reserve_gap:,.2f} below the selected target."
                elif reserve_gap > 0.005:
                    affordability = "Tight"
                    assessment = (
                        f"TIGHT — this payment fits the monthly budget, but your emergency savings are "
                        f"{symbol}{reserve_gap:,.2f} below the selected target. Consider building that reserve before adding the payment."
                    )
                else:
                    affordability = "Affordable"
                    assessment = (
                        f"YES — based on the amounts entered, this payment leaves about {symbol}{projected:,.2f} "
                        "each month after listed expenses."
                    )
            else:
                available_above_reserve = max(0.0, current_savings - emergency_target)
                remaining = current_savings - amount
                reserve_shortfall_after = max(0.0, emergency_target - remaining)
                if remaining < emergency_target - 0.005:
                    affordability = "Not affordable"
                    remaining_text = f"-{symbol}{abs(remaining):,.2f}" if remaining < 0 else f"{symbol}{remaining:,.2f}"
                    assessment = (
                        f"NO — after this {symbol}{amount:,.2f} purchase, you would have about {remaining_text} in savings, "
                        f"which is {symbol}{reserve_shortfall_after:,.2f} below your {symbol}{emergency_target:,.2f} emergency target. "
                        f"You currently have only {symbol}{available_above_reserve:,.2f} available without dipping below that target."
                    )
                elif remaining <= emergency_target + 0.005:
                    affordability = "Tight"
                    assessment = (
                        f"TIGHT — the purchase would leave about {symbol}{remaining:,.2f}, just your selected emergency reserve, "
                        "with no savings above it."
                    )
                else:
                    affordability = "Affordable"
                    assessment = (
                        f"YES — after the purchase, about {symbol}{remaining:,.2f} would remain, including "
                        f"your protected {symbol}{emergency_target:,.2f} emergency reserve."
                    )
        else:
            affordability = "Not assessed"
            assessment = "No purchase or recurring-cost amount was entered, so affordability was not assessed."
        reconciliation = "The budget totals reconcile with the entered profile." if passed else "One or more results did not reconcile; review the entered amounts."
        return {"name": self.name, "status": "Reviewed" if passed else "Needs review", "checks": checks,
                "affordability": affordability, "assessment": assessment,
                "summary": f"{reconciliation} {assessment}"}


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
            elif change < 0:
                parts.append(f"This purchase is {currency_symbol}{abs(change):,.2f} above your current savings.")
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
            parts.append(f"Based on the information entered, {currency_symbol}{goal_analysis['allocated_to_goals']:,.2f} per month is suggested for unfinished goals and {currency_symbol}{goal_analysis['to_general_savings']:,.2f} for general savings.")
        if spending["transaction_count"]:
            parts.append(f"Your highest-spend category in the recent transactions is {spending['top_category']} (about {currency_symbol}{spending['categories'][0]['amount']:,.2f} across the logged period).")
        else:
            parts.append("Add transaction entries to see your recent top spending categories.")
        if not review["status"] == "Reviewed":
            parts.append("One or more budget totals did not reconcile, so review the entries before relying on this summary.")
        return {"name": self.name, "summary": " ".join(parts), "basis": f"{currency_symbol}{amount:,.2f} {decision.get('kind', 'decision').lower()}" if amount else "Current profile snapshot"}


judge_agent = JudgeAgent()
coach_agent = CoachAgent()
