# app.py
# -----------------------------------------------------------------------------
# NSE Momentum Breakout DASHBOARD (the screen you see in the browser).
# Built with Streamlit + Plotly. Run it with:   streamlit run app.py
#
# NOTE FOR NON-CODERS:
# - This file ONLY handles the visual dashboard (cards, charts, gauges, tabs).
# - The scanning maths is untouched and lives in scanner.py / indicators.py.
# - Each dashboard section is clearly commented below.
# -----------------------------------------------------------------------------

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

import scanner
import indicators as ind
import fundamentals


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
DEFAULT_UNIVERSE = os.path.join(BASE_DIR, "universe.csv")
os.makedirs(OUTPUTS_DIR, exist_ok=True)

st.set_page_config(page_title="NSE Momentum Breakout Dashboard", layout="wide")

# Colour language used across the whole dashboard.
CLASS_COLORS = {
    "Strong Breakout / Actionable": "#1e7d32",   # green
    "Wait for Confirmation": "#e08e0b",          # orange/yellow
    "Early Watchlist": "#1f77b4",                # blue
    "Rejected": "#8b1e1e",                       # red/grey
}
RISK_COLORS = {"Low Risk": "#1e7d32", "Medium Risk": "#e08e0b", "High Risk": "#8b1e1e"}


# -----------------------------------------------------------------------------
# SMALL UI HELPERS
# -----------------------------------------------------------------------------
def metric_card(col, label, value, color, sub=""):
    """A coloured metric card (nicer than the plain st.metric box)."""
    col.markdown(
        f"<div style='background:{color};padding:14px 10px;border-radius:12px;"
        f"text-align:center;color:white;'>"
        f"<div style='font-size:13px;opacity:.9'>{label}</div>"
        f"<div style='font-size:30px;font-weight:700;line-height:1.1'>{value}</div>"
        f"<div style='font-size:11px;opacity:.9'>{sub}</div></div>",
        unsafe_allow_html=True,
    )


def badge(text, color):
    return (f"<span style='background:{color};color:white;padding:3px 10px;"
            f"border-radius:12px;font-size:13px;font-weight:600'>{text}</span>")


def safe_num(v, default=0.0):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


@st.cache_data(show_spinner=False)
def cached_history(symbol_ns: str, period: str) -> pd.DataFrame:
    return scanner.download_history(symbol_ns, period=period)


@st.cache_data(show_spinner=False, ttl=86400)
def cached_fundamentals(symbol: str):
    """Screener.in fundamentals for ONE symbol (cached for a day)."""
    return fundamentals.get_fundamentals(symbol)


# Streamlit column config that turns a "Screener" URL column into a clickable link.
SCREENER_COLCFG = {"Screener": st.column_config.LinkColumn("Screener", display_text="open")}


def df_with_links(df: pd.DataFrame, cols, height=420):
    """Show a table with a clickable Screener link as the first column."""
    if df is None or df.empty:
        st.info("No rows.")
        return
    d = df.copy()
    d["Screener"] = d["Symbol"].map(fundamentals.screener_url)
    show = ["Screener"] + [c for c in cols if c in d.columns]
    st.dataframe(d[show], use_container_width=True, height=height, column_config=SCREENER_COLCFG)


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


def classified_all(result) -> pd.DataFrame:
    """Strong + Wait + Watchlist combined into one frame (for maps/charts)."""
    parts = [result[k] for k in ("strong", "wait", "watchlist")
             if isinstance(result[k], pd.DataFrame) and not result[k].empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# -----------------------------------------------------------------------------
# SIDEBAR (unchanged scan controls)
# -----------------------------------------------------------------------------
st.sidebar.header("Scan Settings")
uploaded = st.sidebar.file_uploader("Upload universe.csv (optional)", type=["csv"])
cap_choice = st.sidebar.selectbox(
    "Market cap category",
    ["All", "Large Cap only", "Mid Cap only", "Small Cap only",
     "Large + Mid", "Mid + Small"])
period = st.sidebar.selectbox("Data period", ["5y", "3y", "2y"], index=0)
retest_window = st.sidebar.number_input("Retest window (days)", 20, 120, 60, 5)
retest_tol = st.sidebar.number_input("200 DMA retest tolerance %", 1.0, 15.0, 7.0, 0.5)
min_rsi = st.sidebar.number_input("Min RSI", 30.0, 90.0, 55.0, 1.0)
min_vol_ratio = st.sidebar.number_input("Min volume ratio (strong breakout)", 1.0, 5.0, 1.5, 0.1)
min_score = st.sidebar.number_input("Minimum score (below this = Rejected)", 0, 100, 55, 5)
local_mode = st.sidebar.checkbox(
    "Local mode (NSE bhavcopy + price cache)", value=False,
    help="Only works when you run the app on your OWN PC. Reuses a local price "
         "cache (fast repeat runs) and overlays the latest official NSE bhavcopy "
         "day on top of Yahoo history. Leave OFF on Streamlit Cloud (NSE blocks "
         "cloud servers).")
run_clicked = st.sidebar.button("Run Scan", type="primary")


def filter_by_cap(df, choice):
    cat = df["market_cap_category"].str.strip().str.lower()
    if choice == "Large Cap only":
        return df[cat == "large cap"]
    if choice == "Mid Cap only":
        return df[cat == "mid cap"]
    if choice == "Small Cap only":
        return df[cat == "small cap"]
    if choice == "Large + Mid":
        return df[cat.isin(["large cap", "mid cap"])]
    if choice == "Mid + Small":
        return df[cat.isin(["mid cap", "small cap"])]
    return df   # "All"


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
        local_mode=bool(local_mode),
        progress_callback=on_progress,
    )
    progress.empty()
    status.empty()
    st.session_state["result"] = result
    st.session_state["period"] = period


# =============================================================================
# EXPORT (existing system kept; plus new dashboard_summary.xlsx)
# =============================================================================
def _x(df):
    """Empty buckets get a one-row placeholder so the Excel sheet is never a
    zero-column sheet (which crashes openpyxl on save)."""
    return df if (df is not None and not df.empty) else pd.DataFrame({"Info": ["No stocks in this bucket"]})


def _write_workbook(path, sheets: dict):
    """Write an ordered {sheet_name: df} mapping to one .xlsx.

    Uses keyword `sheet_name=` (required by pandas 3.x, where it is keyword-only)
    and forces a visible active sheet before save — this avoids the
    'At least one sheet must be visible' IndexError seen with openpyxl + pandas 3.
    """
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        for name, df in sheets.items():
            _x(df).to_excel(w, sheet_name=name, index=False)
        try:
            if getattr(w, "book", None) is not None and len(w.book.worksheets):
                for ws in w.book.worksheets:
                    ws.sheet_state = "visible"
                w.book.active = 0
        except Exception:
            pass
    return path


def export_outputs(result):
    strong, wait = result["strong"], result["wait"]
    watch, rejected = result["watchlist"], result["rejected"]
    sector, ctx = result["sector_strength"], result["nifty_context"]
    sector_rot = result.get("sector_rotation", pd.DataFrame())
    allst = result.get("all_stocks", pd.DataFrame())
    coiled, fresh = result.get("coiled", pd.DataFrame()), result.get("fresh", pd.DataFrame())

    def _sel(df, col, val, sort="Composite Score"):
        if df is None or df.empty or col not in df:
            return pd.DataFrame()
        out = df[df[col] == val]
        return out.sort_values(sort, ascending=False) if sort in out else out

    rs_leaders = _sel(allst, "RS Leader", "Yes", sort="RS Score")
    do_not_chase = _sel(allst, "Overextended", "Yes")
    elite = _sel(allst, "Momentum Class", "Elite Momentum")
    actionable = _sel(allst, "Momentum Class", "Actionable Breakout")
    market = pd.DataFrame([{
        "Market Regime": result["regime"], "Nifty Close": ctx.get("nifty_close"),
        "Nifty 50 DMA": ctx.get("nifty_50dma"), "Nifty 200 DMA": ctx.get("nifty_200dma"),
        "Nifty 20-Day Return %": ctx.get("nifty_20d_return"),
        "Top 3 Sectors": ", ".join(result["top_sectors"]), "Scanned At": result["scanned_at"]}])
    claude = pd.DataFrame({"Prompt": [
        scanner.build_strong_prompt(strong), scanner.build_wait_prompt(wait),
        scanner.build_coiled_prompt(coiled), scanner.build_fresh_prompt(fresh),
        scanner.build_donotchase_prompt(do_not_chase)]})

    xlsx_path = _write_workbook(os.path.join(OUTPUTS_DIR, "scanner_output.xlsx"), {
        "Elite_Momentum": elite, "Actionable_Breakout": actionable,
        "Strong_Breakout": strong, "Wait_For_Confirmation": wait,
        "Coiled_Ready": coiled, "Fresh_Momentum": fresh, "Early_Watchlist": watch,
        "RS_Leaders": rs_leaders, "Sector_Rotation": sector_rot,
        "Do_Not_Chase": do_not_chase, "Rejected": rejected,
        "Failed_Tickers": pd.DataFrame({"Failed Tickers": result["failed"]}),
        "Sector_Strength": sector, "Market_Regime": market, "Claude_Review": claude})
    for df, fn in [(strong, "strong_breakout.csv"), (wait, "wait_for_confirmation.csv"),
                   (coiled, "coiled_ready.csv"), (fresh, "fresh_momentum.csv"),
                   (watch, "early_watchlist.csv"), (rs_leaders, "rs_leaders.csv"),
                   (sector_rot, "sector_rotation.csv"), (do_not_chase, "do_not_chase.csv"),
                   (rejected, "rejected_stocks.csv")]:
        if df is not None and not df.empty:
            df.to_csv(os.path.join(OUTPUTS_DIR, fn), index=False)
    return xlsx_path


def export_dashboard_summary(result, overext):
    """New optional workbook with the most useful at-a-glance sheets."""
    strong, wait = result["strong"], result["wait"]
    summary = pd.DataFrame([{
        "Scanned At": result["scanned_at"], "Universe": result.get("universe_count"),
        "Market Regime": result["regime"], "Strong Breakout": len(strong),
        "Wait for Confirmation": len(wait), "Early Watchlist": len(result["watchlist"]),
        "Rejected": len(result["rejected"]), "Failed": len(result["failed"]),
        "Top 3 Sectors": ", ".join(result["top_sectors"])}])
    return _write_workbook(os.path.join(OUTPUTS_DIR, "dashboard_summary.xlsx"), {
        "Dashboard_Summary": summary, "Sector_Strength": result["sector_strength"],
        "Top_10_Strong": strong.head(10) if not strong.empty else pd.DataFrame(),
        "Top_10_Wait_For_Confirmation": wait.head(10) if not wait.empty else pd.DataFrame(),
        "Overextended_Stocks": overext})


# =============================================================================
# CANDLESTICK (price + MAs + 52W high + trigger + invalidation + Vol + RSI + ADX)
# =============================================================================
def make_stock_chart(symbol_ns, period, trigger=None, invalidation=None):
    df = cached_history(symbol_ns, period)
    if df.empty:
        st.warning("No chart data available for this symbol.")
        return
    close = df["Close"]
    dma20, dma50, dma200 = ind.sma(close, 20), ind.sma(close, 50), ind.sma(close, 200)
    dma100 = ind.sma(close, 100)
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
    fig.add_trace(go.Scatter(x=df.index, y=dma100, name="100 DMA", line=dict(width=1, dash="dot")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=dma200, name="200 DMA", line=dict(width=2)), row=1, col=1)
    fig.add_hline(y=high_52w, line_dash="dot", line_color="orange", annotation_text="52W High", row=1, col=1)
    if trigger:
        fig.add_hline(y=trigger, line_dash="dash", line_color="lime", annotation_text="Trigger", row=1, col=1)
    if invalidation:
        fig.add_hline(y=invalidation, line_dash="dash", line_color="red", annotation_text="Invalidation/SL", row=1, col=1)
    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=rsi14, name="RSI 14"), row=3, col=1)
    fig.add_hline(y=60, line_dash="dot", line_color="green", row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=adx14, name="ADX 14"), row=4, col=1)
    fig.add_hline(y=20, line_dash="dot", line_color="grey", row=4, col=1)
    fig.update_layout(height=820, xaxis_rangeslider_visible=False, showlegend=True,
                      margin=dict(t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)


def score_gauge(score):
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=safe_num(score),
        gauge={"axis": {"range": [0, 100]}, "bar": {"color": "black"},
               "steps": [{"range": [0, 55], "color": "#8b1e1e"},
                         {"range": [55, 65], "color": "#1f77b4"},
                         {"range": [65, 80], "color": "#e08e0b"},
                         {"range": [80, 100], "color": "#1e7d32"}]}))
    fig.update_layout(height=260, margin=dict(t=30, b=10))
    return fig


# =============================================================================
# CARD RENDERERS
# =============================================================================
def stock_cards(df, n, accent, fields):
    """Render the top `n` rows of df as coloured cards (fields = list of (label,col))."""
    rows = df.head(n)
    cols = st.columns(min(5, max(1, len(rows))))
    for i, (_, r) in enumerate(rows.iterrows()):
        body = "".join(
            f"<div style='font-size:12px'><b>{lbl}:</b> {r.get(c, '-')}</div>"
            for lbl, c in fields)
        url = fundamentals.screener_url(r["Symbol"])
        cols[i % len(cols)].markdown(
            f"<div style='border:2px solid {accent};border-radius:12px;padding:10px;"
            f"margin-bottom:8px;background:rgba(255,255,255,0.03)'>"
            f"<div style='font-size:17px;font-weight:700'>"
            f"<a href='{url}' target='_blank' style='color:inherit;text-decoration:none'>"
            f"{r['Symbol']} &#128279;</a></div>"
            f"<div style='font-size:11px;opacity:.8;margin-bottom:6px'>{r['Company']}</div>"
            f"{body}</div>", unsafe_allow_html=True)


# =============================================================================
# MAIN
# =============================================================================
# Guard: only render when we have a NEW-format result in session_state.
if "result" in st.session_state and "strong" in st.session_state["result"]:
    result = st.session_state["result"]
    period = st.session_state.get("period", "5y")
    strong, wait = result["strong"], result["wait"]
    watch, rejected = result["watchlist"], result["rejected"]
    failed = result["failed"]
    sector = result["sector_strength"]
    regime = result["regime"]
    ctx = result["nifty_context"]
    allc = classified_all(result)

    # ---- A. HEADER ----
    regime_color = {"Bullish": "#1e7d32", "Neutral": "#e08e0b",
                    "Weak": "#8b1e1e"}.get(regime, "#555")
    st.markdown(
        f"<h1 style='margin-bottom:0'>NSE Momentum Breakout Dashboard</h1>"
        f"<div style='opacity:.8;font-size:13px'>Last scan: {result['scanned_at']} "
        f"&nbsp;|&nbsp; Universe: {result.get('universe_count')} &nbsp;|&nbsp; "
        f"Period: {period} &nbsp;|&nbsp; Market Regime: {badge(regime, regime_color)}</div>",
        unsafe_allow_html=True)
    st.caption("Educational screening only. Not financial advice. Confirm chart, "
               "liquidity, news and risk before trading.")
    st.write("")

    # ---- B. TOP SUMMARY CARDS ----
    c = st.columns(6)
    metric_card(c[0], "Total Scanned", result.get("universe_count", "-"), "#37474f")
    metric_card(c[1], "Strong Breakout", len(strong), CLASS_COLORS["Strong Breakout / Actionable"])
    metric_card(c[2], "Wait for Confirmation", len(wait), CLASS_COLORS["Wait for Confirmation"])
    metric_card(c[3], "Early Watchlist", len(watch), CLASS_COLORS["Early Watchlist"])
    metric_card(c[4], "Rejected", len(rejected), CLASS_COLORS["Rejected"])
    metric_card(c[5], "Failed Tickers", len(failed), "#555")
    if regime == "Weak":
        st.warning("Market Regime is WEAK - trade with caution and reduce position size.")
    st.write("")

    allstocks = result.get("all_stocks", pd.DataFrame())     # full universe incl. rejected
    sector_rot = result.get("sector_rotation", pd.DataFrame())
    coiled = result.get("coiled", pd.DataFrame())
    fresh = result.get("fresh", pd.DataFrame())

    # Name-keyed tabs (order can change without breaking the blocks below).
    tab_names = ["Market Overview", "Sector Rotation", "RS Leaders", "Strong Breakout",
                 "Wait for Confirmation", "Coiled / Ready", "Fresh Momentum",
                 "Early Watchlist", "Do Not Chase", "Momentum Map",
                 "Stock Deep Dive", "Rejected / Failed", "Claude Review", "Export"]
    T = dict(zip(tab_names, st.tabs(tab_names)))

    # =====================================================================
    # 1) MARKET OVERVIEW
    # =====================================================================
    with T["Market Overview"]:
        cc = st.columns(2)
        # A. Classification donut
        donut = pd.DataFrame({
            "Class": ["Strong Breakout", "Wait for Confirmation", "Early Watchlist", "Rejected"],
            "Count": [len(strong), len(wait), len(watch), len(rejected)]})
        fig = px.pie(donut, names="Class", values="Count", hole=0.5,
                     color="Class", color_discrete_map={
                         "Strong Breakout": CLASS_COLORS["Strong Breakout / Actionable"],
                         "Wait for Confirmation": CLASS_COLORS["Wait for Confirmation"],
                         "Early Watchlist": CLASS_COLORS["Early Watchlist"],
                         "Rejected": CLASS_COLORS["Rejected"]},
                     title="Classification split")
        cc[0].plotly_chart(fig, use_container_width=True)

        # B. Score distribution (bands)
        def scores_of(df):
            if df is None or df.empty or "Score" not in df:
                return []
            return [s for s in pd.to_numeric(df["Score"], errors="coerce").dropna().tolist()]
        all_scores = scores_of(strong) + scores_of(wait) + scores_of(watch) + scores_of(rejected)
        bands = {"80-100": 0, "65-80": 0, "55-65": 0, "Below 55": 0}
        for s in all_scores:
            if s >= 80: bands["80-100"] += 1
            elif s >= 65: bands["65-80"] += 1
            elif s >= 55: bands["55-65"] += 1
            else: bands["Below 55"] += 1
        bdf = pd.DataFrame({"Band": list(bands), "Count": list(bands.values())})
        cc[1].plotly_chart(px.bar(bdf, x="Band", y="Count", title="Score distribution",
                                  color="Band", color_discrete_sequence=["#1e7d32", "#e08e0b", "#1f77b4", "#8b1e1e"]),
                           use_container_width=True)

        # C. Market regime panel
        st.subheader("Market Regime (Nifty 50)")
        m = st.columns(4)
        nclose = ctx.get("nifty_close"); n50 = ctx.get("nifty_50dma"); n200 = ctx.get("nifty_200dma")
        metric_card(m[0], "Nifty Close", nclose, "#37474f")
        metric_card(m[1], "vs 50 DMA", "Above" if safe_num(nclose) > safe_num(n50) else "Below",
                    "#1e7d32" if safe_num(nclose) > safe_num(n50) else "#8b1e1e", sub=f"50 DMA {n50}")
        metric_card(m[2], "vs 200 DMA", "Above" if safe_num(nclose) > safe_num(n200) else "Below",
                    "#1e7d32" if safe_num(nclose) > safe_num(n200) else "#8b1e1e", sub=f"200 DMA {n200}")
        metric_card(m[3], "Nifty 20D Return %", ctx.get("nifty_20d_return"),
                    "#1e7d32" if safe_num(ctx.get("nifty_20d_return")) > 0 else "#8b1e1e")

        # D + E. Top momentum + relative strength
        if not allc.empty:
            d = st.columns(2)
            top_score = allc.sort_values("Score", ascending=False).head(10)
            d[0].plotly_chart(px.bar(top_score, x="Symbol", y="Score", color="Classification",
                                     color_discrete_map=CLASS_COLORS, title="Top 10 by Score",
                                     hover_data=["RSI 14", "Volume Ratio", "Relative Strength %"]),
                              use_container_width=True)
            top_rs = allc.sort_values("Relative Strength %", ascending=False).head(10)
            d[1].plotly_chart(px.bar(top_rs, x="Symbol", y="Relative Strength %", color="Classification",
                                     color_discrete_map=CLASS_COLORS, title="Top 10 by Relative Strength vs Nifty"),
                              use_container_width=True)

    # =====================================================================
    # 2) STRONG BREAKOUT
    # =====================================================================
    with T["Strong Breakout"]:
        st.subheader("Strong Breakout / Actionable")
        if strong.empty:
            st.info("No strong breakout stocks with current settings.")
        else:
            # A. Top 5 cards
            stock_cards(strong, 5, CLASS_COLORS["Strong Breakout / Actionable"], [
                ("Score", "Score"), ("CMP", "CMP"), ("Breakout", "Breakout Status"),
                ("RSI", "RSI 14"), ("Vol Ratio", "Volume Ratio"), ("Risk", "Risk Level"),
                ("Entry", "Entry Zone"), ("Stop", "Stop Loss"),
                ("T1", "Target 1"), ("T2", "Target 2")])
            st.write("")
            g = st.columns(2)
            # B. Ranking bar
            g[0].plotly_chart(px.bar(strong.sort_values("Score").tail(20), x="Score", y="Symbol",
                                     orientation="h", title="Strong Breakout ranking",
                                     hover_data=["RSI 14", "Volume Ratio", "Relative Strength %"],
                                     color="Score", color_continuous_scale="Greens"),
                              use_container_width=True)
            # C. Risk-reward scatter
            sd = strong.copy()
            sd["Risk %"] = ((sd["CMP"] - sd["Invalidation Level"]) / sd["CMP"] * 100).round(2)
            g[1].plotly_chart(px.scatter(sd, x="Risk %", y="Risk Reward", size="Volume Ratio",
                                         color="Risk Level", color_discrete_map=RISK_COLORS,
                                         hover_name="Symbol", title="Risk vs Reward (bubble = volume)",
                                         size_max=30),
                              use_container_width=True)
            # D. Detailed table
            with st.expander("Detailed table"):
                df_with_links(strong, list(strong.columns), height=420)

    # =====================================================================
    # 3) WAIT FOR CONFIRMATION
    # =====================================================================
    with T["Wait for Confirmation"]:
        st.warning("These stocks are NOT entry candidates yet. Set alerts and wait "
                   "for the trigger condition.")
        if wait.empty:
            st.info("No wait-for-confirmation stocks with current settings.")
        else:
            wd = wait.copy()
            wd["Distance to Trigger %"] = ((wd["Trigger Price"] / wd["CMP"] - 1) * 100).round(2)
            # B. Cards (top 10, two rows of five)
            stock_cards(wd, 5, CLASS_COLORS["Wait for Confirmation"], [
                ("CMP", "CMP"), ("Score", "Score"), ("Trigger", "Trigger Price"),
                ("Alert", "Suggested Alert Price"), ("To Trigger %", "Distance to Trigger %"),
                ("RSI", "RSI 14"), ("Vol", "Volume Ratio"), ("Need", "Confirmation Needed")])
            st.write("")
            gg = st.columns(2)
            # C. Distance to breakout
            near = wd.sort_values("Distance to Trigger %").head(15)
            gg[0].plotly_chart(px.bar(near, x="Distance to Trigger %", y="Symbol", orientation="h",
                                      title="Closest to trigger", color="Distance to Trigger %",
                                      color_continuous_scale="Oranges_r"), use_container_width=True)
            # D. Confirmation type breakdown
            keys = {"Price breakout (52W high)": "52W high", "RSI cross 60": "RSI",
                    "Volume expansion": "volume", "Sustain above 50 DMA": "50 DMA",
                    "2-day sustain": "consecutive", "Relative strength": "relative strength"}
            counts = {k: int(wd["Confirmation Needed"].str.contains(v, case=False, na=False).sum())
                      for k, v in keys.items()}
            cdf = pd.DataFrame({"Confirmation": list(counts), "Count": list(counts.values())})
            gg[1].plotly_chart(px.bar(cdf, x="Count", y="Confirmation", orientation="h",
                                      title="What are they waiting for?",
                                      color_discrete_sequence=["#e08e0b"]), use_container_width=True)
            # E. Alert watchlist table
            alert_cols = ["Symbol", "Company", "CMP", "Trigger Price", "Suggested Alert Price",
                          "Distance to Trigger %", "Confirmation Needed", "Invalidation Level",
                          "Score", "Risk Level"]
            tbl = wd.sort_values(["Distance to Trigger %", "Score", "Relative Strength %"],
                                 ascending=[True, False, False])
            df_with_links(tbl, alert_cols, height=420)

    # =====================================================================
    # 4) EARLY WATCHLIST
    # =====================================================================
    with T["Early Watchlist"]:
        st.info("Observe only. No trade until confirmation improves.")
        if watch.empty:
            st.info("No early-watchlist stocks with current settings.")
        else:
            stock_cards(watch, 5, CLASS_COLORS["Early Watchlist"], [
                ("CMP", "CMP"), ("Score", "Score"), ("RSI", "RSI 14"),
                ("Vol", "Volume Ratio"), ("Retest", "Retest Date"),
                ("RelStr %", "Relative Strength %"), ("Breakout", "Breakout Status")])
            st.write("")
            st.plotly_chart(px.bar(watch.sort_values("Score").tail(20), x="Score", y="Symbol",
                                   orientation="h", title="Top early setups by score",
                                   color="Score", color_continuous_scale="Blues"),
                            use_container_width=True)
            with st.expander("Detailed table"):
                st.dataframe(watch, use_container_width=True, height=400)

    # =====================================================================
    # SECTOR ROTATION (percentile-ranked sector strength engine)
    # =====================================================================
    with T["Sector Rotation"]:
        if sector_rot is None or sector_rot.empty:
            st.info("No sector data available.")
        else:
            # A. Top sector cards
            st.subheader("Leading sectors")
            tcols = st.columns(3)
            for i, (_, s) in enumerate(sector_rot.head(3).iterrows()):
                metric_card(tcols[i], f"{s['Sector']} ({s['Sector Status']})",
                            f"{s['Sector Strength Score']:.0f}/100", "#1f4e79",
                            sub=f"20D {s['Avg_Return_20D']}% | {int(s['Strong'])} strong / "
                                f"{int(s['Wait'])} wait / {int(s['RS_Leaders'])} RS")
            # B. Sector strength bar chart
            st.plotly_chart(px.bar(sector_rot.sort_values("Sector Strength Score"),
                                   x="Sector Strength Score", y="Sector", orientation="h",
                                   title="Sector strength score (0-100)", color="Sector Strength Score",
                                   color_continuous_scale="RdYlGn"), use_container_width=True)
            # C. Sector heatmap (no matplotlib dependency)
            metrics = ["Sector Strength Score", "Avg_Return_20D", "Avg_Return_60D",
                       "Avg_RS_Score", "Pct_Above_50DMA", "Strong", "Wait"]
            hm = sector_rot.set_index("Sector")[metrics]
            znorm = (hm - hm.min()) / (hm.max() - hm.min() + 1e-9)
            heat = go.Figure(go.Heatmap(z=znorm.values, x=metrics, y=hm.index.tolist(),
                                        text=hm.values, texttemplate="%{text}",
                                        colorscale="RdYlGn", showscale=False))
            heat.update_layout(height=max(320, 26 * len(hm)), margin=dict(t=20, b=10))
            st.plotly_chart(heat, use_container_width=True)
            # D. Full sector table
            with st.expander("Full sector table"):
                st.dataframe(sector_rot, use_container_width=True, height=360)
            # E. Sector drill-down
            if not allstocks.empty:
                sec_pick = st.selectbox("Show stocks in sector", list(sector_rot["Sector"]))
                st.dataframe(allstocks[allstocks["Sector"] == sec_pick][
                    ["Symbol", "Company", "Classification", "Composite Score", "RS Score",
                     "RSI 14", "Volume Ratio", "Relative Strength %", "Breakout Status"]]
                    .sort_values("Composite Score", ascending=False),
                    use_container_width=True, height=320)

    # =====================================================================
    # RS LEADERS (multi-timeframe relative strength)
    # =====================================================================
    with T["RS Leaders"]:
        st.subheader("Relative Strength Leaders")
        st.caption("RS Score = percentile rank of relative strength vs Nifty across "
                   "5D/20D/60D/120D/252D. RS Leader = rs_score>=80, RS positive on "
                   "20D & 60D, and price above 50 & 200 DMA.")
        if allstocks.empty:
            st.info("Run a scan to view RS leaders.")
        else:
            rs = allstocks.sort_values("RS Score", ascending=False).head(20).copy()
            st.plotly_chart(px.bar(rs.sort_values("RS Score"), x="RS Score", y="Symbol",
                                   orientation="h", title="Top 20 by RS Score",
                                   color="RS Score", color_continuous_scale="Viridis",
                                   hover_data=["Sector", "RS 20D %", "RS 60D %", "RS 120D %"]),
                            use_container_width=True)
            rs_cols = ["Symbol", "Company", "Sector", "Classification", "RS Leader", "RS Score",
                       "RS 5D %", "RS 20D %", "RS 60D %", "RS 120D %", "RS 252D %", "CMP",
                       "Distance from 52W High %", "Composite Score"]
            df_with_links(rs, rs_cols, height=460)

    # =====================================================================
    # DO NOT CHASE (strong but overextended - bad fresh entry)
    # =====================================================================
    with T["Do Not Chase"]:
        st.warning("These can be good stocks, but they are OVEREXTENDED right now - "
                   "a fresh entry has poor risk-reward. Wait for the suggested condition.")
        if allstocks.empty or "Overextended" not in allstocks:
            st.info("Run a scan to view this list.")
        else:
            nc = allstocks[allstocks["Overextended"] == "Yes"].copy()
            if nc.empty:
                st.success("No overextended stocks right now.")
            else:
                nc = nc.sort_values("Composite Score", ascending=False)
                st.plotly_chart(px.scatter(
                    nc, x="Distance from 20 DMA %", y="Distance from 200 DMA %",
                    size="Composite Score", color="Classification", color_discrete_map=CLASS_COLORS,
                    hover_name="Symbol", title="How extended? (further right/up = more stretched)",
                    size_max=26), use_container_width=True)
                nc_cols = ["Symbol", "Company", "Sector", "Classification", "CMP",
                           "Distance from 20 DMA %", "Distance from 50 DMA %",
                           "Distance from 200 DMA %", "RSI 14", "Gap Up %", "Risk Reward",
                           "No Chase Reason", "Wait Condition", "Composite Score"]
                st.dataframe(nc[[c for c in nc_cols if c in nc.columns]],
                             use_container_width=True, height=440)

    # =====================================================================
    # COILED / READY (range contraction before a breakout)
    # =====================================================================
    with T["Coiled / Ready"]:
        st.info("Preparing. Do not enter until breakout with volume.")
        st.caption("Tight range + ATR contraction + volume dry-up while holding above "
                   "50/200 DMA and near the 52W high. These are 'spring-loading'.")
        if coiled is None or coiled.empty:
            st.info("No coiled / tight setups with current settings.")
        else:
            cdf = coiled.copy()
            cdf["Distance to Trigger %"] = ((cdf["Trigger Price"] / cdf["CMP"] - 1) * 100).round(2)
            stock_cards(cdf, 5, "#6a1b9a", [
                ("CMP", "CMP"), ("Coiled", "Coiled Score"), ("RS", "RS Score"),
                ("ATR Contr", "ATR Contraction"), ("Vol Dryup", "Volume Dryup 10D"),
                ("To 52WH %", "Distance from 52W High %"), ("Trigger", "Trigger Price")])
            st.write("")
            gc = st.columns(2)
            gc[0].plotly_chart(px.bar(cdf.sort_values("Coiled Score").tail(20),
                                      x="Coiled Score", y="Symbol", orientation="h",
                                      title="Tightest coiled setups", color="Coiled Score",
                                      color_continuous_scale="Purples"), use_container_width=True)
            near = cdf.sort_values("Distance to Trigger %").head(15)
            gc[1].plotly_chart(px.bar(near, x="Distance to Trigger %", y="Symbol", orientation="h",
                                      title="Closest to breakout trigger",
                                      color="Distance to Trigger %",
                                      color_continuous_scale="Purples_r"), use_container_width=True)
            ccols = ["Symbol", "Company", "Sector", "CMP", "Coiled Score", "ATR Contraction",
                     "Volume Dryup 10D", "Range 10D %", "Distance from 52W High %",
                     "Trigger Price", "Distance to Trigger %", "RS Score", "Risk Level"]
            df_with_links(cdf, ccols, height=420)

    # =====================================================================
    # FRESH MOMENTUM (new ignition, may have skipped the 200 DMA retest)
    # =====================================================================
    with T["Fresh Momentum"]:
        st.success("Fresh momentum. Prefer entry on a small pullback or breakout sustain.")
        st.caption("Close > 20 > 50 > 200 DMA (rising), volume expansion, RSI 55-72, "
                   "ADX confirming, at/near a 20-day high, RS Score >= 70.")
        if fresh is None or fresh.empty:
            st.info("No fresh momentum candidates with current settings.")
        else:
            stock_cards(fresh, 5, "#00897b", [
                ("CMP", "CMP"), ("Fresh", "Fresh Momentum Score"), ("RSI", "RSI 14"),
                ("ADX", "ADX 14"), ("Vol", "Volume Ratio"), ("20D High", "20D High"),
                ("RS", "RS Score"), ("Risk", "Risk Level")])
            st.write("")
            st.plotly_chart(px.bar(fresh.sort_values("Fresh Momentum Score").tail(20),
                                   x="Fresh Momentum Score", y="Symbol", orientation="h",
                                   title="Top fresh momentum candidates",
                                   color="Fresh Momentum Score", color_continuous_scale="Teal"),
                            use_container_width=True)
            fcols = ["Symbol", "Company", "Sector", "CMP", "Fresh Momentum Score", "RSI 14",
                     "ADX 14", "Volume Ratio", "20D High", "RS Score", "Composite Score", "Risk Level"]
            df_with_links(fresh, fcols, height=420)

    # =====================================================================
    # 6) MOMENTUM MAP
    # =====================================================================
    with T["Momentum Map"]:
        if allc.empty:
            st.info("Run a scan that produces classified stocks to view maps.")
        else:
            st.plotly_chart(px.scatter(
                allc, x="Relative Strength %", y="Score", size="Volume Ratio",
                color="Classification", color_discrete_map=CLASS_COLORS, hover_name="Symbol",
                hover_data=["Company", "Sector", "RSI 14", "ADX 14",
                            "Distance from 52W High %", "Risk Level"],
                title="Momentum vs Strength (bubble = volume)", size_max=28),
                use_container_width=True)
            st.plotly_chart(px.scatter(
                allc, x="Distance from 52W High %", y="Volume Ratio", size="Score",
                color="Classification", color_discrete_map=CLASS_COLORS, hover_name="Symbol",
                title="Breakout readiness (closer to 0 on X = nearer 52W high)", size_max=28),
                use_container_width=True)
            # Overextension
            overext = allc[(allc["Distance from 20 DMA %"] > 10) |
                           (allc["Distance from 200 DMA %"] > 40)].copy()
            st.subheader("Overextended - avoid chasing")
            if overext.empty:
                st.success("No overextended stocks among classified names.")
            else:
                st.dataframe(overext[["Symbol", "Company", "Classification", "CMP",
                                      "Distance from 20 DMA %", "Distance from 200 DMA %",
                                      "Score", "Risk Level"]],
                             use_container_width=True, height=300)

    # =====================================================================
    # 7) STOCK DEEP DIVE
    # =====================================================================
    with T["Stock Deep Dive"]:
        dd_src = allstocks if not allstocks.empty else allc
        if dd_src.empty:
            st.info("Run a scan to deep-dive a stock.")
        else:
            pick = st.selectbox("Select a stock", dd_src["Symbol"].tolist())
            r = dd_src[dd_src["Symbol"] == pick].iloc[0]
            cls = r["Classification"]
            left, right = st.columns([1.2, 1])
            with left:
                mclass = r.get("Momentum Class", cls)
                st.markdown(
                    f"### {r['Symbol']} — {r['Company']}\n"
                    f"{badge(mclass, CLASS_COLORS.get(cls, '#1f4e79'))} &nbsp; "
                    f"{badge(r['Risk Level'], RISK_COLORS.get(r['Risk Level'], '#555'))}",
                    unsafe_allow_html=True)
                st.write(
                    f"**Sector:** {r['Sector']} (rank {r.get('Sector Rank', '-')}, "
                    f"{r.get('Sector Status', '-')})  |  **Composite:** {r.get('Composite Score', '-')}  "
                    f"|  **Old Score:** {r['Score']}  |  **RS Score:** {r.get('RS Score', '-')}  "
                    f"|  **Breakout Quality:** {r.get('Breakout Quality', '-')} "
                    f"({r.get('Breakout Quality Status', '-')})  |  "
                    f"**Pullback:** {r.get('Pullback Type', '-')} "
                    f"(quality {r.get('Pullback Quality', '-')})")
                # Decision box: Do Not Chase > Coiled > Fresh > Momentum Class.
                if r.get("Overextended") == "Yes":
                    st.error(f"Good stock may be overextended. Avoid fresh entry now. "
                             f"{r.get('Wait Condition', '')}")
                elif r.get("Coiled Ready") == "Yes":
                    st.warning("Coiled / Ready: preparing. Wait for breakout with volume.")
                elif r.get("Fresh Momentum") == "Yes":
                    st.success("Fresh momentum starting. Prefer small pullback or breakout sustain.")
                else:
                    msg = {"Elite Momentum":
                           ("success", "Best quality momentum candidate. Still confirm chart/news."),
                           "Actionable Breakout":
                           ("success", "Can be considered after manual confirmation."),
                           "Wait for Confirmation":
                           ("warning", "Set alert. Do not enter yet."),
                           "Early Watchlist": ("info", "Observe only.")}.get(
                               mclass, ("error", "Avoid for now."))
                    getattr(st, msg[0])(msg[1])
            with right:
                # Main gauge = Composite Momentum Score
                st.plotly_chart(score_gauge(r.get("Composite Score", r["Score"])),
                                use_container_width=True)
            # Score breakdown bar (each sub-score normalised to 0-100)
            breakdown = pd.DataFrame({
                "Component": ["Trend", "RS", "Sector", "Breakout Quality", "Pullback Quality", "Risk"],
                "Score": [safe_num(r.get("Trend Score")) * 4, safe_num(r.get("RS Score")),
                          safe_num(r.get("Sector Strength Score")), safe_num(r.get("Breakout Quality")),
                          safe_num(r.get("Pullback Quality")),
                          safe_num(r.get("Risk Score")) * 100 / 15]})
            st.plotly_chart(px.bar(breakdown, x="Score", y="Component", orientation="h",
                                   range_x=[0, 100], title="Score breakdown (0-100 each)",
                                   color="Score", color_continuous_scale="RdYlGn"),
                            use_container_width=True)
            # Indicator cards
            ic = st.columns(7)
            for col, lbl, key in zip(ic,
                ["RSI", "ADX", "Vol Ratio", "Rel Str %", "Dist 52WH %", "Dist 200 %", "Risk/Reward"],
                ["RSI 14", "ADX 14", "Volume Ratio", "Relative Strength %",
                 "Distance from 52W High %", "Distance from 200 DMA %", "Risk Reward"]):
                metric_card(col, lbl, r.get(key, "-"), "#37474f")
            st.write(f"Trigger: {r['Trigger Price']} | Alert: {r['Suggested Alert Price']} "
                     f"| Invalidation/SL: {r['Invalidation Level']}")
            make_stock_chart(f"{pick}.NS", period, trigger=r.get("Trigger Price"),
                             invalidation=r.get("Invalidation Level"))

            # --- Fundamentals from Screener.in (on demand, for this one stock) ---
            st.markdown(f"#### Fundamentals "
                        f"&nbsp;[Open on Screener.in &#128279;]({fundamentals.screener_url(pick)})")
            with st.expander("Load key fundamentals from Screener.in", expanded=False):
                if st.button("Fetch fundamentals", key=f"fund_{pick}"):
                    with st.spinner("Fetching from Screener.in ..."):
                        fund = cached_fundamentals(pick)
                    if not fund:
                        st.info("Fundamentals unavailable (Screener may be blocking this "
                                "server, or the symbol differs on Screener). Use the link above.")
                    else:
                        # Show the headline ratios as cards, rest as a small table.
                        keys = [k for k in fund if k != "_url"]
                        headline = [k for k in ["Market Cap", "Current Price", "Stock P/E",
                                                "Book Value", "ROCE", "ROE", "Dividend Yield",
                                                "Face Value"] if k in fund]
                        fcols = st.columns(min(4, max(1, len(headline))))
                        for j, k in enumerate(headline):
                            metric_card(fcols[j % len(fcols)], k, fund[k], "#37474f")
                        st.dataframe(pd.DataFrame(
                            [{"Ratio": k, "Value": fund[k]} for k in keys]),
                            use_container_width=True, hide_index=True)

    # =====================================================================
    # 8) REJECTED / FAILED
    # =====================================================================
    with T["Rejected / Failed"]:
        if rejected is not None and not rejected.empty and "Reason" in rejected:
            rc = rejected["Reason"].value_counts().reset_index()
            rc.columns = ["Reason", "Count"]
            st.plotly_chart(px.bar(rc, x="Count", y="Reason", orientation="h",
                                   title="Why stocks were rejected",
                                   color_discrete_sequence=["#8b1e1e"]), use_container_width=True)
            with st.expander("Rejected table"):
                st.dataframe(rejected, use_container_width=True, height=400)
        else:
            st.info("No rejected stocks.")
        st.subheader("Failed tickers (download error / no data)")
        if failed:
            st.dataframe(pd.DataFrame({"Failed Tickers": failed}), use_container_width=True, height=240)
        else:
            st.success("No failed tickers.")

    # =====================================================================
    # 9) CLAUDE REVIEW
    # =====================================================================
    with T["Claude Review"]:
        st.caption("Click the copy icon at the top-right of each box, then paste into "
                   "Claude or ChatGPT.")
        do_not_chase = (allstocks[allstocks.get("Overextended") == "Yes"]
                        if not allstocks.empty and "Overextended" in allstocks else pd.DataFrame())
        st.subheader("1. Elite / Actionable Breakout")
        st.code(scanner.build_strong_prompt(strong), language="text")
        st.subheader("2. Wait for Confirmation")
        st.code(scanner.build_wait_prompt(wait), language="text")
        st.subheader("3. Coiled / Ready")
        st.code(scanner.build_coiled_prompt(coiled), language="text")
        st.subheader("4. Fresh Momentum")
        st.code(scanner.build_fresh_prompt(fresh), language="text")
        st.subheader("5. Do Not Chase")
        st.code(scanner.build_donotchase_prompt(do_not_chase), language="text")

    # =====================================================================
    # 10) EXPORT
    # =====================================================================
    with T["Export"]:
        st.subheader("Export results")
        overext = allc[(allc["Distance from 20 DMA %"] > 10) |
                       (allc["Distance from 200 DMA %"] > 40)].copy() if not allc.empty else pd.DataFrame()
        cexp = st.columns(2)
        if cexp[0].button("Save full Excel + CSVs"):
            try:
                p = export_outputs(result)
                st.success(f"Saved: {p} (+ CSV files in outputs/)")
            except Exception as e:
                st.error(f"Excel export failed: {e}. Use the CSV download buttons below instead.")
        if cexp[1].button("Save dashboard_summary.xlsx"):
            try:
                p = export_dashboard_summary(result, overext)
                st.success(f"Saved: {p}")
            except Exception as e:
                st.error(f"Export failed: {e}. Use the CSV download buttons below instead.")
        st.caption("On Streamlit Cloud the outputs/ folder is temporary - use the "
                   "download buttons below to save to your computer.")
        for label, df, fname in [
            ("Strong Breakout CSV", strong, "strong_breakout.csv"),
            ("Wait for Confirmation CSV", wait, "wait_for_confirmation.csv"),
            ("Coiled / Ready CSV", coiled, "coiled_ready.csv"),
            ("Fresh Momentum CSV", fresh, "fresh_momentum.csv"),
            ("Early Watchlist CSV", watch, "early_watchlist.csv"),
            ("Rejected CSV", rejected, "rejected_stocks.csv")]:
            if df is not None and not df.empty:
                st.download_button(label, df.to_csv(index=False).encode("utf-8"),
                                   file_name=fname, mime="text/csv", key=fname)
else:
    st.title("NSE Momentum Breakout Dashboard")
    st.info("Set your options in the sidebar and click **Run Scan** to begin.")
