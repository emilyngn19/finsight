# FinSight Prototype Architecture

## Purpose

FinSight is a local Streamlit prototype for entering a personal budget, reviewing spending, and comparing financial scenarios. The current agents use transparent, deterministic Python calculations; they do not call an external language model or connect to a bank.

## Workflow

`Profile + transaction entries → Planner → Specialist agents → Judge → Coach → Dashboard`

1. **Planner Agent** (`PlannerAgent`, `orchestrator.py`) routes a profile review to the relevant specialists. A proposed decision also activates the What-if Agent.
2. **Budget Agent** (`BudgetAgent`, `agents.py`) calculates monthly expenses, current surplus, and the effect of one-time or recurring costs.
3. **Goal Agent** (`GoalAgent`, `agents.py`) estimates the remaining amount and time to user-entered savings goals.
4. **Spending Analysis Agent** (`SpendingAnalysisAgent`, `agents.py`) summarizes manually entered transactions from the most recent 90 days.
5. **What-if Agent** (`WhatIfAgent`, `agents.py`) compares the proposed decision with a lower-cost option and a delayed option.
6. **Judge Agent** (`JudgeAgent`, `coach.py`) checks that core budget totals reconcile to the submitted profile.
7. **Coach Agent** (`CoachAgent`, `coach.py`) explains the results in plain language and calls out missing transaction or goal data.

The dashboard invokes the workflow from `app.py` through `orchestrator.py`. The agents are separate specialist classes, but this prototype runs them synchronously in one local Python process; it is not a distributed agent service.

The Budget Agent uses a local monthly-budget calculation tool and calls the savings-runway calculator only when a current or projected monthly shortfall exists. It stops when those calculations are complete, with a hard maximum of three calculation-tool calls per run. In public demo mode, the UI also limits each Streamlit session to ten agent-team runs. The Goal Agent is a second specialist because allocating money to a savings target is a distinct task from calculating the budget impact; the Judge checks the resulting arithmetic.

## Data and privacy

- Inputs include monthly income, savings, categorized expenses, goals, transactions, and an optional decision.
- Receipt images can be processed locally with RapidOCR; after review, the extracted total, date, and category become a transaction entry. The photo itself is temporary and is not stored in the profile.
- Saved profiles and transaction history are stored in `profiles.json` beside the app. Anonymous entries remain in the Streamlit session.
- Local profile data is not encrypted. No bank connection or remote storage is implemented.
- Set `FINSIGHT_PUBLIC_DEMO=1` when hosting publicly. This forces anonymous mode, skips loading and saving `profiles.json`, and provides a session-data clearing button. Public users should enter demo amounts, not sensitive personal financial information.
- Budget and projection math is performed in Python. Investment projections are illustrative assumptions, not guaranteed returns.

## Main files

- `app.py`: Streamlit interface, profile storage, data entry, charts, and agent result panels.
- `agents.py`: Budget, Goal, Spending Analysis, and What-if specialists.
- `orchestrator.py`: Planner routing and workflow execution.
- `coach.py`: Judge checks and Coach narrative.
- `financial_tools.py`: Earlier file-based calculation helpers; the current dashboard workflow uses the profile values passed to the agents instead.
