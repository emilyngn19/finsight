# FinSight public demo

FinSight is a Streamlit personal-budget planning prototype. It accepts user-entered income, expenses, savings, savings goals, transactions, and an optional purchase decision. Its agents use deterministic Python calculations; there is no bank integration, external language model, payment connection, or money movement.

## Run locally

```bash
python3 -m pip install -r requirements.txt
streamlit run app.py
```

## Public demo mode

Set `FINSIGHT_PUBLIC_DEMO=1` in the hosting platform's environment-variable settings before launch. Public mode forces anonymous sessions, skips loading or saving `profiles.json`, and limits each browser session to 10 agent-team runs. The Budget Agent has a hard limit of three calculation-tool calls per run. Users can still enter data and apply a suggested contribution to their in-session plan; the app cannot transfer money.

Do not commit `profiles.json`, the legacy JSON data files, credentials, or real financial information. The `.gitignore` excludes these files. The public app should use synthetic or user-entered demo data only.

## Deploy with Streamlit Community Cloud

1. Put this project in a GitHub repository. Keep the repository private if you do not want the source code public; never include local data files or secrets. If it is private, connect Streamlit Community Cloud to that repository.
2. In Streamlit Community Cloud, deploy the repository with `app.py` as the entry point and choose a short custom subdomain if available.
3. In the app's Secrets settings, add `FINSIGHT_PUBLIC_DEMO = "1"`, then reboot the app.
4. In the app settings under Sharing, set **Who can view this app** to public. A private source repository does not automatically make its app public.
5. Open the generated `*.streamlit.app` URL in a private browser window and confirm it works without sign-in. The URL is the public link to share.

Hosting requires connecting a GitHub account and deploying from that account. Do not share personal financial data in the public demo.

## Evaluation

Run the deterministic Budget Agent evaluation harness:

```bash
python3 evaluate_budget_agent.py
```

It evaluates 10 cases three times each and writes `evaluation_report.md`. See `GOVERNANCE.md` for the data-handling, human-gate, and accountability note.
