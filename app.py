# app.py
# -----------------------------------------------------------------------------
# This is the DASHBOARD (the screen you see in the browser), built with Streamlit.
# Run it with:    streamlit run app.py
#
# NOTE FOR NON-CODERS:
# - This file only handles the SCREEN (cards, tables, tabs, charts).
# - The scanning maths lives in scanner.py and indicators.py.
# - To change how strict the scan is, use the sidebar (left) or edit the
#   THRESHOLDS block at the top of scanner.py.
# -----------------------------------------------------------------------------

import os

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import scanner
import indicators as ind


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
DEFAULT_UNIVERSE = os.path.join(BASE_DIR, "universe.csv")
os.makedirs(OUTPUTS_DIR, exist_ok=True)

st.set_page_config(page_title="NSE Momentum Breakout Scanner", layout="wide")
st.title("NSE Momentum Breakout Scanner - 200 DMA Retest Strategy")
st.caption(
    "Educational screening only. Not financial advice. "
    "Always confirm chart, liquidity, news and risk before trading."
)


# -----------------------------------------------------------------------------
# CACHED HELPERS (avoid re-downloading the same data)
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def cached_history(symbol_ns: str, period: str) -> pd.DataFrame:
    return scanner.download_history(symbol_ns, period=period)


def load_universe(uploaded_file) -> pd.DataFrame:
    required = {"symbol", "company", "sector", "market_cap_category"}
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
    elif os.path.exists(DEFAULT_UNIVERSE):
        df = pd.read_csv(DEFAULT_UNIVERSE)
    else:
        return pd.DataFrame()
    df.columns = [c.strip().lower() for c in df.columns]
    if not required.issubset(set(df.columns)):
        st.error("universe.csv must have columns: symbol, company, sector, market_cap_category")
        return pd.DataFrame()
    return df


# -----------------------------------------------------------------------------
# SIDEBAR CONTROLS
# -----------------------------------------------------------------------------
st.sidebar.header("Scan Settings")
uploaded = st.sidebar.file_uploader("Upload universe.csv (optional)", type=["csv"])
cap_choice = st.sidebar.selectbox("Market cap category",
                                  ["Both", "Large Cap only", "Mid Cap only"])
period = st.sidebar.selectbox("Data period", ["5y", "3y", "2y"], index=0)
retest_window = st.sidebar.number_input("Retest window (days)", 20, 120, 60, 5)
retest_tol = st.sidebar.number_input("200 DMA retest tolerance %", 1.0, 15.0, 7.0, 0.5)
min_rsi = st.sidebar.number_input("Min RSI", 30.0, 90.0, 55.0, 1.0)
min_vol_ratio = st.sidebar.number_input("Min volume ratio (strong breakout)", 1.0, 5.0, 1.5, 0.1)
# NOTE: classification uses fixed score bands (Strong >=80, Wait 65-79,
# Watchlist 55-64). This minimum is the REJECT floor: anything below it is
# rejected. Default 55 keeps the Early Watchlist visible.
min_score = st.sidebar.number_input("Minimum score (below this = Rejected)", 0, 100, 55, 5)
run_clicked = st.sidebar.button("Run Scan", type="primary")


def filter_by_cap(df: pd.DataFrame, choice: str) -> pd.DataFrame:
    if choice == "Large Cap only":
        return df[df["market_cap_category"].str.strip().str.lower() == "large cap"]
    if choice == "Mid Cap only":
        return df[df["market_cap_category"].str.strip().str.lower() == "mid cap"]
    return df


if run_clicked:
    universe = load_universe(uploaded)
    if universe.empty:
        st.stop()
    universe = filter_by_cap(universe, cap_choice)
    if universe.empty:
        st.warning("No stocks match the selected market cap category.")
        st.stop()

    st.info(f"Scanning {len(universe)} stocks for period {period} ...")
    progress = st.progress(0.0)
    status = st.empty()

    def on_progress(done, total, symbol):
        progress.progress(done / total)
        status.write(f"Scanned {done}/{total}: {symbol}")

    result = scanner.run_scan(
        universe, period=period, retest_window=int(retest_window),
        retest_tol=float(retest_tol), min_rsi=float(min_rsi),
        min_vol_ratio=float(min_vol_ratio), min_score=int(min_score),
        progress_callback=on_progress,
    )
    progress.empty()
    status.empty()
    st.session_state["result"] = result
    st.session_state["period"] = period


# -----------------------------------------------------------------------------
# COLOUR CODING (by classification + risk)
# -----------------------------------------------------------------------------
def style_table(df: pd.DataFrame):
    # Colour by classification if present, else fall back to score bands.
    # (The Wait/Watchlist tab views omit the Classification column, so we must
    #  also work from Score alone.)
    def row_style(row):
        cls = str(row.get("Classification", ""))
        try:
            score = float(row.get("Score"))
        except (TypeError, ValueError):
            score = None
        green = "background-color: #1e7d32; color: white"
        yellow = "background-color: #b59f00; color: black"
        blue = "background-color: #1f4e79; color: white"
        red = "background-color: #8b1e1e; color: white"
        if cls == "Rejected":
            bg = red
        elif cls == "Strong Breakout / Actionable" or (score is not None and score >= 80):
            bg = green
        elif cls == "Wait for Confirmation" or (score is not None and 65 <= score < 80):
            bg = yellow
        elif cls == "Early Watchlist" or (score is not None and 55 <= score < 65):
            bg = blue
        else:
            bg = red
        styles = [bg] * len(row)
        if str(row.get("Breakout Status", "")) == "Above previous 52W high":
            styles = ["background-color: #0b6e2e; color: white"] * len(row)
        if str(row.get("Risk Level", "")) == "High Risk":
            styles = ["background-color: #6e0b0b; color: white"] * len(row)
        return styles
    return df.style.apply(row_style, axis=1)


def show_table(df: pd.DataFrame, cols=None, empty_msg="No stocks in this category."):
    if df is None or df.empty:
        st.info(empty_msg)
        return
    view = df[[c for c in cols if c in df.columns]] if cols else df
    st.dataframe(style_table(view), use_container_width=True, height=480)


# Column order for the "Wait for Confirmation" tab (exactly as requested).
WAIT_COLS = ["Rank", "Symbol", "Company", "Sector", "Market Cap Category", "CMP",
             "Score", "RSI 14", "Volume Ratio", "52W High", "Distance from 52W High %",
             "20 DMA", "50 DMA", "200 DMA", "Distance from 200 DMA %", "Retest Date",
             "Days Below 200 DMA", "Relative Strength %", "Breakout Status",
             "Confirmation Needed", "Trigger Price", "Suggested Alert Price",
             "Invalidation Level", "Risk Level", "Final Remark"]

STRONG_COLS = ["Rank", "Symbol", "Company", "Sector", "Market Cap Category", "CMP",
               "Score", "Classification", "RSI 14", "ADX 14", "Volume Ratio",
               "52W High", "Distance from 52W High %", "20 DMA", "50 DMA", "200 DMA",
               "Distance from 200 DMA %", "Retest Date", "Days Below 200 DMA",
               "Relative Strength %", "Breakout Status", "Entry Zone", "Trigger Price",
               "Stop Loss", "Target 1", "Target 2", "Risk Reward", "Risk Level",
               "Final Remark"]

WATCH_COLS = ["Rank", "Symbol", "Company", "Sector", "Market Cap Category", "CMP",
              "Score", "Classification", "RSI 14", "ADX 14", "Volume Ratio",
              "52W High", "Distance from 52W High %", "200 DMA",
              "Distance from 200 DMA %", "Retest Date", "Days Below 200 DMA",
              "Relative Strength %", "Breakout Status", "Confirmation Needed",
              "Trigger Price", "Risk Level", "Final Remark"]

REJECT_COLS = ["Symbol", "Company", "Sector", "Market Cap Category",
               "Classification", "Score", "Reason"]


# -----------------------------------------------------------------------------
# EXPORT (Excel multi-sheet + CSVs)
# -----------------------------------------------------------------------------
def export_outputs(result: dict):
    strong, wait = result["strong"], result["wait"]
    watch, rejected = result["watchlist"], result["rejected"]
    sector = result["sector_strength"]
    ctx = result["nifty_context"]

    strong_prompt = scanner.build_strong_prompt(strong)
    wait_prompt = scanner.build_wait_prompt(wait)

    xlsx_path = os.path.join(OUTPUTS_DIR, "scanner_output.xlsx")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        (strong if not strong.empty else pd.DataFrame()).to_excel(
            writer, sheet_name="Strong_Breakout", index=False)
        (wait if not wait.empty else pd.DataFrame()).to_excel(
            writer, sheet_name="Wait_For_Confirmation", index=False)
        (watch if not watch.empty else pd.DataFrame()).to_excel(
            writer, sheet_name="Early_Watchlist", index=False)
        (rejected if not rejected.empty else pd.DataFrame()).to_excel(
            writer, sheet_name="Rejected", index=False)
        (sector if not sector.empty else pd.DataFrame()).to_excel(
            writer, sheet_name="Sector_Strength", index=False)
        pd.DataFrame([{
            "Market Regime": result["regime"],
            "Nifty Close": ctx.get("nifty_close"),
            "Nifty 50 DMA": ctx.get("nifty_50dma"),
            "Nifty 200 DMA": ctx.get("nifty_200dma"),
            "Nifty 20-Day Return %": ctx.get("nifty_20d_return"),
            "Top 3 Sectors": ", ".join(result["top_sectors"]),
            "Scanned At": result["scanned_at"],
        }]).to_excel(writer, sheet_name="Market_Regime", index=False)
        pd.DataFrame({"Prompt": [strong_prompt, wait_prompt]}).to_excel(
            writer, sheet_name="Claude_Review", index=False)

    # CSVs
    if not strong.empty:
        strong.to_csv(os.path.join(OUTPUTS_DIR, "strong_breakout.csv"), index=False)
    if not wait.empty:
        wait.to_csv(os.path.join(OUTPUTS_DIR, "wait_for_confirmation.csv"), index=False)
    if not watch.empty:
        watch.to_csv(os.path.join(OUTPUTS_DIR, "early_watchlist.csv"), index=False)
    if not rejected.empty:
        rejected.to_csv(os.path.join(OUTPUTS_DIR, "rejected_stocks.csv"), index=False)
    return xlsx_path


# -----------------------------------------------------------------------------
# STOCK CHART (price + MAs + 52W high + trigger + invalidation + Vol + RSI + ADX)
# -----------------------------------------------------------------------------
def make_stock_chart(symbol_ns: str, period: str, trigger=None, invalidation=None):
    df = cached_history(symbol_ns, period)
    if df.empty:
        st.warning("No chart data available for this symbol.")
        return
    close = df["Close"]
    dma20, dma50, dma200 = ind.sma(close, 20), ind.sma(close, 50), ind.sma(close, 200)
    rsi14 = ind.rsi(close, 14)
    adx14 = ind.adx(df["High"], df["Low"], close, 14)
    high_52w = close.tail(252).max()

    fig = make_subplots(rows=4, cols=1, shared_xaxes=True,
                        row_heights=[0.5, 0.18, 0.16, 0.16], vertical_spacing=0.03,
                        subplot_titles=("Price + Moving Averages", "Volume", "RSI 14", "ADX 14"))
    fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"],
                                 low=df["Low"], close=df["Close"], name="Price"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=dma20, name="20 DMA", line=dict(width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=dma50, name="50 DMA", line=dict(width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=dma200, name="200 DMA", line=dict(width=2)), row=1, col=1)
    fig.add_hline(y=high_52w, line_dash="dot", line_color="orange",
                  annotation_text="52W High", row=1, col=1)
    if trigger:
        fig.add_hline(y=trigger, line_dash="dash", line_color="lime",
                      annotation_text="Trigger", row=1, col=1)
    if invalidation:
        fig.add_hline(y=invalidation, line_dash="dash", line_color="red",
                      annotation_text="Invalidation", row=1, col=1)
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=rsi14, name="RSI 14"), row=3, col=1)
    fig.add_hline(y=60, line_dash="dot", line_color="green", row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=adx14, name="ADX 14"), row=4, col=1)
    fig.add_hline(y=20, line_dash="dot", line_color="grey", row=4, col=1)
    fig.add_hline(y=25, line_dash="dot", line_color="green", row=4, col=1)
    fig.update_layout(height=850, xaxis_rangeslider_visible=False, showlegend=True,
                      margin=dict(t=40, b=20))
    st.plotly_chart(fig, use_container_width=True)


# -----------------------------------------------------------------------------
# MAIN DISPLAY
# -----------------------------------------------------------------------------
# Guard: only display when we have a NEW-format result (has "strong" key).
# This prevents a crash if an OLD-format result is left over in session_state
# after a code update (just click Run Scan again to refresh it).
if "result" in st.session_state and "strong" in st.session_state["result"]:
    result = st.session_state["result"]
    period = st.session_state.get("period", "5y")
    strong, wait = result["strong"], result["wait"]
    watch, rejected = result["watchlist"], result["rejected"]
    failed = result["failed"]
    sector = result["sector_strength"]
    regime = result["regime"]
    top3 = ", ".join(result["top_sectors"][:3]) if result["top_sectors"] else "-"

    # --- Summary cards (two rows of four) ---
    r1 = st.columns(4)
    r1[0].metric("Total Scanned", result.get("universe_count", "-"))
    r1[1].metric("Strong Breakout", len(strong))
    r1[2].metric("Wait for Confirmation", len(wait))
    r1[3].metric("Early Watchlist", len(watch))
    r2 = st.columns(4)
    r2[0].metric("Rejected", len(rejected))
    r2[1].metric("Market Regime", regime)
    r2[2].metric("Top 3 Sectors", top3)
    r2[3].metric("Failed Tickers", len(failed))

    if regime == "Weak":
        st.warning("Market Regime is WEAK - trade with caution and reduce position size.")

    tabs = st.tabs(["Strong Breakout", "Wait for Confirmation", "Early Watchlist",
                    "Rejected", "Stock Chart", "Sector Strength", "Claude Review", "Export"])

    # 1) Strong Breakout
    with tabs[0]:
        st.subheader("Strong Breakout / Actionable")
        show_table(strong, STRONG_COLS, "No strong breakout stocks with current settings.")

    # 2) Wait for Confirmation
    with tabs[1]:
        st.subheader("Wait for Confirmation")
        st.caption("Score 65-79: setup developing, breakout NOT yet confirmed. "
                   "Wait for the trigger condition before any entry.")
        show_table(wait, WAIT_COLS, "No wait-for-confirmation stocks with current settings.")

    # 3) Early Watchlist
    with tabs[2]:
        st.subheader("Early Watchlist")
        st.caption("Score 55-64: momentum developing but not ready. Keep on radar.")
        show_table(watch, WATCH_COLS, "No early-watchlist stocks with current settings.")

    # 4) Rejected
    with tabs[3]:
        st.subheader("Rejected")
        show_table(rejected, REJECT_COLS, "No rejected stocks.")
        if failed:
            st.write("**Failed tickers (download error / no data):**")
            st.write(", ".join(failed))

    # 5) Stock Chart
    with tabs[4]:
        combined = pd.concat([strong, wait, watch], ignore_index=True) \
            if any(len(x) for x in [strong, wait, watch]) else pd.DataFrame()
        if combined.empty:
            st.info("Run a scan that produces classified stocks to view charts.")
        else:
            pick = st.selectbox("Select a stock", combined["Symbol"].tolist())
            if pick:
                row = combined[combined["Symbol"] == pick].iloc[0]
                cls = row["Classification"]
                if cls == "Strong Breakout / Actionable":
                    st.success("Breakout candidate. Check chart and risk before entry.")
                elif cls == "Wait for Confirmation":
                    st.warning("This stock is not yet an entry candidate. "
                               "Wait for trigger condition.")
                else:
                    st.info("Early watchlist - momentum still developing.")
                st.write(f"**{row['Company']}** | CMP {row['CMP']} | Score {row['Score']} "
                         f"| {row['Risk Level']} | {row['Breakout Status']}")
                # Transparent component-wise score (detailed view).
                sc = st.columns(5)
                sc[0].metric("Trend /25", row.get("Trend Score", "-"))
                sc[1].metric("Pullback /20", row.get("Pullback Score", "-"))
                sc[2].metric("Momentum /20", row.get("Momentum Score", "-"))
                sc[3].metric("Breakout /20", row.get("Breakout Score", "-"))
                sc[4].metric("Risk /15", row.get("Risk Score", "-"))
                st.write(f"Trigger: {row['Trigger Price']} | "
                         f"Alert: {row['Suggested Alert Price']} | "
                         f"Invalidation: {row['Invalidation Level']}")
                if row.get("Confirmation Needed", "-") not in ("-", ""):
                    st.write(f"Confirmation needed: {row['Confirmation Needed']}")
                st.write(f"Stop Loss: {row['Stop Loss']}")
                st.write(f"Targets: {row['Target 1']} | {row['Target 2']}")
                make_stock_chart(f"{pick}.NS", period,
                                 trigger=row.get("Trigger Price"),
                                 invalidation=row.get("Invalidation Level"))

    # 6) Sector Strength
    with tabs[5]:
        st.subheader("Sector Strength (avg 20-day return of scanned stocks)")
        if sector is None or sector.empty:
            st.info("No sector data available.")
        else:
            st.dataframe(sector, use_container_width=True, height=480)

    # 7) Claude Review
    with tabs[6]:
        st.subheader("Claude / ChatGPT Review Prompts")
        st.write("**A. Strong Breakout review prompt:**")
        st.text_area("Strong breakout prompt", scanner.build_strong_prompt(strong), height=260)
        st.write("**B. Wait for Confirmation review prompt:**")
        st.text_area("Wait for confirmation prompt", scanner.build_wait_prompt(wait), height=300)

    # 8) Export
    with tabs[7]:
        st.subheader("Export results")
        if st.button("Save Excel + CSVs to outputs/ folder"):
            xlsx_path = export_outputs(result)
            st.success(f"Saved Excel + CSV files to: {OUTPUTS_DIR}")
            st.write(f"- Excel (7 sheets): {xlsx_path}")
        st.caption("On Streamlit Cloud the outputs/ folder is temporary - use the "
                   "download buttons below to save to your computer.")
        for label, df, fname in [
            ("Strong Breakout CSV", strong, "strong_breakout.csv"),
            ("Wait for Confirmation CSV", wait, "wait_for_confirmation.csv"),
            ("Early Watchlist CSV", watch, "early_watchlist.csv"),
            ("Rejected CSV", rejected, "rejected_stocks.csv"),
        ]:
            if df is not None and not df.empty:
                st.download_button(label, df.to_csv(index=False).encode("utf-8"),
                                   file_name=fname, mime="text/csv", key=fname)
else:
    st.info("Set your options in the sidebar and click **Run Scan** to begin.")
