import json
import math
import os
import re
import tempfile
from urllib.parse import urlencode
from urllib.request import urlopen
from pathlib import Path
from datetime import date, datetime

import pandas as pd
import streamlit as st
from orchestrator import orchestrator

st.set_page_config(page_title="FinSight | Personal Finance OS", page_icon="◈", layout="wide")

PROFILE_FILE = Path(__file__).with_name("profiles.json")
PUBLIC_DEMO = os.getenv("FINSIGHT_PUBLIC_DEMO", "").strip().lower() in {"1", "true", "yes"}
MAX_AGENT_RUNS_PER_SESSION = 10
CURRENCIES = {
    "USD": "$", "CAD": "CA$", "EUR": "€", "GBP": "£", "AUD": "A$",
    "NZD": "NZ$", "JPY": "¥", "INR": "₹", "CNY": "¥", "MXN": "MX$",
    "CHF": "CHF ", "SGD": "S$", "KRW": "₩", "BRL": "R$",
}
currency_symbol = "$"
# BLS Consumer Expenditure Survey, 2023–24 two-year geographic means;
# average annual expenditures per consumer unit (household), published Dec. 2025.
BLS_AREA_ANNUAL_MEAN = {
    "Boston": 105320, "New York": 91520, "Philadelphia": 92234,
    "Chicago": 85415, "Detroit": 72297, "Minneapolis–St. Paul": 98677, "St. Louis": 77694,
    "Washington, DC": 108125, "Baltimore": 95762, "Atlanta": 83090, "Miami": 64027,
    "Dallas–Fort Worth": 81954, "Houston": 85377, "Tampa": 76152,
    "Los Angeles": 90594, "San Francisco": 117578, "San Diego": 108694,
    "Seattle": 109460, "Phoenix": 97496, "Denver": 102635,
    "Honolulu": 86564, "Anchorage": 90483,
}
DEFAULT_EXPENSES = pd.DataFrame([
    {"Category": "Housing", "Type": "Fixed", "Monthly amount ($)": 0.0},
    {"Category": "Utilities & phone", "Type": "Fixed", "Monthly amount ($)": 0.0},
    {"Category": "Insurance & debt", "Type": "Fixed", "Monthly amount ($)": 0.0},
    {"Category": "Groceries", "Type": "Variable", "Monthly amount ($)": 0.0},
    {"Category": "Transportation", "Type": "Variable", "Monthly amount ($)": 0.0},
    {"Category": "Dining & entertainment", "Type": "Variable", "Monthly amount ($)": 0.0},
    {"Category": "Other", "Type": "Variable", "Monthly amount ($)": 0.0},
])
DEFAULT_GOALS = pd.DataFrame([
    {"Goal": "Emergency fund", "Target ($)": 5000.0, "Saved so far ($)": 0.0, "Monthly contribution ($)": 0.0},
    {"Goal": "Other goal", "Target ($)": 0.0, "Saved so far ($)": 0.0, "Monthly contribution ($)": 0.0},
])

def load_profiles():
    try:
        return json.loads(PROFILE_FILE.read_text()) if PROFILE_FILE.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}

def save_profiles(profiles):
    PROFILE_FILE.write_text(json.dumps(profiles, indent=2))

def money(value):
    decimals = 0 if currency_code in {"JPY", "KRW"} else 2
    return f"{currency_symbol}{value:,.{decimals}f}"

@st.cache_resource
def get_receipt_ocr_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()

def read_receipt_image(image_bytes, suffix):
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as image_file:
        image_file.write(image_bytes)
        image_path = image_file.name
    try:
        results, _ = get_receipt_ocr_engine()(image_path)
        return "\n".join(str(item[1]) for item in (results or []) if len(item) > 1).strip()
    finally:
        os.unlink(image_path)

@st.cache_data(ttl=7 * 24 * 60 * 60)
def fetch_world_bank_countries():
    """Load countries with ISO alpha-2 codes from the World Bank API."""
    request_url = "https://api.worldbank.org/v2/country?format=json&per_page=400"
    with urlopen(request_url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if len(payload) < 2 or not payload[1]:
        raise ValueError("The World Bank country list was empty.")
    countries = []
    for item in payload[1]:
        code = str(item.get("iso2Code", "")).strip()
        region = item.get("region", {}).get("value", "")
        if code and region != "Aggregates":
            countries.append({
                "name": item["name"],
                "code": code.lower(),
                "imf_code": str(item.get("id", "")).strip().upper(),
            })
    return sorted(countries, key=lambda item: item["name"].casefold())

@st.cache_data(ttl=24 * 60 * 60)
def fetch_latest_country_inflation(country_info):
    """Fetch annual CPI inflation, falling back to IMF when World Bank is down.

    country_info contains the World Bank ISO alpha-2 and IMF alpha-3 codes.
    """
    latest_year = date.today().year
    country_code = country_info["code"]
    query = urlencode({
        "format": "json",
        "date": f"{latest_year - 10}:{latest_year}",
        "per_page": 12,
    })
    request_url = (
        f"https://api.worldbank.org/v2/country/{country_code}/indicator/"
        f"FP.CPI.TOTL.ZG?{query}"
    )
    world_bank_error = None
    for attempt in range(2):
        try:
            with urlopen(request_url, timeout=12) as response:
                payload = json.loads(response.read().decode("utf-8"))
            observations = [] if len(payload) < 2 or not payload[1] else [
                {"rate": float(item["value"]), "year": int(item["date"])}
                for item in payload[1] if item.get("value") is not None
            ]
            if observations:
                latest = max(observations, key=lambda item: item["year"])
                return {"rate": latest["rate"], "year": str(latest["year"]), "source": "World Bank"}
            world_bank_error = "no reported value was returned"
            break
        except Exception as exc:
            world_bank_error = str(exc)
    # The IMF DataMapper API is a free, keyless backup for country-level WEO
    # inflation data; its latest year can be an official estimate/forecast.
    try:
        imf_code = str(country_info.get("imf_code", "")).strip().upper()
        if not imf_code:
            raise ValueError("No IMF country code is available for this selection.")
        imf_url = f"https://www.imf.org/external/datamapper/api/v1/PCPIPCH/{imf_code}"
        with urlopen(imf_url, timeout=15) as response:
            imf_payload = json.loads(response.read().decode("utf-8"))
        values = imf_payload.get("values", {}).get("PCPIPCH", {}).get(imf_code, {})
        observations = [
            {"rate": float(value), "year": int(year)}
            for year, value in values.items()
            if value is not None and int(year) <= date.today().year
        ]
        if observations:
            latest = max(observations, key=lambda item: item["year"])
            return {
                "rate": latest["rate"], "year": str(latest["year"]),
                "source": "IMF DataMapper (latest available estimate; may be a forecast)",
            }
        raise ValueError("The IMF returned no annual inflation value for this country.")
    except Exception as imf_error:
        raise ValueError(
            f"World Bank unavailable ({world_bank_error}); IMF fallback also failed ({imf_error})."
        ) from imf_error

def parse_receipt(text, currency_code="USD"):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    comma_decimal = currency_code in {"EUR", "BRL"}
    if comma_decimal:
        currency_pattern = re.compile(r"[$€£¥₹]?\s*(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{2}))?")
    else:
        currency_pattern = re.compile(r"[$€£¥₹]?\s*(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?")

    def parsed_amount(match):
        whole, cents = match
        thousands = "." if comma_decimal else ","
        return float(whole.replace(thousands, "") + ("." + cents if cents else ".00"))
    total_terms = ("grand total", "amount due", "balance due", "total due", "total")
    amount = None
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index]
        lowered = line.lower()
        if any(term in lowered for term in total_terms) and not any(term in lowered for term in ("subtotal", "tax total", "total savings")):
            for total_line in [line] + lines[index + 1:index + 3]:
                matches = currency_pattern.findall(total_line)
                if matches:
                    amount = parsed_amount(matches[-1])
                    break
            if amount is not None:
                break
    if amount is None:
        candidates = []
        for line in lines:
            for match in currency_pattern.findall(line):
                candidates.append(parsed_amount(match))
        amount = max(candidates) if candidates else None

    receipt_date = None
    date_patterns = ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%b %d %Y")
    for line in lines:
        for pattern in date_patterns:
            match = re.search(r"\b\d{1,4}[-/]\d{1,2}[-/]\d{1,4}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b", line, re.I)
            if match:
                try:
                    receipt_date = datetime.strptime(match.group(0).replace(",", ""), pattern.replace(",", "")).date()
                    break
                except ValueError:
                    continue
        if receipt_date is not None:
            break
    date_was_read = receipt_date is not None
    receipt_date = receipt_date or date.today()

    full_text = " ".join(lines).lower()
    categories = [
        ("Transportation", ("gas station", "fuel", "shell", "chevron", "exxon", "transit", "uber", "lyft")),
        ("Groceries", ("grocery", "market", "supermarket", "whole foods", "trader joe", "safeway", "kroger", "aldi")),
        ("Dining & entertainment", ("restaurant", "cafe", "coffee", "pizza", "diner", "bar ", "doordash", "ubereats", "grubhub")),
        ("Utilities & phone", ("wireless", "mobile", "internet", "electric", "water utility")),
        ("Housing", ("property management", "rent payment", "leasing office")),
        ("Insurance & debt", ("insurance", "loan payment", "credit card payment")),
    ]
    category = next((name for name, terms in categories if any(term in full_text for term in terms)), "Other")
    merchant = next((line[:80] for line in lines[:6] if not re.search(r"receipt|invoice|tel|phone|date|\d{3}[-.) ]?\d{3}[-. ]?\d{4}", line, re.I)), "Receipt purchase")
    return {"amount": amount, "date": receipt_date, "date_was_read": date_was_read, "category": category, "merchant": merchant, "text": text}

st.sidebar.markdown('<div class="eyebrow">FINSIGHT / PERSONAL OS</div>', unsafe_allow_html=True)
st.sidebar.title("◈ Your space")
appearance = st.sidebar.radio("Appearance", ["Light", "Dark"], horizontal=True, key="appearance")

LIGHT_CSS = """
<style>
.stApp { background:#f3f6fb; color:#172033; }
[data-testid="stHeader"] { background:rgba(243,246,251,.96); }
[data-testid="stSidebar"] { background:#ffffff; border-right:1px solid #dce4ee; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] { color:#263449; }
.block-container { padding-top:2rem; max-width:1440px; }
html, body, [class*="css"] { font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
h1,h2,h3,h4 { color:#172033; letter-spacing:-.035em; }
.eyebrow { color:#087e78; font:600 12px 'DM Mono',monospace; letter-spacing:.16em; text-transform:uppercase; }
.hero { border:1px solid #dce5ef; border-radius:24px; padding:30px 34px; background:linear-gradient(115deg,#ffffff,#f8fbff); box-shadow:0 14px 38px #1c355010; margin:8px 0 26px; }
.hero h1 { margin:.3rem 0 .5rem; font-size:2.35rem; }
.hero p { color:#526176; margin:0; }
div[data-testid="stMetric"] { background:#ffffff; border:1px solid #dce5ef; padding:18px 20px; border-radius:18px; box-shadow:0 5px 18px #1c355008; }
div[data-testid="stMetricLabel"] { color:#526176; }
div[data-testid="stMetricValue"] { color:#172033; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
div[data-testid="stForm"] { background:#ffffff; border:1px solid #dce5ef; padding:22px; border-radius:20px; }
div[data-testid="stExpander"] { background:#ffffff; border:1px solid #dce5ef; border-radius:14px; }
[data-testid="stDataFrame"], [data-testid="stTable"] { background:#ffffff; }
[data-baseweb="input"] > div, [data-baseweb="select"] > div, [data-baseweb="textarea"] { background:#ffffff; }
div.stButton > button[kind="primaryFormSubmit"], div.stButton > button[kind="primary"] { background:#087e78; border:0; color:#ffffff; font-weight:700; border-radius:12px; }
div.stButton > button[kind="secondary"] { background:#ffffff; border:1px solid #cbd5e1; color:#263449; border-radius:12px; }
hr { border-color:#dce5ef; }
</style>
"""

DARK_CSS = """
<style>
.stApp { background:radial-gradient(ellipse at 70% -15%,#17315a 0%,#0a1221 42%,#070b13 100%); color:#e7eff8; }
[data-testid="stHeader"] { background:transparent; }
[data-testid="stSidebar"] { background:linear-gradient(180deg,#101a2a,#0b111d); border-right:1px solid #25364b; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"], [data-testid="stSidebar"] label, [data-testid="stSidebar"] p { color:#c5d4e2; }
.block-container { padding-top:2rem; max-width:1440px; }
html, body, [class*="css"] { font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
h1,h2,h3,h4 { color:#f2f8ff; letter-spacing:-.035em; }
.eyebrow { color:#53f1df; font:600 12px 'DM Mono',monospace; letter-spacing:.16em; text-transform:uppercase; }
.hero { border:1px solid #2b4359; border-radius:24px; padding:30px 34px; background:linear-gradient(115deg,#142a3f,#11162b); box-shadow:0 14px 38px #0005; margin:8px 0 26px; }
.hero h1 { margin:.3rem 0 .5rem; font-size:2.35rem; }
.hero p { color:#a9bfd2; margin:0; }
div[data-testid="stMetric"] { background:linear-gradient(145deg,#14263a,#101827); border:1px solid #2b4055; padding:18px 20px; border-radius:18px; }
div[data-testid="stMetricLabel"] { color:#a3b8c9; }
div[data-testid="stMetricValue"] { color:#f2f8ff; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
div[data-testid="stForm"], div[data-testid="stExpander"] { background:#101b2bcc; border:1px solid #293d53; border-radius:18px; }
div[data-testid="stForm"] { padding:22px; }
[data-testid="stDataFrame"], [data-testid="stTable"] { background:#101827; }
[data-baseweb="input"] > div, [data-baseweb="select"] > div, [data-baseweb="textarea"] { background:#172438; color:#f2f8ff; }
input, textarea { color:#f2f8ff !important; }
[data-testid="stWidgetLabel"], [data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"] { color:#c5d4e2; }
div.stButton > button[kind="primaryFormSubmit"], div.stButton > button[kind="primary"] { background:linear-gradient(100deg,#27c9bd,#8d7bf5); border:0; color:#07111f; font-weight:700; border-radius:12px; }
div.stButton > button[kind="secondary"] { background:#172438; border:1px solid #344b63; color:#e7eff8; border-radius:12px; }
hr { border-color:#293d53; }
</style>
"""
st.markdown(DARK_CSS if appearance == "Dark" else LIGHT_CSS, unsafe_allow_html=True)

profiles = {} if PUBLIC_DEMO else load_profiles()
if PUBLIC_DEMO:
    mode = "Anonymous"
    st.sidebar.caption("Public demo: anonymous session only. Entries stay temporary to protect visitors’ privacy. Saved profiles are available when running the app on your own computer, not on this shared public version.")
    if st.sidebar.button("Clear my session data", use_container_width=True):
        run_count = st.session_state.get("agent_run_count", 0)
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.session_state["agent_run_count"] = run_count
        st.rerun()
else:
    mode = st.sidebar.radio("Choose how to continue", ["Anonymous", "Saved profile"], help="A saved profile remembers your entries on this device. Anonymous mode keeps them only for this browser session.")
profile_name = ""
active_key = None
profile_data = {}
if mode == "Saved profile":
    st.sidebar.caption("Saved locally on this device. No password or cloud account is used.")
    profile_name = st.sidebar.text_input("Profile name", placeholder="Choose a nickname")
    if profile_name.strip():
        active_key = profile_name.strip().casefold()
        if active_key in profiles:
            profile_data = profiles[active_key]
            st.sidebar.success("Profile found — your saved snapshot is loaded.")
        else:
            st.sidebar.info("New profile. Your snapshot will be saved after you submit it.")
else:
    st.sidebar.caption("Anonymous mode: nothing is written to a profile file.")

if active_key:
    st.session_state["finsight_profile_data"] = profile_data
else:
    profile_data = st.session_state.get("finsight_anonymous_data", {})

profile_scope = active_key or "anonymous"
if st.session_state.get("agent_results_version") != 3:
    st.session_state.pop("agent_results", None)
    st.session_state["agent_results_version"] = 3
stored_currency = profile_data.get("currency", "USD")
currency_code = st.sidebar.selectbox(
    "Currency", list(CURRENCIES), index=list(CURRENCIES).index(stored_currency) if stored_currency in CURRENCIES else 0,
    format_func=lambda code: f"{code} ({CURRENCIES[code].strip()})", key=f"currency_{profile_scope}",
)
currency_symbol = CURRENCIES[currency_code]
if profile_data.get("currency") != currency_code:
    profile_data["currency"] = currency_code
    if active_key:
        profiles[active_key] = profile_data
        save_profiles(profiles)
        st.session_state["finsight_profile_data"] = profile_data
    else:
        st.session_state["finsight_anonymous_data"] = profile_data
st.sidebar.caption("Changing currency relabels existing amounts; it does not convert them. Pick your currency before entering amounts.")
if st.session_state.get("agent_profile_scope") != profile_scope:
    st.session_state.pop("agent_results", None)
    st.session_state["agent_profile_scope"] = profile_scope
if "agent_run_count" not in st.session_state:
    st.session_state["agent_run_count"] = 0

overview_tab, activity_tab, agents_tab = st.tabs(["Overview", "Transactions & receipts", "Agent team"])

with overview_tab:
    st.markdown('<div class="hero"><div class="eyebrow">YOUR FINANCIAL SIGNAL, IN ONE PLACE</div><h1>Make your money make sense.</h1><p>Build a clear monthly snapshot, spot the biggest spending signals, and explore where steady saving could take you.</p></div>', unsafe_allow_html=True)
    st.subheader("01 / Build your monthly snapshot")
    st.caption("Add your take-home income, savings, and monthly expenses. Edit starter categories or add your own rows.")

    default_income = float(profile_data.get("income", 0.0))
    default_savings = float(profile_data.get("savings", 0.0))
    saved_expenses = profile_data.get("expenses")
    expense_df = pd.DataFrame(saved_expenses) if saved_expenses else DEFAULT_EXPENSES.copy()
    if "Monthly amount ($)" not in expense_df:
        expense_df = DEFAULT_EXPENSES.copy()
    saved_goals = profile_data.get("goals")
    goal_df = pd.DataFrame(saved_goals) if saved_goals else DEFAULT_GOALS.copy()
    if "Goal" not in goal_df:
        goal_df = DEFAULT_GOALS.copy()

    with st.form("monthly_snapshot", clear_on_submit=False):
        income_col, savings_col = st.columns(2)
        with income_col:
            income = st.number_input(f"Monthly take-home income ({currency_code})", min_value=0.0, value=default_income, step=100.0)
        with savings_col:
            savings = st.number_input(f"Current savings ({currency_code})", min_value=0.0, value=default_savings, step=100.0)
        edited_expenses = st.data_editor(
            expense_df, num_rows="dynamic", use_container_width=True, hide_index=True,
            column_config={
                "Category": st.column_config.TextColumn("Expense category", required=True),
                "Type": st.column_config.SelectboxColumn("Type", options=["Fixed", "Variable"], required=True),
                "Monthly amount ($)": st.column_config.NumberColumn(f"Monthly amount ({currency_code})", min_value=0, step=25, format="%.2f", required=True),
            }, key=f"expenses_{active_key or 'anonymous'}",
        )
        st.markdown("**Savings goals**")
        edited_goals = st.data_editor(
            goal_df, num_rows="dynamic", use_container_width=True, hide_index=True,
            column_config={
                "Goal": st.column_config.TextColumn("Goal", required=True),
                "Target ($)": st.column_config.NumberColumn(f"Target ({currency_code})", min_value=0, step=100, format="%.2f"),
                "Saved so far ($)": st.column_config.NumberColumn(f"Saved so far ({currency_code})", min_value=0, step=100, format="%.2f"),
                "Monthly contribution ($)": st.column_config.NumberColumn(f"Monthly contribution ({currency_code})", min_value=0, step=25, format="%.2f"),
            }, key=f"goals_{active_key or 'anonymous'}",
        )
        submit_label = "Save snapshot to profile" if active_key else "Update my snapshot"
        submitted = st.form_submit_button(submit_label, type="primary", use_container_width=True)

    if submitted:
        expenses_records = edited_expenses.fillna({"Category": "Other", "Type": "Variable", "Monthly amount ($)": 0}).to_dict(orient="records")
        goals_records = edited_goals.fillna({"Goal": "Savings goal", "Target ($)": 0, "Saved so far ($)": 0, "Monthly contribution ($)": 0}).to_dict(orient="records")
        profile_data.update({"income": income, "savings": savings, "expenses": expenses_records, "goals": goals_records})
        if active_key:
            profiles[active_key] = profile_data
            save_profiles(profiles)
            st.session_state["finsight_profile_data"] = profile_data
            st.sidebar.success("Snapshot saved on this device.")
        else:
            st.session_state["finsight_anonymous_data"] = profile_data
        st.session_state.pop("agent_results", None)
        st.rerun()

has_snapshot = "income" in profile_data
if not has_snapshot:
    st.info("Enter your numbers above, then select **Update my snapshot** to open your dashboard.")
    st.stop()

income = float(profile_data.get("income", 0.0))
savings = float(profile_data.get("savings", 0.0))
expense_df = pd.DataFrame(profile_data.get("expenses", []))
if expense_df.empty or "Monthly amount ($)" not in expense_df:
    expense_df = DEFAULT_EXPENSES.copy()
expense_df["Monthly amount ($)"] = pd.to_numeric(expense_df["Monthly amount ($)"], errors="coerce").fillna(0).clip(lower=0)
expense_df["Category"] = expense_df["Category"].fillna("Other").astype(str)
expense_df["Type"] = expense_df["Type"].fillna("Variable").astype(str)
total_expenses = float(expense_df["Monthly amount ($)"].sum())
fixed_total = float(expense_df.loc[expense_df["Type"] == "Fixed", "Monthly amount ($)"].sum())
variable_total = max(0.0, total_expenses - fixed_total)
monthly_surplus = income - total_expenses

with overview_tab:
    st.divider()
    st.markdown('<div class="eyebrow">LIVE OVERVIEW / MONTHLY</div>', unsafe_allow_html=True)
    st.subheader("02 / Your money at a glance")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Take-home income", money(income))
    k2.metric("Monthly expenses", money(total_expenses))
    k3.metric("Left after expenses", money(monthly_surplus), delta="surplus" if monthly_surplus >= 0 else "shortfall", delta_color="normal" if monthly_surplus >= 0 else "inverse")
    k4.metric("Current savings", money(savings))
    if monthly_surplus < 0:
        current_runway = max(0.0, savings) / abs(monthly_surplus)
        st.warning(f"Your monthly budget is short by {money(abs(monthly_surplus))}. At this same rate, your current savings could last about **{current_runway:.1f} months**. This estimate assumes the shortfall stays steady and excludes unexpected costs or income changes.")

    left, right = st.columns([1.05, 1])
    with left:
        st.markdown("#### Spending composition")
        nonzero = expense_df[expense_df["Monthly amount ($)"] > 0].groupby("Category", as_index=False)["Monthly amount ($)"].sum()
        if nonzero.empty:
            st.caption("Add amounts to your expense categories to see the chart.")
        else:
            chart_data = nonzero.rename(columns={"Category": "category", "Monthly amount ($)": "amount"})
            st.vega_lite_chart(chart_data, {
                "width": "container", "height": 280,
                "mark": {"type": "arc", "innerRadius": 70, "stroke": "#ffffff", "strokeWidth": 3},
                "encoding": {
                    "theta": {"field": "amount", "type": "quantitative"},
                    "color": {"field": "category", "type": "nominal", "scale": {"scheme": "tableau10"}, "legend": {"title": "Expense category", "labelColor": "#344256", "titleColor": "#172033"}},
                    "tooltip": [{"field": "category", "title": "Category"}, {"field": "amount", "title": f"Monthly spend ({currency_code})", "format": ",.2f"}],
                }, "view": {"stroke": None}, "background": "transparent",
            }, use_container_width=True)
    with right:
        st.markdown("#### Monthly budget sheet")
        display_df = expense_df[["Category", "Type", "Monthly amount ($)"]].copy().rename(columns={"Monthly amount ($)": f"Monthly budget ({currency_code})"})
        display_df["Share of expenses"] = display_df[f"Monthly budget ({currency_code})"].apply(lambda x: f"{x / total_expenses:.1%}" if total_expenses else "—")
        st.dataframe(display_df, hide_index=True, use_container_width=True, column_config={f"Monthly budget ({currency_code})": st.column_config.NumberColumn(format="%.2f")})
        st.download_button("Download budget sheet (CSV)", display_df.to_csv(index=False), file_name="finsight_monthly_budget.csv", mime="text/csv")
        st.caption(f"Fixed: {money(fixed_total)}  ·  Flexible: {money(variable_total)}")

    st.divider()
    st.markdown('<div class="eyebrow">FORWARD VIEW / SCENARIO</div>', unsafe_allow_html=True)
    st.subheader("03 / A possible savings trajectory")
    forecast_left, forecast_right = st.columns([1, 1.5])
    with forecast_left:
        contribution = st.number_input(f"Monthly amount to save or invest ({currency_code})", min_value=0.0, value=float(max(0.0, monthly_surplus)), step=50.0, key="forecast_contribution")
        horizon = st.slider("Projection horizon", min_value=6, max_value=60, value=24, step=6, format="%d months")
        annual_return = st.slider("Assumed annual investment return", min_value=0.0, max_value=15.0, value=0.0, step=0.5, format="%.1f%%", help="A hypothetical nominal rate for illustration, not a promised return. Set to 0% to model saving without investment growth.")
        st.session_state.setdefault("annual_inflation", 3.0)
        try:
            inflation_countries = fetch_world_bank_countries()
        except Exception as exc:
            inflation_countries = []
            st.warning(f"Could not load the country list from the World Bank API: {exc}. The manual inflation input remains available.")
        if inflation_countries:
            country_names = [item["name"] for item in inflation_countries]
            country_codes = {item["name"]: item for item in inflation_countries}
            saved_inflation_country = profile_data.get("inflation_country", "United States")
            if saved_inflation_country not in country_names:
                saved_inflation_country = "United States" if "United States" in country_names else country_names[0]
            inflation_country = st.selectbox(
                "Country used for the inflation estimate", country_names,
                index=country_names.index(saved_inflation_country),
                key=f"inflation_country_{profile_scope}",
            )
            if profile_data.get("inflation_country") != inflation_country:
                profile_data["inflation_country"] = inflation_country
                if active_key:
                    profiles[active_key] = profile_data
                    save_profiles(profiles)
                    st.session_state["finsight_profile_data"] = profile_data
                else:
                    st.session_state["finsight_anonymous_data"] = profile_data
            if st.button("Use latest available country inflation", key=f"fetch_country_inflation_{profile_scope}"):
                try:
                    inflation_data = fetch_latest_country_inflation(country_codes[inflation_country])
                    st.session_state["annual_inflation"] = round(float(inflation_data["rate"]), 1)
                    st.session_state["country_inflation_year"] = inflation_data["year"]
                    st.session_state["country_inflation_name"] = inflation_country
                    st.session_state["country_inflation_source"] = inflation_data["source"]
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not fetch inflation data for {inflation_country}: {exc}")
        annual_inflation = st.number_input(
            "Assumed annual inflation (%)", min_value=-50.0, max_value=10000.0,
            step=0.1, format="%.1f", key="annual_inflation",
            help="Load the latest available country rate from the free World Bank API, or enter your own estimate. Country data is annual and may lag current prices.",
        )
        if st.session_state.get("country_inflation_year"):
            st.caption(
                f"{st.session_state.get('country_inflation_source', 'Official annual CPI rate')} for "
                f"{st.session_state['country_inflation_name']}: "
                f"{st.session_state['country_inflation_year']}. The published value may lag current prices; "
                "you can edit the assumption above."
            )
        st.markdown("[World Bank inflation data source](https://data.worldbank.org/indicator/FP.CPI.TOTL.ZG)")
        area_choices = ["Skip comparison", *BLS_AREA_ANNUAL_MEAN.keys(), "Other location (enter local average)"]
        saved_area = profile_data.get("benchmark_area", "Skip comparison")
        area_choice = st.selectbox(
            "Living area for spending comparison", area_choices,
            index=area_choices.index(saved_area) if saved_area in area_choices else 0,
            key=f"benchmark_area_{profile_scope}",
        )
        area_monthly_average = None
        area_benchmark_source = ""
        if area_choice == "Other location (enter local average)":
            living_area = st.text_input(
                "City / region / country", value=profile_data.get("living_area", ""),
                placeholder="e.g. Vancouver, BC, Canada", key=f"living_area_{profile_scope}",
            )
            manual_area_average = st.number_input(
                f"Typical monthly household spending in your area ({currency_code})",
                min_value=0.0, value=float(profile_data.get("local_monthly_average", 0.0)), step=100.0,
                key=f"local_average_{profile_scope}",
                help="Enter a local average from a source you trust. The app does not have comparable official data for every country or city.",
            )
            if manual_area_average > 0:
                area_monthly_average = float(manual_area_average)
                area_benchmark_source = f"your entered estimate for {living_area or 'your area'}"
        elif area_choice in BLS_AREA_ANNUAL_MEAN:
            living_area = area_choice
            if currency_code == "USD":
                area_monthly_average = BLS_AREA_ANNUAL_MEAN[area_choice] / 12
                area_benchmark_source = "U.S. Bureau of Labor Statistics 2023–24 mean household expenditures"
            else:
                st.info("This published benchmark is in USD. Choose USD, or select Other location to enter a local average in your currency.")
        else:
            living_area = ""
            manual_area_average = 0.0
        area_values_changed = (
            profile_data.get("benchmark_area") != area_choice
            or profile_data.get("living_area", "") != living_area
            or float(profile_data.get("local_monthly_average", 0.0)) != float(manual_area_average if area_choice == "Other location (enter local average)" else 0.0)
        )
        if area_values_changed:
            profile_data.update({
                "benchmark_area": area_choice,
                "living_area": living_area,
                "local_monthly_average": float(manual_area_average if area_choice == "Other location (enter local average)" else 0.0),
            })
            if active_key:
                profiles[active_key] = profile_data
                save_profiles(profiles)
                st.session_state["finsight_profile_data"] = profile_data
            else:
                st.session_state["finsight_anonymous_data"] = profile_data
        if contribution > max(0.0, monthly_surplus):
            st.warning("This contribution is higher than your current monthly surplus. The projection assumes you can still make it.")
    with forecast_right:
        monthly_rate = (1 + annual_return / 100) ** (1 / 12) - 1
        monthly_inflation = (1 + annual_inflation / 100) ** (1 / 12) - 1
        nominal_balance = savings
        balances = []
        for month in range(horizon + 1):
            real_balance = nominal_balance / ((1 + monthly_inflation) ** month)
            balances.append({
                "Month": month,
                f"Projected balance ({currency_code})": round(nominal_balance, 2),
                f"Inflation-adjusted balance ({currency_code})": round(real_balance, 2),
            })
            nominal_balance = nominal_balance * (1 + monthly_rate) + contribution
        forecast_df = pd.DataFrame(balances)
        st.line_chart(
            forecast_df.set_index("Month"),
            y=[f"Projected balance ({currency_code})", f"Inflation-adjusted balance ({currency_code})"],
            color=["#53f1df", "#a78bfa"], use_container_width=True,
        )
        projected_cols = st.columns(2)
        projected_cols[0].metric(f"Future balance in {horizon} months", money(forecast_df.iloc[-1][f"Projected balance ({currency_code})"]))
        projected_cols[1].metric(f"In today’s purchasing power", money(forecast_df.iloc[-1][f"Inflation-adjusted balance ({currency_code})"]))
        st.caption("The second line discounts the projected balance by your chosen inflation assumption. Both figures are estimates; actual returns and inflation will vary.")
        if area_monthly_average is not None:
            today = date.today()
            benchmark_years_to_today = max(0.0, (today - date(2024, 6, 30)).days / 365.25)
            annual_inflation_factor = 1 + annual_inflation / 100
            local_average_today = area_monthly_average * (annual_inflation_factor ** benchmark_years_to_today)
            your_future_expenses = total_expenses * (annual_inflation_factor ** (horizon / 12))
            local_future_average = area_monthly_average * (annual_inflation_factor ** (benchmark_years_to_today + horizon / 12))
            st.markdown("#### Your projected expenses vs. the area average")
            comparison_cols = st.columns(2)
            comparison_cols[0].metric(f"Your monthly expenses in {horizon} months", money(your_future_expenses))
            comparison_cols[1].metric("Area average at that time", money(local_future_average), delta=f"{money(your_future_expenses - local_future_average)} vs. area average", delta_color="inverse")
            if area_choice in BLS_AREA_ANNUAL_MEAN:
                st.caption(f"Area benchmark: {area_benchmark_source}. The published 2023–24 average is adjusted to today and the projection horizon using your selected inflation assumption. It represents an average consumer unit, not a household-size-matched estimate; your budget categories may not include every BLS expenditure category.")
                st.markdown("[About the BLS geographic spending averages](https://www.bls.gov/regions/midwest/data/consumerexpenditures_selectedareas_table.htm)")
            else:
                st.caption("This comparison uses the local monthly average you entered as a starting estimate and applies your selected inflation assumption. It is not a verified area statistic.")

with activity_tab:
    if active_key:
        st.divider()
        st.markdown('<div class="eyebrow">HISTORY / PROFILE</div>', unsafe_allow_html=True)
        st.subheader("04 / Track monthly expenses")
        st.caption("Record a month to build a simple history and see how your spending changes over time.")
        logs = profile_data.get("expense_history", [])
        with st.form("monthly_log"):
            log_month = st.date_input("Month to record", value=date.today().replace(day=1), format="YYYY/MM/DD")
            log_total = st.number_input(f"Total expenses for that month ({currency_code})", min_value=0.0, value=float(total_expenses), step=50.0)
            log_submitted = st.form_submit_button("Add month to history", type="primary")
        if log_submitted:
            month_label = log_month.strftime("%Y-%m")
            logs = [item for item in logs if item.get("month") != month_label]
            logs.append({"month": month_label, "expenses": float(log_total)})
            logs.sort(key=lambda item: item["month"])
            profile_data["expense_history"] = logs
            profiles[active_key] = profile_data
            save_profiles(profiles)
            st.rerun()
        if logs:
            history_df = pd.DataFrame(logs).rename(columns={"month": "Month", "expenses": f"Expenses ({currency_code})"}).sort_values("Month")
            st.line_chart(history_df.set_index("Month"), y=f"Expenses ({currency_code})", color="#a78bfa")
            st.dataframe(history_df, hide_index=True, use_container_width=True, column_config={f"Expenses ({currency_code})": st.column_config.NumberColumn(format="%.2f")})
        else:
            st.info("No months recorded yet. Add a month above whenever you want to track actual expenses.")
    else:
        st.caption("Anonymous session data stays in this browser session. Choose Saved profile to remember your snapshot and track monthly history on this device.")

    st.divider()
    st.markdown('<div class="eyebrow">TRANSACTION INPUT / PATTERN SIGNAL</div>', unsafe_allow_html=True)
    st.subheader("05 / Add transaction activity")
    st.caption("Add a purchase and choose its category. Current-month spent and remaining amounts update automatically; monthly category amounts remain your budget limits. No bank connection is enabled.")
    transactions = profile_data.get("transactions", [])
    transaction_categories = sorted(set(expense_df["Category"].astype(str).tolist() + ["Other"]))
    with st.form("transaction_entry"):
        tx_cols = st.columns([1, 1, 1, 2])
        with tx_cols[0]:
            tx_date = st.date_input("Date", value=date.today())
        with tx_cols[1]:
            tx_category = st.selectbox("Category", transaction_categories)
        with tx_cols[2]:
            tx_amount = st.number_input(f"Amount ({currency_code})", min_value=0.0, value=0.0, step=10.0)
        with tx_cols[3]:
            tx_note = st.text_input("Note (optional)", placeholder="e.g. weekly groceries")
        tx_submitted = st.form_submit_button("Add transaction", type="primary")
    if tx_submitted:
        transactions.append({"Date": tx_date.strftime("%Y-%m-%d"), "Category": tx_category, "Amount ($)": float(tx_amount), "Note": tx_note.strip()})
        profile_data["transactions"] = transactions
        if active_key:
            profiles[active_key] = profile_data
            save_profiles(profiles)
        else:
            st.session_state["finsight_anonymous_data"] = profile_data
        st.session_state.pop("agent_results", None)
        st.rerun()

    current_month = date.today().strftime("%Y-%m")
    current_month_transaction_total = 0.0
    for tx in transactions:
        try:
            if datetime.strptime(str(tx.get("Date", "")), "%Y-%m-%d").strftime("%Y-%m") == current_month:
                current_month_transaction_total += max(0.0, float(tx.get("Amount ($)", 0) or 0))
        except (TypeError, ValueError):
            continue
    tracking_complete = st.checkbox(
        "This month is complete, and I’ve entered all its expenses",
        value=profile_data.get("expense_tracking_complete_month") == current_month,
        key=f"all_expenses_logged_{profile_scope}_{current_month}",
        help="Check this at the end of the month after entering all expenses. Savings suggestions can then use actual spending instead of assuming you used every budgeted dollar.",
    )
    previous_tracking_month = profile_data.get("expense_tracking_complete_month")
    if tracking_complete:
        profile_data["expense_tracking_complete_month"] = current_month
    else:
        profile_data.pop("expense_tracking_complete_month", None)
    if previous_tracking_month != profile_data.get("expense_tracking_complete_month"):
        if active_key:
            profiles[active_key] = profile_data
            save_profiles(profiles)
            st.session_state["finsight_profile_data"] = profile_data
        else:
            st.session_state["finsight_anonymous_data"] = profile_data
    if profile_data.get("expense_tracking_complete_month") == current_month and tracking_complete:
        goal_available_surplus = income - current_month_transaction_total
        goal_surplus_basis = "actual spending entered for this month"
        unspent_budget_amount = total_expenses - current_month_transaction_total
        st.caption(f"Actual spending entered: {money(current_month_transaction_total)} · Unspent from planned expense budget: {money(unspent_budget_amount)} · Potentially available after spending: {money(max(0.0, goal_available_surplus))}.")
    else:
        goal_available_surplus = monthly_surplus
        goal_surplus_basis = "your monthly budget snapshot"
        if monthly_surplus > 0:
            st.caption(f"Savings suggestions will use your planned monthly surplus of {money(monthly_surplus)}. Confirm the checkbox above after entering this month’s expenses to include any underspent budget.")
    if transactions:
        st.dataframe(pd.DataFrame(transactions).rename(columns={"Amount ($)": f"Amount ({currency_code})"}).sort_values("Date", ascending=False), hide_index=True, use_container_width=True)
        transaction_df = pd.DataFrame(transactions)
        transaction_df["Amount ($)"] = pd.to_numeric(transaction_df["Amount ($)"], errors="coerce").fillna(0)
        transaction_df["Date"] = pd.to_datetime(transaction_df["Date"], errors="coerce")
        transaction_df = transaction_df.dropna(subset=["Date"])
        transaction_df["Month"] = transaction_df["Date"].dt.strftime("%Y-%m")
        current_month = date.today().strftime("%Y-%m")
        actual_month = transaction_df[transaction_df["Month"] == current_month]
        monthly_limits = expense_df.groupby("Category")["Monthly amount ($)"].sum()
        category_spend = actual_month.groupby("Category")["Amount ($)"].sum()
        all_categories = sorted(set(monthly_limits.index.astype(str)) | set(category_spend.index.astype(str)))
        monthly_limits = monthly_limits.reindex(all_categories, fill_value=0)
        progress_df = pd.DataFrame([
            {
                "Category": category,
                "Monthly budget ($)": float(limit),
                "Spent this month ($)": float(category_spend.get(category, 0.0)),
                "Remaining ($)": float(limit) - float(category_spend.get(category, 0.0)),
            }
            for category, limit in monthly_limits.items()
        ])
        st.markdown("#### Current-month budget progress")
        st.caption("Transactions are counted under their selected category as soon as they’re saved. A negative remaining amount means that category is over its monthly budget.")
        progress_df = progress_df.rename(columns={
            "Monthly budget ($)": f"Monthly budget ({currency_code})",
            "Spent this month ($)": f"Spent this month ({currency_code})",
            "Remaining ($)": f"Remaining ({currency_code})",
        })
        st.dataframe(progress_df, hide_index=True, use_container_width=True, column_config={
            f"Monthly budget ({currency_code})": st.column_config.NumberColumn(format="%.2f"),
            f"Spent this month ({currency_code})": st.column_config.NumberColumn(format="%.2f"),
            f"Remaining ({currency_code})": st.column_config.NumberColumn(format="%.2f"),
        })
        actual_cols = st.columns([1, 2])
        actual_cols[0].metric("Actual spend logged this month", money(actual_month["Amount ($)"].sum()))
        if not actual_month.empty:
            by_category = actual_month.groupby("Category")["Amount ($)"].sum().sort_values(ascending=False)
            with actual_cols[1]:
                st.markdown(f"**This month by category ({currency_code})**")
                st.bar_chart(by_category, color="#53f1df", horizontal=True)
        monthly_actuals = transaction_df.groupby("Month", as_index=False)["Amount ($)"].sum().sort_values("Month")
        if len(monthly_actuals) > 1:
            st.markdown("**Transaction spend by month**")
            monthly_actuals = monthly_actuals.rename(columns={"Amount ($)": f"Amount ({currency_code})"})
            st.line_chart(monthly_actuals.set_index("Month"), y=f"Amount ({currency_code})", color="#a78bfa")
    else:
        st.info("Add a few transactions to see recent spending patterns here.")

    st.divider()
    st.markdown('<div class="eyebrow">RECEIPT SCAN / LOCAL OCR</div>', unsafe_allow_html=True)
    st.subheader("06 / Scan a receipt")
    use_receipt = st.checkbox("I want to add an expense using a receipt photo", key="use_receipt_photo")
    if not use_receipt:
        st.session_state.pop("receipt_draft", None)
        st.caption("Receipt scanning is optional. Turn this on only when you want to upload or take a receipt photo.")
    else:
        st.caption(f"Upload a JPG or PNG photo, or take one with your camera. Check the extracted total before saving; it is treated as {currency_code}, and receipt currency is not converted. The image is read locally and removed after reading.")
        receipt_upload_col, receipt_camera_col = st.columns(2)
        with receipt_upload_col:
            receipt_upload = st.file_uploader("Upload receipt image", type=["jpg", "jpeg", "png"], key="receipt_upload")
        with receipt_camera_col:
            receipt_camera = st.camera_input("Take a receipt photo", key="receipt_camera")
        receipt_image = receipt_camera or receipt_upload
        if receipt_image:
            st.image(receipt_image, caption="Receipt preview", width=360)
            if st.button("Read receipt", type="primary", key="read_receipt"):
                suffix = Path(receipt_image.name or "receipt.jpg").suffix.lower() or ".jpg"
                try:
                    extracted_text = read_receipt_image(receipt_image.getvalue(), suffix)
                    st.session_state["receipt_draft"] = parse_receipt(extracted_text, currency_code)
                    if not extracted_text:
                        st.warning("I couldn't read text from that photo. Try a clearer, well-lit picture with the full receipt in frame.")
                except ImportError:
                    st.error("Receipt OCR is not installed in the Python environment running Streamlit. Stop the app, install the packages in requirements.txt, then restart it.")
                except Exception as exc:
                    st.error(f"Could not read this receipt: {exc}")

        receipt_draft = st.session_state.get("receipt_draft")
        if receipt_draft:
            with st.expander("Review extracted receipt details", expanded=True):
                if receipt_draft.get("amount") is None:
                    st.warning("I couldn't confidently find the receipt total. Enter the total below before adding it.")
                if not receipt_draft.get("date_was_read"):
                    st.caption("No clear date was detected, so today's date was filled in. You can change it below.")
                if receipt_draft.get("text"):
                    with st.expander("Show OCR text"):
                        st.text(receipt_draft["text"])
                with st.form("apply_receipt"):
                    receipt_cols = st.columns(3)
                    with receipt_cols[0]:
                        detected_amount = receipt_draft.get("amount")
                        amount_source = st.radio(
                            "Receipt amount",
                            ["Check / correct detected amount", "Enter amount manually"],
                            horizontal=False,
                            help="Receipt scanning can misread totals. Always check this value before adding it.",
                        )
                        amount_default = float(detected_amount or 0) if amount_source.startswith("Check") else 0.0
                        receipt_amount = st.number_input(
                            f"Confirm the amount to record ({currency_code})", min_value=0.0,
                            value=amount_default, step=0.01, format="%.2f",
                            help="Edit this number if the scanned total is wrong. The amount you confirm is what gets recorded.",
                        )
                    with receipt_cols[1]:
                        receipt_date = st.date_input("Receipt date", value=receipt_draft["date"])
                    with receipt_cols[2]:
                        receipt_category = st.selectbox("Category", sorted(set(transaction_categories + [receipt_draft["category"]])), index=sorted(set(transaction_categories + [receipt_draft["category"]])).index(receipt_draft["category"]))
                    receipt_merchant = st.text_input("Merchant", value=receipt_draft["merchant"])
                    apply_receipt = st.form_submit_button("Add receipt to expenses", type="primary", use_container_width=True)
                if apply_receipt:
                    transactions.append({"Date": receipt_date.strftime("%Y-%m-%d"), "Category": receipt_category, "Amount ($)": float(receipt_amount), "Note": f"Receipt · {receipt_merchant.strip()}"})
                    profile_data["transactions"] = transactions
                    if active_key:
                        profiles[active_key] = profile_data
                        save_profiles(profiles)
                    else:
                        st.session_state["finsight_anonymous_data"] = profile_data
                    st.session_state.pop("receipt_draft", None)
                    st.session_state.pop("agent_results", None)
                    st.rerun()

with agents_tab:
    st.divider()
    st.markdown('<div class="eyebrow">DECISION SUPPORT</div>', unsafe_allow_html=True)
    st.subheader("07 / Explore a financial decision")
    st.caption("Review how a purchase or new monthly cost could affect your budget, savings goals, and spending plan.")
    with st.form("agent_analysis"):
        decision_description = st.text_input("What decision are you considering?", placeholder="e.g. Buy a laptop, take a trip, or add a monthly subscription")
        decision_cols = st.columns(2)
        with decision_cols[0]:
            decision_amount = st.number_input(f"Decision amount ({currency_code})", min_value=0.0, value=0.0, step=50.0)
        with decision_cols[1]:
            decision_kind = st.radio("Cost type", ["One-time", "Monthly recurring"], horizontal=True)
        run_limit_reached = PUBLIC_DEMO and st.session_state["agent_run_count"] >= MAX_AGENT_RUNS_PER_SESSION
        run_agents = st.form_submit_button(
            "Analyze this decision", type="primary", use_container_width=True, disabled=run_limit_reached
        )
    if PUBLIC_DEMO:
        st.caption(f"Public demo limit: {st.session_state['agent_run_count']} of {MAX_AGENT_RUNS_PER_SESSION} agent runs used in this session.")
        if run_limit_reached:
            st.warning("This demo session has reached its run limit. Refresh the app to start a new session.")
    if run_agents:
        if PUBLIC_DEMO:
            st.session_state["agent_run_count"] += 1
        decision = {"description": decision_description.strip(), "amount": float(decision_amount), "kind": decision_kind}
        st.session_state["agent_results"] = orchestrator.analyze(
            profile_data, decision, transactions, currency_symbol, goal_available_surplus
        )
        st.session_state["agent_decision"] = decision

    agent_output = st.session_state.get("agent_results")
    if agent_output:
        findings = agent_output["findings"]
        decision_data = st.session_state.get("agent_decision", {})
        st.markdown("#### Your decision summary")
        budget_result = findings["budget"]
        review = findings["judge"]
        if review["status"] != "Reviewed":
            st.warning("Some budget totals need review. Check your income and expense entries before relying on the result.")
        elif review["affordability"] == "Not affordable":
            st.error(review["assessment"])
        elif review["affordability"] == "Tight":
            st.warning(review["assessment"])
        elif review["affordability"] == "Affordable":
            st.success(review["assessment"])
        st.info(findings["coach"]["summary"])

        if review["affordability"] == "Not affordable":
            amount = float(decision_data.get("amount", 0) or 0)
            recurring = decision_data.get("kind") == "Monthly recurring"
            current_surplus = float(budget_result["current_surplus"])
            if amount > 0 and not recurring:
                st.markdown("##### Options to make this purchase more manageable")
                installment_rows = []
                for months in (3, 6, 12):
                    payment = amount / months
                    remaining_after_payment = current_surplus - payment
                    if current_surplus < 0:
                        fit = "Does not fit: budget already has a shortfall"
                    elif remaining_after_payment < -0.005:
                        fit = "Exceeds current monthly surplus"
                    elif remaining_after_payment <= 0.005:
                        fit = "Fits exactly; leaves no monthly margin"
                    else:
                        fit = "Fits listed surplus"
                    installment_rows.append({
                        "Term": f"{months} months",
                        f"Estimated payment ({currency_code}/month)": money(payment),
                        f"Left after payment ({currency_code}/month)": money(remaining_after_payment),
                        "Budget check": fit,
                    })
                st.dataframe(pd.DataFrame(installment_rows), hide_index=True, use_container_width=True)
                st.caption("Illustration assumes equal payments at 0% interest with no fees. Actual financing may cost more; check the lender’s total repayment amount and terms.")
                if current_surplus > 0:
                    months_to_save = math.ceil(amount / current_surplus)
                    st.write(
                        f"If you keep your current savings untouched and direct your full monthly surplus of "
                        f"{money(current_surplus)} to a separate purchase goal, it would take about "
                        f"{months_to_save} month{'s' if months_to_save != 1 else ''} to save the full price."
                    )
                else:
                    st.write("Your current budget has no positive monthly surplus to fund this goal yet. Consider lowering expenses or increasing income first.")

                saved_goals = profile_data.setdefault("goals", [])
                goal_name = (str(decision_data.get("description", "")).strip() or "Purchase fund")
                existing_names = {str(goal.get("Goal", "")).strip().casefold() for goal in saved_goals}
                goal_name_in_use = goal_name.casefold() in existing_names
                if goal_name_in_use:
                    st.caption("A savings goal with this name already exists. You can update its target in the savings goals section.")
                if st.button(
                    f"Add {goal_name} as a savings goal",
                    type="secondary", key="add_decision_as_goal", disabled=goal_name_in_use,
                    help="Adds a separate goal for the full purchase price and leaves current savings untouched.",
                ):
                    saved_goals.append({
                        "Goal": goal_name,
                        "Target ($)": amount,
                        "Saved so far ($)": 0.0,
                        "Monthly contribution ($)": 0.0,
                    })
                    if active_key:
                        profiles[active_key] = profile_data
                        save_profiles(profiles)
                        st.session_state["finsight_profile_data"] = profile_data
                    else:
                        st.session_state["finsight_anonymous_data"] = profile_data
                    st.session_state.pop("agent_results", None)
                    st.rerun()
            elif recurring:
                st.caption(
                    f"To avoid a monthly shortfall, keep a recurring payment at or below "
                    f"{money(max(0.0, current_surplus))}; keeping it lower leaves some margin."
                )

        budget_cols = st.columns(5)
        budget_cols[0].metric("Monthly surplus", money(budget_result["current_surplus"]))
        budget_cols[1].metric("Monthly expenses", money(budget_result["monthly_expenses"]))
        budget_cols[2].metric("After new monthly cost", money(budget_result["projected_monthly_surplus"]))
        budget_cols[3].metric("Savings after purchase", money(budget_result["projected_savings_after_decision"]))
        runway = budget_result["projected_runway_months"]
        runway_label = f"{runway:.1f} months" if runway is not None else "No shortfall"
        budget_cols[4].metric("Savings runway", runway_label)

        goal_summary = findings["goals"]
        goal_results = goal_summary["goals"]
        with st.expander("Savings goal suggestions", expanded=True):
            st.info(
                f"Using {goal_surplus_basis}, {money(goal_summary['available_surplus'])} is available after this decision. "
                f"Suggested for your active goals: {money(goal_summary['allocated_to_goals'])} per month; "
                f"suggested for general savings: {money(goal_summary['to_general_savings'])} per month."
            )
            st.caption("Your existing monthly contribution entries are treated as preferences. Any extra is split across unfinished goals based on their remaining target amounts; amounts beyond completed goals are directed to general savings.")
            if goal_results:
                goal_view = pd.DataFrame(goal_results).rename(columns={
                    "goal": "Goal", "target": f"Target ({currency_code})",
                    "saved": f"Saved so far ({currency_code})", "remaining": f"Current gap ({currency_code})",
                    "requested_monthly_contribution": f"Your contribution preference ({currency_code})",
                    "suggested_monthly_contribution": f"Suggested monthly contribution ({currency_code})",
                    "estimated_months": "Estimated months at suggestion",
                })
                st.dataframe(goal_view.drop(columns=["goal_index"]), hide_index=True, use_container_width=True)
                st.caption("Applying a suggestion updates your local goal plan only; it does not move money.")
                if st.button("Apply suggested contributions to my goal plan", type="primary", key="apply_goal_suggestions"):
                    saved_goals = profile_data.get("goals", [])
                    for suggested_goal in goal_results:
                        goal_index = suggested_goal["goal_index"]
                        if 0 <= goal_index < len(saved_goals):
                            saved_goals[goal_index]["Monthly contribution ($)"] = suggested_goal["suggested_monthly_contribution"]
                    profile_data["goals"] = saved_goals
                    if active_key:
                        profiles[active_key] = profile_data
                        save_profiles(profiles)
                        st.session_state["finsight_profile_data"] = profile_data
                    else:
                        st.session_state["finsight_anonymous_data"] = profile_data
                    st.session_state.pop("agent_results", None)
                    st.rerun()
            else:
                st.write("No unfinished goal with a target amount is entered. The available amount is suggested for general savings.")

        with st.expander("Your spending patterns", expanded=True):
            spending_result = findings["spending"]
            st.write(spending_result["message"])
            if spending_result["categories"]:
                st.dataframe(pd.DataFrame(spending_result["categories"]).rename(columns={"category": "Category", "amount": f"90-day total ({currency_code})"}), hide_index=True, use_container_width=True)

        if "what_if" in findings:
            with st.expander("Compare alternatives", expanded=True):
                st.write(findings["what_if"]["metric"])
                scenario_view = pd.DataFrame(findings["what_if"]["scenarios"])
                scenario_view["amount"] = scenario_view["amount"].map(money)
                st.dataframe(scenario_view.rename(columns={"scenario": "Alternative", "amount": f"{findings['what_if']['metric']} ({currency_code})"}), hide_index=True, use_container_width=True)
                st.caption(findings["what_if"]["recommendation"])

st.markdown("---")
if PUBLIC_DEMO:
    st.caption("FinSight is a public planning demo. It uses anonymous session data, does not connect to banks or move money, and does not save entries to a profile file. Avoid entering sensitive personal information.")
else:
    st.caption("FinSight is a planning prototype. Saved profile data is stored locally in this app folder; it is not encrypted and is not uploaded to a cloud service.")
