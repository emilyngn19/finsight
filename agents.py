"""Deterministic finance specialists used by the FinSight prototype."""

from datetime import date, datetime, timedelta


class BudgetAgent:
    name = "Budget Agent"
    MAX_TOOL_CALLS = 3

    @staticmethod
    def savings_runway(savings, monthly_surplus):
        if monthly_surplus >= 0:
            return None
        monthly_shortfall = abs(monthly_surplus)
        return max(0.0, savings) / monthly_shortfall

    def _calculate_monthly_budget(self, profile, decision):
        income = float(profile.get("income", 0) or 0)
        expenses = profile.get("expenses", [])
        monthly_expenses = sum(float(row.get("Monthly amount ($)", 0) or 0) for row in expenses)
        surplus = income - monthly_expenses
        savings = float(profile.get("savings", 0) or 0)
        amount = float(decision.get("amount", 0) or 0)
        recurring = decision.get("kind") == "Monthly recurring"
        projected_surplus = surplus - amount if recurring else surplus
        projected_savings = savings if recurring else savings - amount
        return {
            "name": self.name,
            "income": income,
            "monthly_expenses": monthly_expenses,
            "current_surplus": surplus,
            "decision_amount": amount,
            "projected_monthly_surplus": projected_surplus,
            "current_savings": savings,
            "projected_savings_after_decision": projected_savings,
            "current_runway_months": None,
            "projected_runway_months": None,
            "is_recurring": recurring,
        }

    def analyze(self, profile, decision):
        """Run budget calculation tools, stopping at completion or the hard cap."""
        tool_calls = []
        pending_tools = ["calculate_monthly_budget"]
        budget = None

        while pending_tools and len(tool_calls) < self.MAX_TOOL_CALLS:
            tool_name = pending_tools.pop(0)
            if tool_name == "calculate_monthly_budget":
                budget = self._calculate_monthly_budget(profile, decision)
                observation = (
                    f"Monthly expenses {budget['monthly_expenses']:.2f}; "
                    f"current surplus {budget['current_surplus']:.2f}; "
                    f"projected surplus {budget['projected_monthly_surplus']:.2f}."
                )
                tool_calls.append({"tool": tool_name, "observation": observation})
                if budget["current_surplus"] < 0:
                    pending_tools.append("estimate_current_savings_runway")
                if budget["projected_monthly_surplus"] < 0:
                    pending_tools.append("estimate_projected_savings_runway")
            elif tool_name == "estimate_current_savings_runway":
                budget["current_runway_months"] = self.savings_runway(
                    budget["current_savings"], budget["current_surplus"]
                )
                tool_calls.append({
                    "tool": tool_name,
                    "observation": f"Current savings runway: {budget['current_runway_months']:.1f} months.",
                })
            elif tool_name == "estimate_projected_savings_runway":
                budget["projected_runway_months"] = self.savings_runway(
                    budget["projected_savings_after_decision"], budget["projected_monthly_surplus"]
                )
                tool_calls.append({
                    "tool": tool_name,
                    "observation": f"Projected savings runway: {budget['projected_runway_months']:.1f} months.",
                })

        budget["execution"] = {
            "max_tool_calls": self.MAX_TOOL_CALLS,
            "tool_calls": tool_calls,
            "tool_call_count": len(tool_calls),
            "stop_reason": "maximum_tool_calls_reached" if pending_tools else "task_complete",
        }
        return budget


class GoalAgent:
    name = "Goal Agent"

    def analyze(self, profile, decision, available_surplus=None):
        goals = profile.get("goals", [])
        planned_surplus = float(profile.get("income", 0) or 0) - sum(
            float(row.get("Monthly amount ($)", 0) or 0) for row in profile.get("expenses", [])
        )
        surplus_before_decision = planned_surplus if available_surplus is None else float(available_surplus)
        amount = float(decision.get("amount", 0) or 0)
        recurring = decision.get("kind") == "Monthly recurring"
        goal_budget = max(0.0, surplus_before_decision - (amount if recurring else 0.0))

        eligible = []
        for goal_index, goal in enumerate(goals):
            target = float(goal.get("Target ($)", 0) or 0)
            current = float(goal.get("Saved so far ($)", 0) or 0)
            requested = max(0.0, float(goal.get("Monthly contribution ($)", 0) or 0))
            if target <= 0:
                continue
            remaining = max(0.0, target - current)
            adjusted_remaining = remaining
            if adjusted_remaining > 0:
                eligible.append({
                    "goal_index": goal_index,
                    "goal": str(goal.get("Goal", "Savings goal")),
                    "target": target,
                    "saved": current,
                    "remaining": remaining,
                    "adjusted_remaining": adjusted_remaining,
                    "requested": requested,
                })

        allocations = [min(item["requested"], item["adjusted_remaining"]) for item in eligible]
        requested_total = sum(allocations)
        if requested_total > goal_budget and requested_total > 0:
            allocations = [value * goal_budget / requested_total for value in allocations]
        else:
            extra = max(0.0, goal_budget - requested_total)
            # Honor each goal's requested contribution first, then spread the
            # remaining surplus by the size of each unfinished goal.
            for _ in range(len(eligible) + 1):
                if extra <= 0.005:
                    break
                open_goals = [
                    i for i, item in enumerate(eligible)
                    if item["adjusted_remaining"] - allocations[i] > 0.005
                ]
                if not open_goals:
                    break
                weight_total = sum(eligible[i]["adjusted_remaining"] for i in open_goals)
                distributed = 0.0
                for i in open_goals:
                    share = extra * eligible[i]["adjusted_remaining"] / weight_total
                    addition = min(share, eligible[i]["adjusted_remaining"] - allocations[i])
                    allocations[i] += addition
                    distributed += addition
                extra -= distributed
                if distributed <= 0.005:
                    break

        results = []
        for item, suggested in zip(eligible, allocations):
            months = item["adjusted_remaining"] / suggested if suggested > 0 else None
            results.append({
                "goal_index": item["goal_index"],
                "goal": item["goal"],
                "target": item["target"],
                "saved": item["saved"],
                "remaining": item["remaining"],
                "requested_monthly_contribution": item["requested"],
                "monthly_contribution": round(suggested, 2),
                "suggested_monthly_contribution": round(suggested, 2),
                "estimated_months": round(months, 1) if months is not None else None,
            })
        allocated_to_goals = sum(row["suggested_monthly_contribution"] for row in results)
        return {
            "name": self.name,
            "goals": results,
            "monthly_surplus": planned_surplus,
            "available_surplus": round(goal_budget, 2),
            "allocated_to_goals": round(allocated_to_goals, 2),
            "to_general_savings": round(max(0.0, goal_budget - allocated_to_goals), 2),
            "recurring_decision_applied": recurring,
        }


class SpendingAnalysisAgent:
    name = "Spending Analysis Agent"

    def analyze(self, transactions, monthly_expenses, currency_symbol="$"):
        cutoff = date.today() - timedelta(days=90)
        recent = []
        for transaction in transactions:
            try:
                tx_date = datetime.strptime(transaction.get("Date", ""), "%Y-%m-%d").date()
            except (TypeError, ValueError):
                continue
            amount = float(transaction.get("Amount ($)", 0) or 0)
            if tx_date >= cutoff and amount >= 0:
                recent.append({"date": tx_date, "category": str(transaction.get("Category", "Other")), "amount": amount})
        if not recent:
            return {"name": self.name, "transaction_count": 0, "total_90_days": 0.0, "average_monthly": 0.0, "top_category": None, "categories": [], "message": "No transaction entries from the last 90 days yet. Add transactions to reveal spending patterns."}
        category_totals = {}
        for tx in recent:
            category_totals[tx["category"]] = category_totals.get(tx["category"], 0.0) + tx["amount"]
        total = sum(category_totals.values())
        ordered = sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
        return {
            "name": self.name,
            "transaction_count": len(recent),
            "total_90_days": round(total, 2),
            "average_monthly": round(total / 3, 2),
            "top_category": ordered[0][0] if ordered else None,
            "categories": [{"category": key, "amount": round(value, 2)} for key, value in ordered],
            "message": f"{len(recent)} transactions total {currency_symbol}{total:,.2f} over the last 90 days.",
        }


class WhatIfAgent:
    name = "What-if Agent"

    def compare(self, budget, decision):
        amount = float(decision.get("amount", 0) or 0)
        recurring = decision.get("kind") == "Monthly recurring"
        current_surplus = float(budget["current_surplus"])
        current_savings = float(budget["current_savings"])
        if recurring:
            reductions = [0.0, 0.1, 0.2, 0.5, 1.0]
            descriptions = [
                "Proceed at the full monthly cost",
                "Find an option 10% less expensive",
                "Find an option 20% less expensive",
                "Find an option 50% less expensive",
                "Skip the recurring expense",
            ]
            values = [current_surplus - amount * (1 - reduction) for reduction in reductions]
            metric = "Monthly amount left after expenses"
        else:
            descriptions = [
                "Buy now at the full price",
                "Find an option 10% less expensive",
                "Find an option 20% less expensive",
                "Save for 3 months, then buy at full price",
                "Save for 6 months, then buy at full price",
                "Do not buy; keep the savings",
            ]
            values = [
                current_savings - amount,
                current_savings - amount * 0.9,
                current_savings - amount * 0.8,
                current_savings + max(0.0, current_surplus) * 3 - amount,
                current_savings + max(0.0, current_surplus) * 6 - amount,
                current_savings,
            ]
            metric = "Savings remaining after purchase"
        return {
            "name": self.name,
            "metric": metric,
            "scenarios": [{"scenario": label, "amount": round(value, 2)} for label, value in zip(descriptions, values)],
            "recommendation": "Compare the trade-offs using your actual priorities; the delayed option assumes your current monthly surplus stays the same.",
        }


budget_agent = BudgetAgent()
goal_agent = GoalAgent()
spending_analysis_agent = SpendingAnalysisAgent()
what_if_agent = WhatIfAgent()
