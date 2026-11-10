# FinSight governance note

**Data read and storage.** FinSight reads the income, savings, expense categories and amounts, goal targets, transaction dates/categories/amounts, and optional decision amount entered by the user. A receipt photo is temporarily written to a local temporary file for OCR and deleted after reading; extracted text and the confirmed transaction are held in the app session. In public mode (`FINSIGHT_PUBLIC_DEMO=1`), the app forces Anonymous mode, does not read or write `profiles.json`, and keeps entries only in that browser's Streamlit session. No bank data, credentials, payments, or external AI service are connected. Users should not enter sensitive real financial information.

**Human gate.** After agents calculate suggested contributions and display the goal, amount, and timeline, the user must click **Apply suggested contributions to my goal plan** before those amounts update the in-session plan. This action occurs between the Goal Agent recommendation and the local plan update. The button does not transfer funds or create a real financial transaction. Receipt OCR also requires the user to review or enter the amount and confirm **Add receipt to expenses** before it becomes a transaction.

**What a stranger can do.** Anyone with the public URL can enter sample numbers, upload a receipt image for temporary OCR, run the rule-based analyses (up to three Budget Agent calculation calls per run and ten agent-team runs per session), and update only their in-session goal plan. They cannot view another user's session through app controls, access a bank, transfer money, send email, make purchases, or delete external data. The app is a planning demo, not financial advice.

**Expansion and reason.** The Goal Agent is a second specialized agent alongside the Budget Agent. The reason is task decomposition: budget impact and savings-goal allocation are separate calculations with different inputs and outputs. The Judge Agent adds a reconciliation check before the Coach summarizes the result.

**Accountable person.** Duyen Nguyen is accountable for the agent, its behavior, its public demo, and responding to issues.
