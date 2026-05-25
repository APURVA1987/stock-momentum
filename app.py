# app.py
# -----------------------------------------------------------------------------
# This is the DASHBOARD (the screen you see in the browser).
# It is built with Streamlit. To run it, open a terminal in this folder and run:
#
#     streamlit run app.py
#
# A browser tab will open automatically. Use the sidebar on the left to set
# options, then click "Run Scan".
#
# NOTE FOR NON-CODERS:
# - This file only handles the SCREEN (buttons, tables, charts).
# - The actual scanning math lives in scanner.py and indicators.py.
# -----------------------------------------------------------------------------

import os

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import scanner
import indicators as ind


# Folder where this app.py lives, so file paths work no matter where you run it.
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
# CACHED HELPERS (so we don't re-download the same data repeatedly)
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def cached_history(symbol_ns: str, period: str) -> pd.DataFrame:
    """Cached wrapper around the download so chart redraws are fast."""
    return scanner.download_history(symbol_ns, period=period)


def load_universe(uploaded_file) -> pd.DataFrame:
    """Load the universe from an uploaded file, else from the default CSV."""
    required = {"symbol", "company", "sector", "market_cap_category"}
    if uploaded_file is not None:
        df = pd.read_csv(uploaded_file)
    elif os.path.exists(DEFAULT_UNIVERSE):
        df = pd.read_csv(DEFAULT_UNIVERSE)
    else:
        return pd.DataFrame()

    df.columns = [c.strip().lower() for c in df.columns]
    if not required.issubset(set(df.columns)):
        st.error(
            "universe.csv must have columns: symbol, company, sector, "
            "market_cap_category"
        )
        return pd.DataFrame()
    return df


# -----------------------------------------------------------------------------
# SIDEBAR CONTROLS
# -----------------------------------------------------------------------------
st.sidebar.header("Scan Settings")

uploaded = st.sidebar.file_uploader("Upload universe.csv (optional)", type=["csv"])

cap_choice = st.sidebar.selectbox(
    "Market cap category",
    ["Both", "Large Cap only", "Mid Cap only"],
)

period = st.sidebar.selectbox("Data period", ["5y", "3y", "2y"], index=0)

retest_window = st.sidebar.number_input(
    "Retest window (days)", min_value=20, max_value=120, value=60, step=5
)
retest_tol = st.sidebar.number_input(
    "200 DMA retest tolerance %", min_value=1.0, max_value=15.0, value=7.0, step=0.5
)
min_rsi = st.sidebar.number_input(
    "Min RSI", min_value=30.0, max_value=90.0, value=55.0, step=1.0
)
min_vol_ratio = st.sidebar.number_input(
    "Min volume ratio (strong breakout)", min_value=1.0, max_value=5.0, value=1.5, step=0.1
)
min_score = st.sidebar.number_input(
    "Minimum score", min_value=0, max_value=100, value=65, step=5
)

run_clicked = st.sidebar.button("Run Scan", type="primary")


# -----------------------------------------------------------------------------
# RUN THE SCAN
# -----------------------------------------------------------------------------
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
        universe,
        period=period,
        retest_window=int(retest_window),
        retest_tol=float(retest_tol),
        min_rsi=float(min_rsi),
        min_vol_ratio=float(min_vol_ratio),
        min_score=int(min_score),
        progress_callback=on_progress,
    )
    progress.empty()
    status.empty()

    # Keep results in session_state so they survive UI interactions.
    st.session_state["result"] = result
    st.session_state["period"] = period


# -----------------------------------------------------------------------------
# DISPLAY RESULTS (if we have any)
# -----------------------------------------------------------------------------
def style_table(df: pd.DataFrame):
    """Colour-code the table by score and risk."""
    def row_style(row):
        styles = [""] * len(row)
        score = row.get("Score", 0)
        if score >= 80:
            bg = "background-color: #1e7d32; color: white"   # green
        elif score >= 65:
            bg = "background-color: #b59f00; color: black"    # yellow
        else:
            bg = "background-color: #8b1e1e; color: white"    # red
        styles = [bg] * len(row)
        # Highlight breakout rows with a stronger green border-ish tone.
        if str(row.get("Breakout Status", "")) == "Above previous 52W high":
            styles = ["background-color: #0b6e2e; color: white"] * len(row)
        if str(row.get("Risk Level", "")) == "High Risk":
            styles = ["background-color: #6e0b0b; color: white"] * len(row)
        return styles

    return df.style.apply(row_style, axis=1)


def export_outputs(result: dict):
    """Write Excel (multi-sheet) + CSV files into outputs/."""
    qdf = result["qualified"]
    rdf = result["rejected"]
    failed = result["failed"]
    prompt = scanner.build_claude_prompt(qdf)

    xlsx_path = os.path.join(OUTPUTS_DIR, "scanner_output.xlsx")
    csv_path = os.path.join(OUTPUTS_DIR, "scanner_output.csv")
    rej_path = os.path.join(OUTPUTS_DIR, "rejected_stocks.csv")

    # Multi-sheet Excel.
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        (qdf if not qdf.empty else pd.DataFrame()).to_excel(
            writer, sheet_name="Scanner_Output", index=False)
        # Raw summary = a compact view of qualified stocks.
        summary_cols = ["Rank", "Symbol", "Company", "Sector", "CMP", "Score",
                        "Risk Level", "Breakout Status"]
        raw = qdf[summary_cols] if (not qdf.empty) else pd.DataFrame()
        raw.to_excel(writer, sheet_name="Raw_Summary", index=False)
        (rdf if not rdf.empty else pd.DataFrame()).to_excel(
            writer, sheet_name="Rejected", index=False)
        pd.DataFrame({"Failed Tickers": failed}).to_excel(
            writer, sheet_name="Failed_Tickers", index=False)
        pd.DataFrame({"Claude_Review_Prompt": [prompt]}).to_excel(
            writer, sheet_name="Claude_Review", index=False)

    if not qdf.empty:
        qdf.to_csv(csv_path, index=False)
    if not rdf.empty:
        rdf.to_csv(rej_path, index=False)

    return xlsx_path, csv_path, rej_path, prompt


def make_stock_chart(symbol_ns: str, period: str):
    """Candlestick + moving averages + volume + RSI using Plotly."""
    df = cached_history(symbol_ns, period)
    if df.empty:
        st.warning("No chart data available for this symbol.")
        return

    close = df["Close"]
    dma20 = ind.sma(close, 20)
    dma50 = ind.sma(close, 50)
    dma200 = ind.sma(close, 200)
    rsi14 = ind.rsi(close, 14)
    high_52w = close.tail(252).max()

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03,
        subplot_titles=("Price + Moving Averages", "Volume", "RSI 14"),
    )

    # Candles
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"],
        close=df["Close"], name="Price"), row=1, col=1)
    # Moving averages
    fig.add_trace(go.Scatter(x=df.index, y=dma20, name="20 DMA",
                             line=dict(width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=dma50, name="50 DMA",
                             line=dict(width=1)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=dma200, name="200 DMA",
                             line=dict(width=2)), row=1, col=1)
    # 52W high line
    fig.add_hline(y=high_52w, line_dash="dot", line_color="orange",
                  annotation_text="52W High", row=1, col=1)
    # Volume
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume"),
                  row=2, col=1)
    # RSI
    fig.add_trace(go.Scatter(x=df.index, y=rsi14, name="RSI 14"), row=3, col=1)
    fig.add_hline(y=55, line_dash="dot", line_color="green", row=3, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color="red", row=3, col=1)

    fig.update_layout(height=750, xaxis_rangeslider_visible=False,
                      showlegend=True, margin=dict(t=40, b=20))
    st.plotly_chart(fig, use_container_width=True)


if "result" in st.session_state:
    result = st.session_state["result"]
    period = st.session_state.get("period", "5y")
    qdf = result["qualified"]
    rdf = result["rejected"]
    failed = result["failed"]

    strong = int((qdf["Tag"] == "Strong Breakout").sum()) if not qdf.empty else 0
    watch = int((qdf["Tag"] == "Watchlist").sum()) if not qdf.empty else 0
    scanned_total = (len(qdf) + len(rdf) + len(failed))

    # --- Summary cards ---
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Scanned", scanned_total)
    c2.metric("Qualified", len(qdf))
    c3.metric("Strong Breakout", strong)
    c4.metric("Watchlist", watch)
    c5.metric("Failed Tickers", len(failed))

    tabs = st.tabs(["Ranked Results", "Stock Chart", "Rejected", "Claude Review", "Export"])

    # --- Tab 1: Ranked table ---
    with tabs[0]:
        if qdf.empty:
            st.warning("No stocks qualified with the current settings.")
        else:
            display_cols = [c for c in qdf.columns if c != "Tag"]
            st.dataframe(style_table(qdf[display_cols]), use_container_width=True,
                         height=520)

    # --- Tab 2: Stock chart ---
    with tabs[1]:
        if qdf.empty:
            st.info("Run a scan that produces qualified stocks to view charts.")
        else:
            pick = st.selectbox("Select a stock", qdf["Symbol"].tolist())
            if pick:
                row = qdf[qdf["Symbol"] == pick].iloc[0]
                st.write(
                    f"**{row['Company']}** | CMP {row['CMP']} | Score {row['Score']} | "
                    f"{row['Risk Level']} | {row['Breakout Status']}"
                )
                st.write(f"Entry: {row['Entry Zone']}")
                st.write(f"Stop Loss: {row['Stop Loss']}")
                st.write(f"Targets: {row['Target 1']} | {row['Target 2']}")
                make_stock_chart(f"{pick}.NS", period)

    # --- Tab 3: Rejected ---
    with tabs[2]:
        if rdf.empty:
            st.info("No rejected stocks.")
        else:
            st.dataframe(rdf, use_container_width=True, height=520)
        if failed:
            st.write("**Failed tickers (download error / no data):**")
            st.write(", ".join(failed))

    # --- Tab 4: Claude review prompt ---
    with tabs[3]:
        prompt = scanner.build_claude_prompt(qdf)
        st.write("Copy this prompt into Claude or ChatGPT for a deeper review:")
        st.text_area("Claude / ChatGPT review prompt", prompt, height=400)

    # --- Tab 5: Export ---
    with tabs[4]:
        if st.button("Save Excel + CSV to outputs/ folder"):
            xlsx_path, csv_path, rej_path, _ = export_outputs(result)
            st.success("Files saved to the outputs/ folder.")
            st.write(f"- Excel: {xlsx_path}")
            st.write(f"- CSV: {csv_path}")
            st.write(f"- Rejected CSV: {rej_path}")

        if not qdf.empty:
            st.download_button(
                "Download qualified stocks CSV",
                qdf.to_csv(index=False).encode("utf-8"),
                file_name="scanner_output.csv",
                mime="text/csv",
            )
else:
    st.info("Set your options in the sidebar and click **Run Scan** to begin.")
