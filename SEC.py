import streamlit as st
import requests
import json
import pandas as pd
import altair as alt
from datetime import datetime

###############################################################################
# Synonyms to handle popular company names like 'google' => 'alphabet inc'
###############################################################################
SYNONYMS = {
    "google": "alphabet inc",
    "nvidia": "nvidia corporation",
    # Add more if needed
}

###############################################################################
# 1) Company Name -> Ticker
###############################################################################
def get_ticker_from_company_name(company_name: str, user_agent: str):
    """
    Searches 'company_tickers.json' from the SEC, matching the 'title' field
    to the given company_name (case-insensitive substring match).
    Returns a list of tickers (could be multiple if partial match).
    Also checks the SYNONYMS dict to handle names like 'google' -> 'alphabet inc'.
    """
    # Handle synonyms
    name_lower = company_name.lower().strip()
    if name_lower in SYNONYMS:
        company_name = SYNONYMS[name_lower]
    
    headers = {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }
    url = "https://www.sec.gov/files/company_tickers.json"
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return []
    
    data = resp.json()
    name_upper = company_name.upper().strip()
    matched_tickers = []
    for _, info in data.items():
        title_upper = info["title"].upper()
        if name_upper in title_upper:
            matched_tickers.append(info["ticker"])
    return matched_tickers

###############################################################################
# 2) Ticker -> CIK
###############################################################################
def get_cik_from_ticker(ticker: str, user_agent: str) -> str:
    """
    Looks up the 10-digit CIK for the given ticker from 'company_tickers.json'.
    Returns 'CIKXXXXXXXXXX' or an empty string if not found.
    """
    headers = {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov",
    }
    url = "https://www.sec.gov/files/company_tickers.json"
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return ""
    
    data = resp.json()
    t_upper = ticker.upper().strip()
    for _, info in data.items():
        if info["ticker"].upper() == t_upper:
            cik_str_10 = str(info["cik_str"]).zfill(10)
            return f"CIK{cik_str_10}"
    return ""

###############################################################################
# 3) Fetch financial data from SEC
###############################################################################
def get_financial_data(
    cik_10digit: str,
    concept: str,
    user_agent: str,
    fetch_count: int = 30,
    final_count: int = 10
):
    """
    Uses the SEC XBRL Company Concept API to fetch data for a given 'concept',
    e.g. "NetIncomeLoss" or "RevenueFromContractWithCustomerExcludingAssessedTax".
    Filters for 10-K, fp=FY, and ~>=300 days (full year).
    Returns up to 'final_count' unique records (by start/end date).
    """
    url = f"https://data.sec.gov/api/xbrl/companyconcept/{cik_10digit}/us-gaap/{concept}.json"
    headers = {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov",
    }
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        return None, f"Request failed (status {resp.status_code}) for {concept}"
    
    data = resp.json()
    try:
        units = data["units"]["USD"]
    except KeyError:
        return None, f"USD unit not found for {concept}"
    
    if not units:
        return None, f"No {concept} (USD) data found"
    
    def is_full_year(item):
        try:
            start_date = datetime.strptime(item["start"], "%Y-%m-%d")
            end_date = datetime.strptime(item["end"], "%Y-%m-%d")
            return (end_date - start_date).days >= 300
        except:
            return False

    ten_k_units = [
        u for u in units
        if u.get("form") == "10-K"
        and u.get("fp") == "FY"
        and is_full_year(u)
    ]
    if not ten_k_units:
        return None, f"No 10-K full-year data found for {concept}"
    
    sorted_units = sorted(ten_k_units, key=lambda x: x.get("end", ""), reverse=True)[:fetch_count]
    
    unique_records = []
    seen = set()
    for item in sorted_units:
        start_end = (item.get("start"), item.get("end"))
        if start_end not in seen:
            unique_records.append(item)
            seen.add(start_end)
        if len(unique_records) == final_count:
            break
    
    return unique_records, None

###############################################################################
# 4) Streamlit App
###############################################################################

# Initialize session state for two-step search
if "matched_tickers" not in st.session_state:
    st.session_state.matched_tickers = None
if "selected_ticker" not in st.session_state:
    st.session_state.selected_ticker = None

# Main Title: "Shyft" in the center
st.markdown("<h1 style='text-align: center;'>Shyft</h1>", unsafe_allow_html=True)
st.markdown("<h3 style='text-align: center;'>Financial Data Lookup (data.sec.gov API)</h3>", unsafe_allow_html=True)

# User-Agent
user_agent = st.text_input("User-Agent (required by SEC)", value="MyStreamlitApp (contact@example.com)")

# Default: Company Name
mode = st.selectbox("Select lookup method", ["Company Name", "Ticker", "CIK"], index=0)

# Input fields
if mode == "Company Name":
    input_company = st.text_input("Enter Company Name", value="Apple")
elif mode == "Ticker":
    input_ticker = st.text_input("Enter Ticker", value="AAPL")
else:
    input_cik = st.text_input("Enter 10-digit CIK (leading zeros if needed)", value="0000320193")

###############################################################################
# Company Name: Two-step search
###############################################################################
if mode == "Company Name":
    st.subheader("Step 1: Search by Company Name")
    if st.button("Search (Company)"):
        if not user_agent:
            st.error("Please enter a valid User-Agent.")
            st.stop()
        if not input_company.strip():
            st.warning("Please enter a company name.")
            st.stop()
        
        with st.spinner("Searching for matching tickers..."):
            matched = get_ticker_from_company_name(input_company, user_agent)
        
        if not matched:
            st.error(f"No matches found for '{input_company}'.")
            st.stop()
        
        st.session_state.matched_tickers = matched
        st.info("Ticker list created. Select a ticker below, then click 'Search (Ticker)' to fetch data.")

    # Show the Ticker selectbox only if we have matched tickers
    if st.session_state.matched_tickers:
        st.subheader("Step 2: Select Ticker and Search Data")
        st.session_state.selected_ticker = st.selectbox(
            "Matched Tickers",
            st.session_state.matched_tickers
        )
        if st.button("Search (Ticker)"):
            if not st.session_state.selected_ticker:
                st.error("No ticker selected.")
                st.stop()
            
            # Convert ticker -> CIK
            cik_10 = get_cik_from_ticker(st.session_state.selected_ticker, user_agent)
            if not cik_10:
                st.error(f"Failed to find CIK for ticker '{st.session_state.selected_ticker}'.")
                st.stop()
            
            st.write(f"**Selected Ticker**: {st.session_state.selected_ticker}, **CIK**: {cik_10}")
            
            # Fetch data
            with st.spinner("Fetching financial data..."):
                rev_data, rev_err = get_financial_data(cik_10, "RevenueFromContractWithCustomerExcludingAssessedTax", user_agent)
                ni_data, ni_err = get_financial_data(cik_10, "NetIncomeLoss", user_agent)
            
            if rev_err:
                st.error(f"Revenue error: {rev_err}")
            if ni_err:
                st.error(f"Net Income error: {ni_err}")
            if rev_err or ni_err:
                st.stop()
            
            # Prepare data
            rev_list = []
            for item in rev_data:
                end_year = datetime.strptime(item["end"], "%Y-%m-%d").year
                rev_list.append({"Year": end_year, "Revenue": item["val"]})
            df_rev = pd.DataFrame(rev_list).groupby("Year", as_index=False).sum()
            
            ni_list = []
            for item in ni_data:
                end_year = datetime.strptime(item["end"], "%Y-%m-%d").year
                ni_list.append({"Year": end_year, "NetIncome": item["val"]})
            df_ni = pd.DataFrame(ni_list).groupby("Year", as_index=False).sum()
            
            df_combined = pd.merge(df_rev, df_ni, on="Year", how="inner").sort_values("Year")
            
            max_val = max(df_combined["Revenue"].max(), df_combined["NetIncome"].max())
            if max_val >= 1e12:
                factor = 1e12
                unit_label = "(in Trillions USD)"
            else:
                factor = 1e9
                unit_label = "(in Billions USD)"
            
            df_combined["Revenue"]   = df_combined["Revenue"]   / factor
            df_combined["NetIncome"] = df_combined["NetIncome"] / factor
            
            rv_col = f"Revenue {unit_label}"
            ni_col = f"NetIncome {unit_label}"
            df_combined.rename(
                columns={
                    "Revenue":   rv_col,
                    "NetIncome": ni_col
                },
                inplace=True
            )
            
            st.subheader("Revenue & Net Income")
            st.table(df_combined)
            
            # Chart with numeric offset to ensure Revenue=left, NetIncome=right
            df_melt = df_combined.melt(
                id_vars="Year",
                value_vars=[rv_col, ni_col],
                var_name="Measure",
                value_name="Amount"
            )
            measure_order_map = {rv_col: 0, ni_col: 1}
            df_melt["MeasureSort"] = df_melt["Measure"].map(measure_order_map)
            
            chart = (
                alt.Chart(df_melt)
                .mark_bar()
                .encode(
                    x=alt.X("Year:O", title="Year"),
                    y=alt.Y("Amount:Q", title=unit_label),
                    color=alt.Color("Measure:N"),
                    xOffset="MeasureSort:N",  # 0 => Revenue (left), 1 => NetIncome (right)
                    tooltip=["Year:O", "Measure:N", "Amount:Q"]
                )
                .properties(width=600, height=400)
            )
            st.altair_chart(chart, use_container_width=True)
            
            # Reset session states
            st.session_state.matched_tickers = None
            st.session_state.selected_ticker = None

###############################################################################
# Ticker mode (single-step)
###############################################################################
elif mode == "Ticker":
    if st.button("Search"):
        if not user_agent:
            st.error("Please enter a valid User-Agent.")
            st.stop()
        if not input_ticker.strip():
            st.warning("Please enter a ticker.")
            st.stop()
        
        with st.spinner("Converting Ticker -> CIK..."):
            cik_10 = get_cik_from_ticker(input_ticker, user_agent)
            if not cik_10:
                st.error(f"No CIK found for ticker '{input_ticker}'.")
                st.stop()
        st.write(f"**Found CIK**: {cik_10}")
        
        with st.spinner("Fetching financial data..."):
            rev_data, rev_err = get_financial_data(cik_10, "RevenueFromContractWithCustomerExcludingAssessedTax", user_agent)
            ni_data, ni_err = get_financial_data(cik_10, "NetIncomeLoss", user_agent)
        
        if rev_err:
            st.error(f"Revenue error: {rev_err}")
        if ni_err:
            st.error(f"Net Income error: {ni_err}")
        if rev_err or ni_err:
            st.stop()
        
        rev_list = []
        for item in rev_data:
            end_year = datetime.strptime(item["end"], "%Y-%m-%d").year
            rev_list.append({"Year": end_year, "Revenue": item["val"]})
        df_rev = pd.DataFrame(rev_list).groupby("Year", as_index=False).sum()
        
        ni_list = []
        for item in ni_data:
            end_year = datetime.strptime(item["end"], "%Y-%m-%d").year
            ni_list.append({"Year": end_year, "NetIncome": item["val"]})
        df_ni = pd.DataFrame(ni_list).groupby("Year", as_index=False).sum()
        
        df_combined = pd.merge(df_rev, df_ni, on="Year", how="inner").sort_values("Year")
        
        max_val = max(df_combined["Revenue"].max(), df_combined["NetIncome"].max())
        if max_val >= 1e12:
            factor = 1e12
            unit_label = "(in Trillions USD)"
        else:
            factor = 1e9
            unit_label = "(in Billions USD)"
        
        df_combined["Revenue"]   = df_combined["Revenue"]   / factor
        df_combined["NetIncome"] = df_combined["NetIncome"] / factor
        
        rv_col = f"Revenue {unit_label}"
        ni_col = f"NetIncome {unit_label}"
        df_combined.rename(
            columns={
                "Revenue":   rv_col,
                "NetIncome": ni_col
            },
            inplace=True
        )
        
        st.subheader("Revenue & Net Income")
        st.table(df_combined)
        
        df_melt = df_combined.melt(
            id_vars="Year",
            value_vars=[rv_col, ni_col],
            var_name="Measure",
            value_name="Amount"
        )
        measure_order_map = {rv_col: 0, ni_col: 1}
        df_melt["MeasureSort"] = df_melt["Measure"].map(measure_order_map)
        
        chart = (
            alt.Chart(df_melt)
            .mark_bar()
            .encode(
                x=alt.X("Year:O", title="Year"),
                y=alt.Y("Amount:Q", title=unit_label),
                color=alt.Color("Measure:N"),
                xOffset="MeasureSort:N",
                tooltip=["Year:O", "Measure:N", "Amount:Q"]
            )
            .properties(width=600, height=400)
        )
        st.altair_chart(chart, use_container_width=True)

###############################################################################
# CIK mode (single-step)
###############################################################################
else:  # mode == "CIK"
    if st.button("Search"):
        if not user_agent:
            st.error("Please enter a valid User-Agent.")
            st.stop()
        c = input_cik.strip()
        if not c:
            st.warning("Please enter a CIK.")
            st.stop()
        if not c.startswith("CIK"):
            c = "CIK" + c.zfill(10)
        cik_10 = c
        st.write(f"**Entered CIK**: {cik_10}")
        
        with st.spinner("Fetching financial data..."):
            rev_data, rev_err = get_financial_data(cik_10, "RevenueFromContractWithCustomerExcludingAssessedTax", user_agent)
            ni_data, ni_err = get_financial_data(cik_10, "NetIncomeLoss", user_agent)
        
        if rev_err:
            st.error(f"Revenue error: {rev_err}")
        if ni_err:
            st.error(f"Net Income error: {ni_err}")
        if rev_err or ni_err:
            st.stop()
        
        rev_list = []
        for item in rev_data:
            end_year = datetime.strptime(item["end"], "%Y-%m-%d").year
            rev_list.append({"Year": end_year, "Revenue": item["val"]})
        df_rev = pd.DataFrame(rev_list).groupby("Year", as_index=False).sum()
        
        ni_list = []
        for item in ni_data:
            end_year = datetime.strptime(item["end"], "%Y-%m-%d").year
            ni_list.append({"Year": end_year, "NetIncome": item["val"]})
        df_ni = pd.DataFrame(ni_list).groupby("Year", as_index=False).sum()
        
        df_combined = pd.merge(df_rev, df_ni, on="Year", how="inner").sort_values("Year")
        
        max_val = max(df_combined["Revenue"].max(), df_combined["NetIncome"].max())
        if max_val >= 1e12:
            factor = 1e12
            unit_label = "(in Trillions USD)"
        else:
            factor = 1e9
            unit_label = "(in Billions USD)"
        
        df_combined["Revenue"]   = df_combined["Revenue"]   / factor
        df_combined["NetIncome"] = df_combined["NetIncome"] / factor
        
        rv_col = f"Revenue {unit_label}"
        ni_col = f"NetIncome {unit_label}"
        df_combined.rename(
            columns={
                "Revenue":   rv_col,
                "NetIncome": ni_col
            },
            inplace=True
        )
        
        st.subheader("Revenue & Net Income")
        st.table(df_combined)
        
        df_melt = df_combined.melt(
            id_vars="Year",
            value_vars=[rv_col, ni_col],
            var_name="Measure",
            value_name="Amount"
        )
        measure_order_map = {rv_col: 0, ni_col: 1}
        df_melt["MeasureSort"] = df_melt["Measure"].map(measure_order_map)
        
        chart = (
            alt.Chart(df_melt)
            .mark_bar()
            .encode(
                x=alt.X("Year:O", title="Year"),
                y=alt.Y("Amount:Q", title=unit_label),
                color=alt.Color("Measure:N"),
                xOffset="MeasureSort:N",
                tooltip=["Year:O", "Measure:N", "Amount:Q"]
            )
            .properties(width=600, height=400)
        )
        st.altair_chart(chart, use_container_width=True)