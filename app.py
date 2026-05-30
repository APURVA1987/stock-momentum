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
import holdings as H
import backtest as BT
import fundamentals


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUTS_DIR = os.path.join(BASE_DIR, "outputs")
DEFAULT_UNIVERSE = os.path.join(BASE_DIR, "universe.csv")
DATA_DIR = os.path.join(BASE_DIR, "data")
HOLDINGS_PATH = os.path.join(DATA_DIR, "holdings_latest.xlsx")
FUND_PATH = os.path.join(DATA_DIR, "fundamentals.csv")   # bulk fundamentals (v2 Phase 2)
NSE_DEFAULT_PATHS = {                                     # Persistent NSE constituent files
    "Large Cap": os.path.join(DATA_DIR, "nse_large.csv"),
    "Mid Cap":   os.path.join(DATA_DIR, "nse_mid.csv"),
    "Small Cap": os.path.join(DATA_DIR, "nse_small.csv")}
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


# st.fragment isolates dropdown-driven sections (Stock / Holding / Value Deep
# Dive) so changing the selected stock re-runs ONLY that block - the active
# tab and scroll position are preserved. Falls back to a no-op decorator on
# older Streamlit versions.
_fragment = (getattr(st, "fragment", None)
             or getattr(st, "experimental_fragment", None)
             or (lambda f: f))


def _holdings_authed() -> bool:
    """Holdings stay private unless the visitor enters the access password
    configured in `st.secrets["APP_PASSWORD"]`. If no password is set in
    secrets (e.g. running locally), access is allowed by default so the owner
    has zero-friction use of their own machine."""
    if st.session_state.get("holdings_auth"):
        return True
    pw_required = ""
    try:
        pw_required = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        pw_required = ""
    if not pw_required:
        st.session_state["holdings_auth"] = True
        return True
    return False


def _save_default_upload(uploaded, path: str) -> bool:
    """Persist any st.file_uploader file to `path`. Returns True on success."""
    if uploaded is None:
        return False
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(uploaded.getvalue())
        return True
    except Exception:
        return False

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
# Wider min-widths for the identifier / status columns so they never collapse
# to 2-letter slivers like "AL". The rest size to their content naturally
# (with use_container_width=False the user can scroll horizontally like Excel).
SCREENER_COLCFG = {
    "Screener":              st.column_config.LinkColumn("Screener", display_text="open"),
    "Symbol":                st.column_config.TextColumn("Symbol", width="medium"),
    "symbol":                st.column_config.TextColumn("symbol", width="medium"),
    "Company":               st.column_config.TextColumn("Company", width="large"),
    "company":               st.column_config.TextColumn("company", width="large"),
    "Sector":                st.column_config.TextColumn("Sector", width="medium"),
    "Classification":        st.column_config.TextColumn("Classification", width="medium"),
    "Value Classification":  st.column_config.TextColumn("Value Classification", width="medium"),
    "Final Remark":          st.column_config.TextColumn("Final Remark", width="large"),
    "holding_action":        st.column_config.TextColumn("Action", width="medium"),
    "holding_remark":        st.column_config.TextColumn("Remark", width="large"),
    "Confirmation Needed":   st.column_config.TextColumn("Confirmation Needed", width="large"),
    "Stop Loss":             st.column_config.TextColumn("Stop Loss", width="large"),
    "Target 1":              st.column_config.TextColumn("Target 1", width="medium"),
    "Target 2":              st.column_config.TextColumn("Target 2", width="medium"),
}


def df_with_links(df: pd.DataFrame, cols, height=420):
    """Show a table with a clickable Screener link as the first column.

    Uses natural column widths (use_container_width=False) so the Symbol /
    Company columns never get squished. The user can scroll horizontally
    inside the table to see all columns - the Excel experience they expect.
    """
    if df is None or df.empty:
        st.info("No rows.")
        return
    d = df.copy()
    d["Screener"] = d["Symbol"].map(fundamentals.screener_url)
    show = ["Screener"] + [c for c in cols if c in d.columns]
    st.dataframe(d[show], use_container_width=False, height=height, column_config=SCREENER_COLCFG)


# Compact summary columns shown in the "first" table everywhere (<= 11 cols so
# there is little/no horizontal scrolling). The full wide table goes in an
# expander underneath.
SUMMARY_COLS = ["Symbol", "Company", "CMP", "Classification", "Composite Score",
                "RS Score", "RSI 14", "Volume Ratio", "Trigger Price",
                "Risk Level", "Final Remark"]


def summary_table(df, key, title, caption="", detail_cols=None,
                  default_sort="Composite Score"):
    """Graphical-dashboard table block used by the table-heavy tabs:

      - heading + caption ABOVE the table (never below)
      - filter controls (search, classification, row count) ABOVE the table
      - a COMPACT <=11-column table with a clickable Screener link
      - the full wide table inside an expander at the very bottom

    Filters live in st.session_state (keyed) so they survive reruns and never
    trigger a re-scan. Returns nothing - it renders in place.
    """
    st.subheader(title)
    if caption:
        st.caption(caption)
    if df is None or df.empty:
        st.info("No rows to show.")
        return

    d = df.copy()
    if "Sector" in d.columns:
        d["Sector"] = d["Sector"].fillna("Unknown").replace("", "Unknown")

    # --- Filter controls (above the table) ---
    fc = st.columns([2, 2, 1.2, 1.2])
    q = fc[0].text_input("Search symbol / company", key=f"{key}_q").strip().lower()
    classes = (["All"] + sorted(d["Classification"].dropna().unique().tolist())
               if "Classification" in d.columns else ["All"])
    pick_cls = fc[1].selectbox("Classification", classes, key=f"{key}_cls")
    sort_opts = [c for c in [default_sort, "RS Score", "Volume Ratio",
                             "Distance from 52W High %", "Score"] if c in d.columns]
    sort_by = fc[2].selectbox("Sort by", sort_opts or ["Symbol"], key=f"{key}_sort")
    n_choice = fc[3].selectbox("Rows", ["10", "20", "50", "All"], index=1, key=f"{key}_n")

    if q:
        mask = d["Symbol"].astype(str).str.lower().str.contains(q)
        if "Company" in d.columns:
            mask = mask | d["Company"].astype(str).str.lower().str.contains(q)
        d = d[mask]
    if pick_cls != "All" and "Classification" in d.columns:
        d = d[d["Classification"] == pick_cls]
    if sort_by in d.columns:
        asc = sort_by == "Distance from 52W High %"
        d = d.sort_values(sort_by, ascending=asc)
    if n_choice != "All":
        d = d.head(int(n_choice))

    st.caption(f"Showing {len(d)} of {len(df)} stocks.")
    # Compact table first
    compact = [c for c in SUMMARY_COLS if c in d.columns]
    df_with_links(d, compact, height=min(460, 80 + 36 * min(len(d), 12)))
    # Full wide table in an expander
    full = detail_cols or list(df.columns)
    with st.expander("Show detailed full table"):
        df_with_links(d, [c for c in full if c in d.columns], height=480)


def parse_nse_constituent(file, cap_label: str) -> pd.DataFrame:
    """Parse an NSE / niftyindices.com constituent CSV (e.g. ind_nifty100list.csv)
    into our 4-column universe schema. The file's typical columns are:
        Company Name, Industry, Symbol, Series, ISIN Code
    We keep only Series == 'EQ' rows. `cap_label` becomes market_cap_category."""
    try:
        df = pd.read_csv(file)
    except Exception:
        return pd.DataFrame()
    df.columns = [c.strip() for c in df.columns]
    cmap = {c.lower(): c for c in df.columns}
    sym = cmap.get("symbol")
    if not sym:
        return pd.DataFrame()
    name = cmap.get("company name") or cmap.get("companyname") or sym
    ind = cmap.get("industry") or cmap.get("sector")
    series = cmap.get("series")
    if series:
        df = df[df[series].astype(str).str.strip().str.upper() == "EQ"]
    out = pd.DataFrame({
        "symbol": df[sym].astype(str).str.strip().str.upper(),
        "company": (df[name].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
                    .str.rstrip(".") if name in df.columns else df[sym]),
        "sector": df[ind].astype(str).str.strip() if (ind and ind in df.columns) else "-",
        "market_cap_category": cap_label,
    })
    # Drop placeholder/demerger stub symbols (e.g. DUMMYVEDL1) - they have no
    # Yahoo data and just clutter the "Failed Tickers" list.
    out = out[~out["symbol"].astype(str).str.upper().str.startswith("DUMMY")]
    return out[out["symbol"].astype(str).str.len() > 0].reset_index(drop=True)


def load_universe(uploaded_file, nse_files=None) -> pd.DataFrame:
    """Load the universe. Priority:
       1. NSE constituent CSVs (one per cap tier) if any were uploaded.
       2. Legacy single 4-column CSV upload.
       3. Default universe.csv in this folder.
    """
    required = {"symbol", "company", "sector", "market_cap_category"}
    # 1. NSE constituent files (one per cap tier).
    if nse_files:
        parts = [parse_nse_constituent(f, cap) for f, cap in nse_files if f is not None]
        parts = [p for p in parts if not p.empty]
        if parts:
            df = pd.concat(parts, ignore_index=True)
            df = df.drop_duplicates(subset="symbol", keep="first").reset_index(drop=True)
            return df
    # 2. Legacy single-file upload or 3. default.
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

# Drop in NSE / niftyindices.com constituent files (one per cap tier). The app
# auto-maps Symbol / Company Name / Industry and filters Series == EQ. If any
# of these slots is filled, it OVERRIDES the universe.csv / single-file upload.
with st.sidebar.expander("Or: upload NSE index CSVs (one per cap tier)"):
    st.caption("Drop the ind_nifty100list / ind_niftymidcap150list / "
               "ind_niftysmallcap250list CSVs from niftyindices.com here. "
               "Files are saved as defaults and re-used on the next session.")
    nse_large = st.file_uploader("Large Cap file", type="csv", key="nse_large")
    nse_mid = st.file_uploader("Mid Cap file", type="csv", key="nse_mid")
    nse_small = st.file_uploader("Small Cap file", type="csv", key="nse_small")
    # Persist any fresh upload to data/ and report which slot is currently in use.
    for upl, cap in [(nse_large, "Large Cap"), (nse_mid, "Mid Cap"), (nse_small, "Small Cap")]:
        if upl is not None and _save_default_upload(upl, NSE_DEFAULT_PATHS[cap]):
            st.caption(f"Saved as default -> {os.path.basename(NSE_DEFAULT_PATHS[cap])}")
    _saved_nse = [cap for cap, p in NSE_DEFAULT_PATHS.items() if os.path.exists(p)]
    for cap in _saved_nse:
        st.caption(f"Using saved {cap}: {os.path.basename(NSE_DEFAULT_PATHS[cap])}")
    if _saved_nse:
        st.caption("These saved files OVERRIDE the built-in universe.csv. Clear "
                   "them to go back to the full universe.csv list.")
        if st.button("Clear saved NSE files (use universe.csv)", key="clear_nse"):
            for cap in list(NSE_DEFAULT_PATHS):
                try:
                    if os.path.exists(NSE_DEFAULT_PATHS[cap]):
                        os.remove(NSE_DEFAULT_PATHS[cap])
                except Exception:
                    pass
            st.success("Cleared. The next scan uses the full universe.csv. "
                       "Re-run the scan.")
            st.rerun()


def _nse_slot(uploaded, cap):
    """Use a fresh upload if provided; otherwise fall back to the saved default."""
    if uploaded is not None:
        return uploaded
    p = NSE_DEFAULT_PATHS[cap]
    return p if os.path.exists(p) else None


NSE_FILES = [(_nse_slot(nse_large, "Large Cap"), "Large Cap"),
             (_nse_slot(nse_mid, "Mid Cap"), "Mid Cap"),
             (_nse_slot(nse_small, "Small Cap"), "Small Cap")]

# --- My Holdings (Zerodha) - private; needs password if APP_PASSWORD is set ---
# The holdings file is saved as the default for next time. The whole holdings
# overlay (load + combine + display + export + Claude prompt) is gated by the
# password so anyone with the URL can use the scanner but only the owner sees
# the portfolio.
with st.sidebar.expander("My Holdings (Zerodha)"):
    # Password gate (no-op if APP_PASSWORD secret is empty - local single-user use).
    try:
        _pw_set = bool(st.secrets.get("APP_PASSWORD", ""))
    except Exception:
        _pw_set = False
    if _pw_set and not st.session_state.get("holdings_auth"):
        pw_try = st.text_input("Holdings access password", type="password", key="hold_pw")
        if pw_try:
            try:
                if pw_try == st.secrets.get("APP_PASSWORD", ""):
                    st.session_state["holdings_auth"] = True
                    st.success("Unlocked.")
                else:
                    st.error("Wrong password.")
            except Exception:
                st.error("Could not read APP_PASSWORD from secrets.")
    if _holdings_authed():
        fhold = st.file_uploader("Upload holdings (.xlsx / .xls / .csv)",
                                 type=["xlsx", "xls", "csv"], key="zhold")
        if fhold is not None:
            ext = os.path.splitext(fhold.name)[1].lower() or ".xlsx"
            save_path = os.path.join(DATA_DIR, "holdings_latest" + ext)
            if H.save_persistent(fhold, save_path):
                st.session_state["holdings_path"] = save_path
                st.success(f"Saved as default -> {os.path.basename(save_path)}")
        saved = st.session_state.get("holdings_path") or (
            HOLDINGS_PATH if os.path.exists(HOLDINGS_PATH) else
            next((os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR)
                  if f.startswith("holdings_latest")), None)
            if os.path.isdir(DATA_DIR) else None)
        if saved and os.path.exists(saved):
            st.caption(f"Using saved holdings: {os.path.basename(saved)}")
    else:
        st.caption("Locked. Enter the password to load/upload holdings.")

# Load + normalise the saved holdings ONLY if the visitor is authenticated.
holdings_norm = pd.DataFrame()
if _holdings_authed():
    _saved = st.session_state.get("holdings_path")
    if not _saved:
        for ext in (".xlsx", ".xls", ".csv"):
            p = os.path.join(DATA_DIR, "holdings_latest" + ext)
            if os.path.exists(p):
                _saved = p
                break
    if _saved and os.path.exists(_saved):
        holdings_norm = H.normalise_holdings(H.load_persistent(_saved))
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
eod_only = st.sidebar.checkbox(
    "End-of-day data only (drop intraday partial bar)", value=True,
    help="During NSE market hours (9:15-15:30 IST) Yahoo returns a PARTIAL bar "
         "for today: Close = current LTP and Volume = only what has traded so "
         "far. That makes Volume Ratio collapse (~0.2x at 11 AM) and demotes "
         "real breakouts to Wait/Rejected. With this ON, the partial bar is "
         "stripped so a 10 AM scan gives the SAME results as a post-close "
         "scan. Recommended ON.")
# Show a live notice when the market is currently open.
if scanner._is_nse_market_hours_ist():
    if eod_only:
        st.sidebar.info("Market is OPEN now. Today's partial candle will be "
                        "stripped automatically; scan uses up to last close.")
    else:
        st.sidebar.warning("Market is OPEN. Volume/breakout signals will be "
                           "understated because today's bar is partial.")
# --- Fundamentals (v2 Phase 2): bulk CSV keyed by symbol -----------------------
FUND_YF_CACHE = os.path.join(DATA_DIR, "fundamentals_yf_cache.pkl")
FUND_YF_CSV = os.path.join(DATA_DIR, "fundamentals_yahoo.csv")
with st.sidebar.expander("Fundamentals (optional)"):
    st.caption("Two ways to feed the Value scan:")
    st.markdown("**A. Auto from Yahoo (free, cloud-safe)**")
    st.caption("Builds fundamentals for the whole universe from yfinance. "
               "Covers ROE / margins / D-E / growth / P/E / P/B / PEG. Missing: "
               "promoter holding & pledge (Yahoo has no India governance data), so "
               "scores are PARTIAL and full 'Compounder' status needs option B.")
    auto_yf = st.checkbox("Use Yahoo auto-fundamentals", value=False, key="auto_yf")
    if st.button("Fetch / refresh Yahoo fundamentals now", key="fetch_yf"):
        uni_tmp = load_universe(uploaded, NSE_FILES)
        syms = set(uni_tmp["symbol"].astype(str).str.upper().unique()) if not uni_tmp.empty else set()
        # ALWAYS include holdings symbols so the portfolio gets a value assessment,
        # even for stocks outside the scan universe.
        if holdings_norm is not None and not holdings_norm.empty:
            syms |= set(holdings_norm["symbol"].astype(str).str.upper().unique())
        syms = sorted(syms)
        if not syms:
            st.warning("No universe / holdings to fetch. Add a universe or holdings file.")
        else:
            pbar = st.progress(0.0); ptxt = st.empty()
            def _fp(d, t, s): pbar.progress(d / t); ptxt.write(f"{d}/{t}: {s}")
            with st.spinner(f"Fetching Yahoo fundamentals for {len(syms)} stocks "
                            "(cached; first run is slow) ..."):
                got = fundamentals.fetch_fundamentals_yf(
                    syms, cache_path=FUND_YF_CACHE, progress=_fp)
            pbar.empty(); ptxt.empty()
            st.session_state["fund_yf"] = got
            # Persist EVERYTHING fetched so far (cache accumulates) into a CSV
            # the user can download and re-upload after a reboot.
            full = fundamentals.load_yf_cache(FUND_YF_CACHE)
            n = fundamentals.write_fundamentals_csv(full, FUND_YF_CSV)
            st.success(f"Yahoo fundamentals ready for {len(got)} stocks "
                       f"(saved file now holds {n} total).")
    # Download the accumulated Yahoo fundamentals CSV (survives reboot via re-upload)
    if os.path.exists(FUND_YF_CSV):
        with open(FUND_YF_CSV, "rb") as _fh:
            st.download_button("Download Yahoo fundamentals CSV", _fh.read(),
                               file_name="fundamentals_yahoo.csv", mime="text/csv",
                               key="dl_yf_csv",
                               help="Save this. After a reboot, upload it under "
                                    "option B to skip re-fetching.")
    st.markdown("**B. Upload Screener CSV (most complete)**")
    st.caption("Bulk CSV keyed by `symbol` (ROCE, ROE, Profit/Sales Growth, "
               "Debt to Equity, Promoter Holding, Pledge, P/E, PEG). Headers "
               "auto-matched. Overrides/complements option A.")
    ffile = st.file_uploader("Upload fundamentals.csv", type=["csv"], key="fund_csv")
    if ffile is not None and _save_default_upload(ffile, FUND_PATH):
        st.success("Saved as default -> fundamentals.csv")
    if os.path.exists(FUND_PATH):
        st.caption("Using saved fundamentals.csv")
momentum_quality_gate = st.sidebar.checkbox(
    "Momentum quality gate (demote weak-fundamental breakouts)", value=False,
    help="Section 5A. When ON, a Strong Breakout in a business with Quality "
         "Score < 40 is demoted to Wait for Confirmation. Needs fundamentals.")
# Build the fundamentals dict: CSV (option B) merged over Yahoo (option A).
fundamentals_data = {}
if st.session_state.get("auto_yf"):
    fundamentals_data.update(st.session_state.get("fund_yf") or {})
    if not fundamentals_data:
        fundamentals_data.update(fundamentals.load_yf_cache(FUND_YF_CACHE))
if os.path.exists(FUND_PATH):
    csv_fund = fundamentals.load_fundamentals(FUND_PATH)
    for sym, rec in csv_fund.items():           # CSV wins on overlap
        fundamentals_data[sym] = {**fundamentals_data.get(sym, {}), **rec}
if fundamentals_data:
    st.sidebar.caption(f"Fundamentals loaded for {len(fundamentals_data)} symbols.")

scan_focus = st.sidebar.selectbox(
    "Scan focus", ["All (Momentum + Value)", "Momentum only", "Value only"],
    index=0, help="Filters which tabs are shown to reduce on-screen clutter. "
                  "Scan time is unchanged - all signals are still computed.")
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
    universe = load_universe(uploaded, NSE_FILES)
    if universe.empty and (holdings_norm is None or holdings_norm.empty):
        st.stop()
    universe = filter_by_cap(universe, cap_choice) if not universe.empty else universe
    # Always include holding symbols in the scan, even if they are outside the
    # selected universe / cap filter (Universe + Holding overlay).
    universe = H.combine_universe_holdings(universe, holdings_norm)
    if universe.empty:
        st.warning("No stocks to scan (empty universe and no holdings).")
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
        local_mode=bool(local_mode), eod_only=bool(eod_only),
        fundamentals=fundamentals_data,
        momentum_quality_gate=bool(momentum_quality_gate),
        progress_callback=on_progress,
    )
    progress.empty()
    status.empty()
    st.session_state["result"] = result
    st.session_state["period"] = period
    # Keep the in-memory OHLCV cache so the Deep-Dive chart never re-downloads.
    st.session_state["price_data"] = result.get("price_data") or {}
    # Build the holdings-vs-momentum overlay (re-used by the My Holdings tab).
    st.session_state["holdings_df"] = (
        H.merge_with_scan(holdings_norm, result.get("all_stocks"))
        if holdings_norm is not None and not holdings_norm.empty else pd.DataFrame())


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
    and forces a visible active sheet before save - this avoids the
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


def export_outputs(result, holdings_df=None):
    strong, wait = result["strong"], result["wait"]
    watch, rejected = result["watchlist"], result["rejected"]
    sector, ctx = result["sector_strength"], result["nifty_context"]
    sector_rot = result.get("sector_rotation", pd.DataFrame())
    allst = result.get("all_stocks", pd.DataFrame())
    coiled, fresh = result.get("coiled", pd.DataFrame()), result.get("fresh", pd.DataFrame())
    spring_x = result.get("spring", pd.DataFrame())
    vq_x = result.get("value_quality", pd.DataFrame())
    xover_x = result.get("crossover", pd.DataFrame())

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

    # Phase 2 value-scanner derived frames
    def _vsel(cls):
        if allst is None or allst.empty or "Value Classification" not in allst:
            return pd.DataFrame()
        out = allst[allst["Value Classification"] == cls]
        return out.sort_values("Value Score", ascending=False) if "Value Score" in out else out
    val_reversal_x = _vsel("Value Reversal Ready")
    val_base_x = _vsel("Value Base Forming")
    val_deep_x = _vsel("Deep Value High Risk")
    val_trap_x = _vsel("Value Trap Avoid")
    matrix_x = (allst.sort_values(["Composite Score", "Value Score"], ascending=[False, False])
                if (allst is not None and not allst.empty and "Matrix Class" in allst)
                else pd.DataFrame())

    sheets = {
        "Elite_Momentum": elite, "Actionable_Breakout": actionable,
        "Strong_Breakout": strong, "Wait_For_Confirmation": wait,
        "Spring_PreBreakout": spring_x,
        "Value_Quality_Growth": vq_x, "Crossover_Buy": xover_x,
        "Coiled_Ready": coiled, "Fresh_Momentum": fresh, "Early_Watchlist": watch,
        "RS_Leaders": rs_leaders, "Sector_Rotation": sector_rot,
        "Do_Not_Chase": do_not_chase, "Rejected": rejected,
        "Value_Reversal_Ready": val_reversal_x, "Value_Base_Forming": val_base_x,
        "Deep_Value_High_Risk": val_deep_x, "Value_Trap_Avoid": val_trap_x,
        "Momentum_Value_Matrix": matrix_x,
        "Failed_Tickers": pd.DataFrame({"Failed Tickers": result["failed"]}),
        "Sector_Strength": sector, "Market_Regime": market, "Claude_Review": claude}
    # Holdings sheets (added only if a holdings file was provided this run)
    if holdings_df is not None and not holdings_df.empty:
        sheets.update({
            "My_Holdings_All": holdings_df,
            "Holdings_In_Momentum": holdings_df[holdings_df["holding_action"].isin(
                ["Hold / Trail", "Add on Pullback"])],
            "Holdings_Wait_For_Confirmation": holdings_df[holdings_df["holding_action"]
                                                          == "Hold, Set Alert"],
            "Holdings_Weak_Exit_Review": holdings_df[holdings_df["holding_action"].isin(
                ["Review / Reduce", "Exit Review"])],
            "Holdings_Do_Not_Chase": holdings_df[holdings_df["holding_action"]
                                                 == "Do Not Add / Trail Only"],
            "Portfolio_Summary": pd.DataFrame([H.portfolio_summary(holdings_df)])})
        if "Value Classification" in holdings_df.columns:
            sheets["Holdings_Value_Recovery"] = holdings_df[
                holdings_df["Value Classification"].isin(
                    ["Value Reversal Ready", "Value Base Forming"])]
    xlsx_path = _write_workbook(os.path.join(OUTPUTS_DIR, "scanner_output.xlsx"), sheets)
    csvs = [(strong, "strong_breakout.csv"), (wait, "wait_for_confirmation.csv"),
            (spring_x, "spring_prebreakout.csv"),
            (coiled, "coiled_ready.csv"), (fresh, "fresh_momentum.csv"),
            (watch, "early_watchlist.csv"), (rs_leaders, "rs_leaders.csv"),
            (sector_rot, "sector_rotation.csv"), (do_not_chase, "do_not_chase.csv"),
            (rejected, "rejected_stocks.csv"),
            (val_reversal_x, "value_reversal_ready.csv"),
            (val_base_x, "value_base_forming.csv"),
            (matrix_x, "momentum_value_matrix.csv")]
    if holdings_df is not None and not holdings_df.empty:
        csvs += [(holdings_df, "my_holdings_all.csv"),
                 (holdings_df[holdings_df["holding_action"].isin(
                     ["Hold / Trail", "Add on Pullback"])], "holdings_in_momentum.csv"),
                 (holdings_df[holdings_df["holding_action"].isin(
                     ["Review / Reduce", "Exit Review"])], "holdings_weak_exit_review.csv")]
    for df, fn in csvs:
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
    # Prefer the OHLCV already downloaded during the scan (instant, no re-fetch).
    # That fixes the "Deep Dive goes blank when I change stock" issue, because
    # selecting a different symbol no longer triggers a network call.
    cached = st.session_state.get("price_data") or {}
    sym = symbol_ns.replace(".NS", "")
    df = cached.get(sym)
    if df is None or df.empty:
        df = cached_history(symbol_ns, period)
    if df is None or df.empty:
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
    spring = result.get("spring", pd.DataFrame())

    # Name-keyed tabs (order can change without breaking the blocks below).
    # ---- Tab visibility driven by sidebar "Scan focus" ----
    _ALL_TABS = ["My Holdings", "Crossover Buy", "Market Overview", "Sector Rotation", "RS Leaders",
                 "Strong Breakout", "Spring / Pre-Breakout", "Wait for Confirmation",
                 "Coiled / Ready", "Fresh Momentum", "Early Watchlist", "Do Not Chase",
                 "Momentum Map", "Value / Quality-Growth", "Technical Recovery",
                 "Momentum + Value Matrix",
                 "Stock Deep Dive", "Backtest", "Rejected / Failed", "Claude Review", "Export"]
    if scan_focus == "Momentum only":
        _hidden = {"Value / Quality-Growth"}
    elif scan_focus == "Value only":
        _hidden = {"Strong Breakout", "Spring / Pre-Breakout", "Wait for Confirmation",
                   "Coiled / Ready", "Fresh Momentum", "Do Not Chase", "Momentum Map",
                   "RS Leaders", "Technical Recovery", "Backtest"}
    else:
        _hidden = set()
    if not _holdings_authed():                # holdings tab vanishes if locked
        _hidden.add("My Holdings")
    tab_names = [t for t in _ALL_TABS if t not in _hidden]

    # Tab dict with a "no-op tab" fallback for hidden names.
    # When a tab is hidden, `with T["X"]:` enters a one-shot st.empty() container
    # and clears it on exit, so the existing block bodies don't need rewriting.
    class _NullTab:
        def __enter__(self):
            self._ph = st.empty()
            self._ctx = self._ph.container()
            self._ctx.__enter__()
            return self
        def __exit__(self, exc_type, exc_val, tb):
            try:
                self._ctx.__exit__(exc_type, exc_val, tb)
            finally:
                self._ph.empty()

    class _TabDict(dict):
        def __getitem__(self, k):
            return super().__getitem__(k) if k in self else _NullTab()
        def __contains__(self, k):
            return dict.__contains__(self, k)
    T = _TabDict(zip(tab_names, st.tabs(tab_names)))
    holdings_df = st.session_state.get("holdings_df", pd.DataFrame())

    # =====================================================================
    # MY HOLDINGS (Zerodha overlay on the momentum scanner)
    # =====================================================================
    with T["My Holdings"]:
        if holdings_df is None or holdings_df.empty:
            st.info("No holdings loaded yet. Upload your Zerodha holdings file "
                    "in the sidebar (under **My Holdings (Zerodha)**). It will be "
                    "saved as the default and used on every scan from then on.")
        else:
            psum = H.portfolio_summary(holdings_df)
            # Top portfolio cards (8 metrics)
            cA = st.columns(4)
            metric_card(cA[0], "Total Current Value", psum.get("Total Current Value"), "#1f4e79")
            metric_card(cA[1], "Total Invested", psum.get("Total Invested"), "#37474f")
            pnl = psum.get("Total P&L", 0)
            metric_card(cA[2], "Total P&L", pnl, "#1e7d32" if pnl >= 0 else "#8b1e1e")
            pnl_p = psum.get("Total P&L %", 0)
            metric_card(cA[3], "Total P&L %", pnl_p, "#1e7d32" if pnl_p >= 0 else "#8b1e1e")
            cB = st.columns(4)
            metric_card(cB[0], "Holdings in Momentum", psum.get("Holdings In Momentum"), CLASS_COLORS["Strong Breakout / Actionable"])
            metric_card(cB[1], "Waiting / Set Alert", psum.get("Holdings Waiting"), CLASS_COLORS["Wait for Confirmation"])
            metric_card(cB[2], "Weak / Exit Review", psum.get("Holdings Weak / Exit"), CLASS_COLORS["Rejected"])
            metric_card(cB[3], "Top Holding Weight %", psum.get("Top Holding Weight %"), "#37474f",
                        sub=f"{psum.get('Holdings Count', 0)} holdings")

            sub = st.tabs(["Portfolio Summary", "In Momentum",
                           "Waiting for Confirmation", "Weak / Exit Review",
                           "Do Not Chase", "Value Assessment", "Holding Deep Dive"])

            # Action-label colours for the sub-tab tables.
            ACT_COLORS = {
                "Hold / Trail": "#1e7d32", "Add on Pullback": "#0b6e2e",
                "Hold, Set Alert": "#e08e0b", "Do Not Add / Trail Only": "#6a1b9a",
                "Review / Reduce": "#b71c1c", "Exit Review": "#6e0b0b",
                "Watch Only": "#1f4e79", "No Scanner Data": "#555",
                "Core Compounder - Hold / Add in Zones": "#0b6e2e",
                "Fundamental + Technical Breakdown - Exit Review": "#6e0b0b"}

            def style_holdings(df):
                def row_style(row):
                    bg = ACT_COLORS.get(str(row.get("holding_action", "")), "#37474f")
                    return [f"background-color:{bg};color:white"] * len(row)
                return df.style.apply(row_style, axis=1)

            holding_cols = ["symbol", "company", "quantity", "avg_cost", "CMP", "ltp",
                            "invested", "current_value", "pnl", "pnl_pct",
                            "portfolio_weight_pct", "Classification", "Composite Score",
                            "RS Score", "Value Class", "Composite Value", "Expected CAGR %",
                            "Crossover Buy", "Sector", "Sector Status", "Breakout Status",
                            "Risk Level", "Trigger Price", "Invalidation Level",
                            "Confirmation Needed", "Pullback Type",
                            "avg_vs_cmp_pct", "avg_vs_200dma_pct", "cmp_vs_200dma_pct",
                            "holding_action", "holding_remark"]

            def show_h(df, empty_msg):
                if df is None or df.empty:
                    st.info(empty_msg)
                    return
                cols = [c for c in holding_cols if c in df.columns]
                # use_container_width=False = natural per-column widths so the
                # Symbol/Company columns are never truncated. The user scrolls
                # horizontally inside the table for the remaining columns.
                st.dataframe(style_holdings(df[cols]),
                             use_container_width=False, height=480,
                             column_config=SCREENER_COLCFG)

            # ---- A. Portfolio Summary ----
            with sub[0]:
                g = st.columns(2)
                # Allocation pie by sector
                if "Sector" in holdings_df.columns and "current_value" in holdings_df.columns:
                    sec_alloc = (holdings_df.groupby("Sector")["current_value"].sum()
                                 .sort_values(ascending=False).reset_index())
                    g[0].plotly_chart(px.pie(sec_alloc, names="Sector", values="current_value",
                                             title="Sector allocation", hole=0.45),
                                      use_container_width=True)
                # Weight bar (top 15)
                if "portfolio_weight_pct" in holdings_df.columns:
                    top_w = holdings_df.sort_values("portfolio_weight_pct", ascending=True).tail(15)
                    g[1].plotly_chart(px.bar(top_w, x="portfolio_weight_pct", y="symbol",
                                             orientation="h", title="Top weights",
                                             color="portfolio_weight_pct",
                                             color_continuous_scale="Blues"),
                                      use_container_width=True)
                # P&L bar
                if "pnl" in holdings_df.columns:
                    pdf = holdings_df.sort_values("pnl", ascending=True)
                    st.plotly_chart(px.bar(pdf, x="pnl", y="symbol", orientation="h",
                                           title="P&L by holding", color="pnl",
                                           color_continuous_scale="RdYlGn"),
                                    use_container_width=True)
                # Holding classification donut
                if "holding_action" in holdings_df.columns:
                    acts = holdings_df["holding_action"].value_counts().reset_index()
                    acts.columns = ["Action", "Count"]
                    st.plotly_chart(px.pie(acts, names="Action", values="Count",
                                           hole=0.5, title="Holdings by action label",
                                           color="Action",
                                           color_discrete_map=ACT_COLORS),
                                    use_container_width=True)
                with st.expander("All holdings (full table)"):
                    show_h(holdings_df, "No holdings.")

            # ---- B. In Momentum ----
            with sub[1]:
                st.success("Strong momentum positions. Hold / trail; add only on a "
                           "controlled pullback or breakout sustain.")
                show_h(holdings_df[holdings_df["holding_action"].isin(
                    ["Hold / Trail", "Add on Pullback"])],
                    "No holdings currently in strong momentum.")

            # ---- C. Waiting for Confirmation ----
            with sub[2]:
                st.warning("Setup developing. Hold the existing position and set "
                           "alerts near trigger price - do not add yet.")
                show_h(holdings_df[holdings_df["holding_action"] == "Hold, Set Alert"],
                       "No holdings in Wait / Coiled / Fresh state.")

            # ---- D. Weak / Exit Review ----
            with sub[3]:
                st.error("Weak technical structure. Review for reduction; avoid "
                         "averaging down until the structure improves.")
                show_h(holdings_df[holdings_df["holding_action"].isin(
                    ["Review / Reduce", "Exit Review"])],
                    "No holdings flagged Weak / Exit Review.")

            # ---- E. Do Not Chase ----
            with sub[4]:
                st.warning("Strong but overextended. Trail SL on what you hold; "
                           "DO NOT add fresh until risk-reward improves.")
                show_h(holdings_df[holdings_df["holding_action"] == "Do Not Add / Trail Only"],
                       "No holdings currently overextended.")

            # ---- F. Value Assessment (fundamentals quality-growth lens) ----
            with sub[5]:
                st.caption("Each holding judged on the 3-5 year fundamentals lens "
                           "(Value Class, Composite Value, Expected CAGR). Needs "
                           "fundamentals - use the sidebar (Yahoo auto or Screener CSV) "
                           "and re-run the scan.")
                if "Value Class" not in holdings_df.columns or \
                        holdings_df["Value Class"].fillna("").eq("").all():
                    st.warning("No fundamentals attached to your holdings yet. In the "
                               "sidebar: tick **Use Yahoo auto-fundamentals**, click "
                               "**Fetch** (now includes your holdings), then **Run "
                               "Scan**. Compounder status also needs the Screener CSV "
                               "(governance fields).")
                else:
                    # Value-class breakdown of the portfolio
                    vh = holdings_df.copy()
                    vh["Value Class"] = vh["Value Class"].fillna("Fundamentals Missing")
                    counts = vh["Value Class"].value_counts().reset_index()
                    counts.columns = ["Value Class", "Holdings"]
                    cc = st.columns(2)
                    cc[0].plotly_chart(px.pie(counts, names="Value Class", values="Holdings",
                                              hole=0.5, title="Holdings by Value Class"),
                                       use_container_width=True)
                    # Avg expected CAGR per held name (bar)
                    if "Expected CAGR %" in vh.columns:
                        cg = vh.dropna(subset=["Expected CAGR %"]).sort_values("Expected CAGR %")
                        if not cg.empty:
                            cc[1].plotly_chart(px.bar(cg.tail(15), x="Expected CAGR %",
                                                      y="symbol", orientation="h",
                                                      title="Holdings by Expected CAGR %",
                                                      color="Expected CAGR %",
                                                      color_continuous_scale="RdYlGn"),
                                               use_container_width=True)
                    st.divider()
                    val_cols = ["symbol", "company", "quantity", "current_value",
                                "pnl_pct", "Value Class", "Composite Value",
                                "Expected CAGR %", "CAGR Band", "Quality Score",
                                "Crossover Buy", "holding_action"]
                    show_cols = [c for c in val_cols if c in vh.columns]
                    st.subheader("Holdings - value assessment")
                    st.dataframe(vh[show_cols], use_container_width=True, height=420,
                                 hide_index=True)

            # ---- G. Holding Deep Dive (fragment-isolated) ----
            with sub[6]:
                @_fragment
                def _holding_deep_dive():
                    if holdings_df.empty:
                        st.info("Upload holdings to deep-dive.")
                        return
                    try:
                        pick = st.selectbox("Select holding", holdings_df["symbol"].tolist(),
                                            key="hold_deepdive")
                        r = holdings_df[holdings_df["symbol"] == pick].iloc[0]
                        cls = str(r.get("Classification", "")) or "No Scanner Data"
                        action = str(r.get("holding_action", "")) or "No Scanner Data"
                        st.markdown(
                            f"### {r['symbol']} - {r.get('company', '')}<br>"
                            f"{badge(action, ACT_COLORS.get(action, '#555'))} &nbsp; "
                            f"{badge(cls, CLASS_COLORS.get(cls, '#555'))}",
                            unsafe_allow_html=True)
                        st.caption(r.get("holding_remark", ""))
                        dc = st.columns(5)
                        metric_card(dc[0], "Qty", r.get("quantity"), "#37474f")
                        metric_card(dc[1], "Avg Cost", r.get("avg_cost"), "#37474f")
                        metric_card(dc[2], "CMP / LTP", r.get("CMP") if pd.notna(r.get("CMP")) else r.get("ltp"), "#37474f")
                        pnl_v = r.get("pnl", 0) or 0
                        metric_card(dc[3], "P&L", pnl_v, "#1e7d32" if pnl_v >= 0 else "#8b1e1e")
                        pnl_p = r.get("pnl_pct", 0) or 0
                        metric_card(dc[4], "P&L %", pnl_p, "#1e7d32" if pnl_p >= 0 else "#8b1e1e")
                        dc2 = st.columns(5)
                        metric_card(dc2[0], "Composite", r.get("Composite Score", "-"), "#1f4e79")
                        metric_card(dc2[1], "RS Score", r.get("RS Score", "-"), "#1f4e79")
                        metric_card(dc2[2], "Sector Rank", r.get("Sector Rank", "-"), "#1f4e79")
                        metric_card(dc2[3], "Avg vs CMP %", r.get("avg_vs_cmp_pct", "-"), "#37474f")
                        metric_card(dc2[4], "CMP vs 200DMA %", r.get("cmp_vs_200dma_pct", "-"), "#37474f")
                        # Value (fundamentals) lens, if attached
                        if str(r.get("Value Class", "") or "") not in ("", "nan"):
                            st.markdown(f"**Value lens:** {badge(str(r.get('Value Class')), '#1f4e79')}",
                                        unsafe_allow_html=True)
                            dv = st.columns(4)
                            metric_card(dv[0], "Composite Value", r.get("Composite Value", "-"), "#1f4e79")
                            metric_card(dv[1], "Expected CAGR %", r.get("Expected CAGR %", "-"), "#1e7d32")
                            metric_card(dv[2], "Quality", r.get("Quality Score", "-"), "#1f4e79")
                            metric_card(dv[3], "Crossover Buy", r.get("Crossover Buy", "-"),
                                        "#0b6e2e" if r.get("Crossover Buy") == "Yes" else "#555")
                        st.write(f"Trigger: {r.get('Trigger Price', '-')} | "
                                 f"Invalidation/SL: {r.get('Invalidation Level', '-')} | "
                                 f"Confirmation: {r.get('Confirmation Needed', '-')}")
                        if pd.notna(r.get("CMP")):
                            make_stock_chart(f"{pick}.NS", period,
                                             trigger=r.get("Trigger Price"),
                                             invalidation=r.get("Invalidation Level"))
                    except Exception as exc:
                        st.error(f"Could not render Holding Deep Dive: {exc}. "
                                 "Try selecting a different holding.")
                _holding_deep_dive()

    # =====================================================================
    # CROSSOVER BUY (v2 Phase 4 - the dual-scan jackpot, Section 38)
    # =====================================================================
    with T["Crossover Buy"]:
        st.markdown("## Crossover Buy")
        st.caption("A verified 15-20% CAGR business that is ALSO breaking out or "
                   "coiling. Quality + timing align - the highest-priority list. "
                   "Needs a fundamentals CSV.")
        xb = result.get("crossover", pd.DataFrame())
        if xb is None or xb.empty:
            st.info("No Crossover Buy stocks. This needs fundamentals (sidebar CSV) "
                    "AND a value Compounder / Quality-Growth that is simultaneously "
                    "Spring-Ready or an Actionable/Elite momentum breakout. Empty is "
                    "common - that is the point: it only fires on the best setups.")
        else:
            kc = st.columns(4)
            metric_card(kc[0], "Crossover Buys", len(xb), "#0b6e2e")
            metric_card(kc[1], "Avg Composite Value",
                        f"{xb['Composite Value'].mean():.0f}", "#1e7d32")
            metric_card(kc[2], "Avg Expected CAGR %",
                        f"{xb['Expected CAGR %'].mean():.1f}", "#1e7d32")
            top_sec = (xb["Sector"].mode().iloc[0]
                       if not xb["Sector"].dropna().empty else "-")
            metric_card(kc[3], "Top sector", top_sec, "#1f4e79")
            st.write("")
            stock_cards(xb, len(xb), "#0b6e2e", [
                ("CMP", "CMP"), ("Comp Value", "Composite Value"),
                ("CAGR %", "Expected CAGR %"), ("Class", "Value Class"),
                ("Momentum", "Composite Score"), ("Spring", "Spring Ready"),
                ("Entry", "Value Entry Style"), ("Zone", "Accumulation Zone")])
            st.write("")
            st.plotly_chart(px.scatter(
                xb, x="Composite Value", y="Composite Score", size="Expected CAGR %",
                color="Value Class", hover_name="Symbol",
                hover_data=["Sector", "Expected CAGR %", "Value Entry Style"],
                title="Crossover Buy: value (x) vs momentum (y), bubble = CAGR",
                size_max=30), use_container_width=True)
            st.divider()
            xb_cols = ["Symbol", "Company", "Sector", "CMP", "Value Class",
                       "Composite Value", "Expected CAGR %", "CAGR Band", "Composite Score",
                       "Momentum Class", "Spring Ready", "Quality Score", "Value Entry Style",
                       "Accumulation Zone", "Value Target 3-5Y", "Risk Level"]
            summary_table(xb, key="xover_tbl", title="Crossover Buy stocks",
                          caption="Quality business + technical timing. Still confirm "
                                  "chart, news and liquidity before sizing.",
                          detail_cols=xb_cols, default_sort="Composite Value")

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
        st.markdown("## Strong Breakout / Actionable")
        st.caption("Highest-conviction momentum candidates. Always confirm chart, "
                   "news and liquidity before entry.")
        if strong.empty:
            st.info("No strong breakout stocks with current settings.")
        else:
            # A. Summary cards
            sc = st.columns(5)
            metric_card(sc[0], "Strong Breakouts", len(strong),
                        CLASS_COLORS["Strong Breakout / Actionable"])
            metric_card(sc[1], "Avg Score", f"{strong['Score'].mean():.0f}", "#37474f")
            metric_card(sc[2], "Avg Vol Ratio", f"{strong['Volume Ratio'].mean():.2f}", "#37474f")
            top_sec = (strong["Sector"].mode().iloc[0]
                       if not strong["Sector"].dropna().empty else "-")
            metric_card(sc[3], "Top sector", top_sec, "#1f4e79")
            avg_rs = strong["RS Score"].mean() if "RS Score" in strong else float("nan")
            metric_card(sc[4], "Avg RS Score",
                        f"{avg_rs:.0f}" if pd.notna(avg_rs) else "-", "#1e7d32")
            st.write("")
            # B. Cards for every strong breakout (actionable list - none hidden)
            stock_cards(strong, len(strong), CLASS_COLORS["Strong Breakout / Actionable"], [
                ("Score", "Score"), ("CMP", "CMP"), ("Breakout", "Breakout Status"),
                ("RSI", "RSI 14"), ("Vol Ratio", "Volume Ratio"), ("Risk", "Risk Level"),
                ("Entry", "Entry Zone"), ("Stop", "Stop Loss"),
                ("T1", "Target 1"), ("T2", "Target 2")])
            st.write("")
            g = st.columns(2)
            g[0].plotly_chart(px.bar(strong.sort_values("Score").tail(20), x="Score", y="Symbol",
                                     orientation="h", title="Strong Breakout ranking",
                                     hover_data=["RSI 14", "Volume Ratio", "Relative Strength %"],
                                     color="Score", color_continuous_scale="Greens"),
                              use_container_width=True)
            sd = strong.copy()
            sd["Risk %"] = ((sd["CMP"] - sd["Invalidation Level"]) / sd["CMP"] * 100).round(2)
            g[1].plotly_chart(px.scatter(sd, x="Risk %", y="Risk Reward", size="Volume Ratio",
                                         color="Risk Level", color_discrete_map=RISK_COLORS,
                                         hover_name="Symbol", title="Risk vs Reward (bubble = volume)",
                                         size_max=30),
                              use_container_width=True)
            st.divider()
            summary_table(strong, key="strong_tbl", title="All Strong Breakout stocks",
                          caption="Compact view first; open the expander for every column.",
                          detail_cols=list(strong.columns))

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
            # A. Summary cards
            wc = st.columns(5)
            metric_card(wc[0], "Waitlist stocks", len(wd), CLASS_COLORS["Wait for Confirmation"])
            nearest = wd.sort_values("Distance to Trigger %").iloc[0]
            metric_card(wc[1], "Closest to trigger", nearest["Symbol"], "#1e7d32",
                        sub=f"{nearest['Distance to Trigger %']}% away")
            metric_card(wc[2], "Highest score", f"{wd['Score'].max():.0f}", "#37474f")
            metric_card(wc[3], "Highest RS Score",
                        f"{wd['RS Score'].max():.0f}" if 'RS Score' in wd else "-", "#37474f")
            vol_only = int(wd["Confirmation Needed"].str.contains("volume", case=False, na=False).sum())
            metric_card(wc[4], "Need volume only", vol_only, "#e08e0b")
            st.write("")
            # B. Cards (top 20, wraps 5 per row)
            stock_cards(wd, min(20, len(wd)), CLASS_COLORS["Wait for Confirmation"], [
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
            st.divider()
            # E. Alert watchlist table (compact first, full in expander)
            alert_cols = ["Symbol", "Company", "CMP", "Trigger Price", "Suggested Alert Price",
                          "Distance to Trigger %", "Confirmation Needed", "Invalidation Level",
                          "Score", "Composite Score", "RS Score", "Risk Level"]
            tbl = wd.sort_values(["Distance to Trigger %", "Score", "Relative Strength %"],
                                 ascending=[True, False, False])
            summary_table(tbl, key="wait_tbl", title="Alert watchlist",
                          caption="Sorted by distance to trigger. Set alerts near the "
                                  "trigger price; do not enter until it confirms.",
                          detail_cols=alert_cols, default_sort="Score")

    # =====================================================================
    # 4) EARLY WATCHLIST
    # =====================================================================
    with T["Early Watchlist"]:
        st.info("Observe only. No trade until confirmation improves.")
        if watch.empty:
            st.info("No early-watchlist stocks with current settings.")
        else:
            stock_cards(watch, min(15, len(watch)), CLASS_COLORS["Early Watchlist"], [
                ("CMP", "CMP"), ("Score", "Score"), ("RSI", "RSI 14"),
                ("Vol", "Volume Ratio"), ("Retest", "Retest Date"),
                ("RelStr %", "Relative Strength %"), ("Breakout", "Breakout Status")])
            st.write("")
            st.plotly_chart(px.bar(watch.sort_values("Score").tail(20), x="Score", y="Symbol",
                                   orientation="h", title="Top early setups by score",
                                   color="Score", color_continuous_scale="Blues"),
                            use_container_width=True)
            st.divider()
            summary_table(watch, key="watch_tbl", title="Early-Watchlist stocks",
                          caption="Momentum developing but not ready. Observe only.",
                          detail_cols=list(watch.columns), default_sort="Score")

    # =====================================================================
    # SECTOR ROTATION (percentile-ranked sector strength engine)
    # =====================================================================
    with T["Sector Rotation"]:
        st.markdown("## Sector Rotation Dashboard")
        st.caption("Identify which sectors are leading and which stocks inside "
                   "those sectors are showing momentum.")
        if sector_rot is None or sector_rot.empty:
            st.info("No sector data available. Run a scan first.")
        else:
            @_fragment
            def _sector_rotation():
                sr = sector_rot.copy()
                # Selector at the TOP - preserved in session_state so changing it
                # only re-runs THIS fragment, never the whole scan.
                sectors = list(sr["Sector"])
                sel = st.selectbox("Select sector to view stocks", sectors,
                                   key="sector_pick")
                row = sr[sr["Sector"] == sel].iloc[0]

                # --- B. Selected-sector summary cards (8 metrics, 2 rows) ---
                st.markdown(f"### {sel}  -  {row['Sector Status']}")
                a = st.columns(4)
                metric_card(a[0], "Sector Rank", f"#{int(row['Sector Rank'])}", "#1f4e79")
                metric_card(a[1], "Strength Score", f"{row['Sector Strength Score']:.0f}/100",
                            "#1e7d32" if row["Sector Strength Score"] >= 60 else "#e08e0b")
                metric_card(a[2], "Avg 20D Return %", f"{row['Avg_Return_20D']}", "#37474f")
                metric_card(a[3], "Avg RS Score", f"{row['Avg_RS_Score']:.0f}", "#37474f")
                b = st.columns(4)
                metric_card(b[0], "% Above 50 DMA", f"{row['Pct_Above_50DMA']:.0f}%", "#1f4e79")
                metric_card(b[1], "% Above 200 DMA", f"{row['Pct_Above_200DMA']:.0f}%", "#1f4e79")
                metric_card(b[2], "Strong Breakouts", int(row["Strong"]),
                            CLASS_COLORS["Strong Breakout / Actionable"])
                metric_card(b[3], "Wait for Confirmation", int(row["Wait"]),
                            CLASS_COLORS["Wait for Confirmation"])
                st.divider()

                # --- C. Charts first ---
                g1 = st.columns(2)
                # 1. Sector strength bar, selected sector highlighted
                srs = sr.sort_values("Sector Strength Score")
                bar_colors = ["#1e7d32" if s == sel else "#9fb6c4" for s in srs["Sector"]]
                fig_str = go.Figure(go.Bar(
                    x=srs["Sector Strength Score"], y=srs["Sector"], orientation="h",
                    marker_color=bar_colors))
                fig_str.update_layout(title="Sector strength (selected highlighted)",
                                      height=max(320, 20 * len(srs)), margin=dict(t=40, b=10))
                g1[0].plotly_chart(fig_str, use_container_width=True)
                # 2. Breadth for selected sector
                breadth = pd.DataFrame({
                    "Breadth": ["% Above 50 DMA", "% Above 200 DMA"],
                    "Pct": [row["Pct_Above_50DMA"], row["Pct_Above_200DMA"]]})
                g1[1].plotly_chart(px.bar(breadth, x="Pct", y="Breadth", orientation="h",
                                          range_x=[0, 100], title=f"{sel} breadth",
                                          color="Breadth",
                                          color_discrete_sequence=["#1e7d32", "#1f4e79"]),
                                   use_container_width=True)

                # Stocks in the selected sector (handle missing sector safely)
                stk = allstocks.copy() if not allstocks.empty else pd.DataFrame()
                if not stk.empty:
                    stk["Sector"] = stk["Sector"].fillna("Unknown").replace("", "Unknown")
                    stk = stk[stk["Sector"] == sel]

                if stk.empty:
                    st.info("No scanned stocks in this sector.")
                    return

                g2 = st.columns(2)
                # 3. Classification donut for selected sector
                cc = stk["Classification"].value_counts().reset_index()
                cc.columns = ["Classification", "Count"]
                g2[0].plotly_chart(px.pie(cc, names="Classification", values="Count",
                                          hole=0.5, title=f"{sel} - classification split",
                                          color="Classification",
                                          color_discrete_map=CLASS_COLORS),
                                   use_container_width=True)
                # 4. Top-10 stocks by composite score
                top10 = stk.sort_values("Composite Score", ascending=False).head(10)
                g2[1].plotly_chart(px.bar(top10.sort_values("Composite Score"),
                                          x="Composite Score", y="Symbol", orientation="h",
                                          title=f"Top {len(top10)} in {sel} by score",
                                          color="Classification", color_discrete_map=CLASS_COLORS),
                                   use_container_width=True)

                # 5. Momentum scatter
                sc = stk.copy()
                sc["Volume Ratio"] = pd.to_numeric(sc["Volume Ratio"], errors="coerce").fillna(1).clip(lower=0.1)
                st.plotly_chart(px.scatter(
                    sc, x="Relative Strength %", y="Composite Score", size="Volume Ratio",
                    color="Classification", color_discrete_map=CLASS_COLORS, hover_name="Symbol",
                    hover_data=["Company", "CMP", "RSI 14", "Trigger Price"],
                    title=f"{sel} - momentum map (bubble = volume)", size_max=26),
                    use_container_width=True)
                st.divider()

                # --- D. Detailed table at the BOTTOM (header above) ---
                det = ["Symbol", "Company", "CMP", "Classification", "Composite Score",
                       "RS Score", "Sector Strength Score", "RSI 14", "Volume Ratio",
                       "Distance from 52W High %", "Breakout Status", "Trigger Price",
                       "Confirmation Needed", "Risk Level", "Final Remark"]
                ordered = stk.sort_values(
                    ["Composite Score", "RS Score", "Distance from 52W High %"],
                    ascending=[False, False, True])
                summary_table(ordered, key="sector_stocks",
                              title=f"Stocks in {sel}",
                              caption="Sorted by momentum score. Use the filters to "
                                      "search or narrow by classification.",
                              detail_cols=det)

            _sector_rotation()

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
            rs_all = allstocks.sort_values("RS Score", ascending=False).copy()
            leaders = rs_all[rs_all.get("RS Leader") == "Yes"] if "RS Leader" in rs_all else pd.DataFrame()
            # A. Summary cards
            cc = st.columns(4)
            metric_card(cc[0], "RS Leaders", len(leaders), "#1e7d32")
            metric_card(cc[1], "Avg RS Score", f"{rs_all['RS Score'].mean():.0f}", "#37474f")
            top_sec = (rs_all.head(20)["Sector"].mode().iloc[0]
                       if not rs_all.head(20)["Sector"].dropna().empty else "-")
            metric_card(cc[2], "Top sector (top 20)", top_sec, "#1f4e79")
            metric_card(cc[3], "Highest RS Score", f"{rs_all['RS Score'].max():.0f}", "#1e7d32")
            st.write("")
            rs = rs_all.head(20)
            st.plotly_chart(px.bar(rs.sort_values("RS Score"), x="RS Score", y="Symbol",
                                   orientation="h", title="Top 20 by RS Score",
                                   color="RS Score", color_continuous_scale="Viridis",
                                   hover_data=["Sector", "RS 20D %", "RS 60D %", "RS 120D %"]),
                            use_container_width=True)
            st.divider()
            rs_cols = ["Symbol", "Company", "Sector", "Classification", "RS Leader", "RS Score",
                       "RS 5D %", "RS 20D %", "RS 60D %", "RS 120D %", "RS 252D %", "CMP",
                       "Distance from 52W High %", "Composite Score"]
            summary_table(rs_all, key="rs_leaders", title="Relative Strength ranking",
                          caption="All scanned stocks ranked by RS Score. "
                                  "Filter by classification or search a symbol.",
                          detail_cols=rs_cols, default_sort="RS Score")

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
                # Summary cards
                dc = st.columns(4)
                metric_card(dc[0], "Overextended", len(nc), "#6a1b9a")
                metric_card(dc[1], "Avg Composite", f"{nc['Composite Score'].mean():.0f}", "#37474f")
                metric_card(dc[2], "Avg Dist 20 DMA %",
                            f"{nc['Distance from 20 DMA %'].mean():.1f}", "#e08e0b")
                top_sec = (nc["Sector"].mode().iloc[0]
                           if not nc["Sector"].dropna().empty else "-")
                metric_card(dc[3], "Top sector", top_sec, "#1f4e79")
                st.write("")
                st.plotly_chart(px.scatter(
                    nc, x="Distance from 20 DMA %", y="Distance from 200 DMA %",
                    size="Composite Score", color="Classification", color_discrete_map=CLASS_COLORS,
                    hover_name="Symbol", title="How extended? (further right/up = more stretched)",
                    size_max=26), use_container_width=True)
                st.divider()
                nc_cols = ["Symbol", "Company", "Sector", "Classification", "CMP",
                           "Distance from 20 DMA %", "Distance from 50 DMA %",
                           "Distance from 200 DMA %", "RSI 14", "Gap Up %", "Risk Reward",
                           "No Chase Reason", "Wait Condition", "Composite Score"]
                summary_table(nc, key="nochase_tbl", title="Overextended stocks",
                              caption="Good stocks, late entry. Hold/trail only; "
                                      "wait for the suggested condition before adding.",
                              detail_cols=nc_cols)

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
            # Summary cards
            kc = st.columns(4)
            metric_card(kc[0], "Coiled setups", len(cdf), "#6a1b9a")
            metric_card(kc[1], "Avg Coiled Score", f"{cdf['Coiled Score'].mean():.0f}", "#37474f")
            nearest = cdf.sort_values("Distance to Trigger %").iloc[0]
            metric_card(kc[2], "Closest to trigger", nearest["Symbol"], "#1e7d32",
                        sub=f"{nearest['Distance to Trigger %']}% away")
            metric_card(kc[3], "Tightest ATR contr.",
                        f"{cdf['ATR Contraction'].min():.2f}", "#1f4e79")
            st.write("")
            stock_cards(cdf, min(20, len(cdf)), "#6a1b9a", [
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
            st.divider()
            ccols = ["Symbol", "Company", "Sector", "CMP", "Coiled Score", "ATR Contraction",
                     "Volume Dryup 10D", "Range 10D %", "Distance from 52W High %",
                     "Trigger Price", "Distance to Trigger %", "RS Score", "Risk Level"]
            summary_table(cdf, key="coiled_tbl", title="Coiled / Ready stocks",
                          caption="Spring-loaded setups. Wait for a breakout with volume.",
                          detail_cols=ccols, default_sort="Coiled Score")

    # =====================================================================
    # SPRING / PRE-BREAKOUT (v2 - earliest candidate detector)
    # =====================================================================
    with T["Spring / Pre-Breakout"]:
        st.markdown("## Spring / Pre-Breakout")
        st.caption("Stocks coiling in a tight base WHILE under accumulation (rising "
                   "OBV, dry down-volume) - caught BEFORE the breakout. Alert at the "
                   "pivot; enter only on a volume breakout above trigger.")
        if spring is None or spring.empty:
            st.info("No Spring-Ready setups with current settings. This is the strictest "
                    "engine (tight VCP base + accumulation + uptrend); empty is common "
                    "in a weak or choppy market.")
        else:
            sp = spring.copy()
            sp["To Trigger %"] = ((sp["Spring Trigger"] / sp["CMP"] - 1) * 100).round(2)
            kc = st.columns(4)
            metric_card(kc[0], "Spring Ready", len(sp), "#6a1b9a")
            metric_card(kc[1], "Avg Spring Score", f"{sp['Spring Score'].mean():.0f}", "#37474f")
            metric_card(kc[2], "Avg Accumulation",
                        f"{sp['Accumulation Score'].mean():.0f}", "#1e7d32")
            nearest = sp.sort_values("To Trigger %").iloc[0]
            metric_card(kc[3], "Closest to pivot", nearest["Symbol"], "#1f4e79",
                        sub=f"{nearest['To Trigger %']}% away")
            st.write("")
            stock_cards(sp, min(20, len(sp)), "#6a1b9a", [
                ("CMP", "CMP"), ("Spring", "Spring Score"), ("Accum", "Accumulation Score"),
                ("A/D", "A/D State"), ("VCP", "VCP Contractions"),
                ("Pocket Pivot", "Pocket Pivot"), ("Trigger", "Spring Trigger"),
                ("To Trigger %", "To Trigger %")])
            st.write("")
            gsp = st.columns(2)
            gsp[0].plotly_chart(px.bar(sp.sort_values("Spring Score").tail(20),
                                       x="Spring Score", y="Symbol", orientation="h",
                                       title="Tightest accumulating springs",
                                       color="Accumulation Score",
                                       color_continuous_scale="Purples"),
                                use_container_width=True)
            gsp[1].plotly_chart(px.scatter(
                sp, x="Accumulation Score", y="Spring Score", size="VCP Contractions",
                color="A/D State",
                color_discrete_map={"Accumulation": "#1e7d32", "Neutral": "#e08e0b",
                                    "Distribution": "#8b1e1e"},
                hover_name="Symbol", title="Spring vs Accumulation (bubble = VCP)",
                size_max=24), use_container_width=True)
            st.divider()
            scols = ["Symbol", "Company", "Sector", "CMP", "Spring Score",
                     "Accumulation Score", "A/D State", "VCP Contractions", "Pocket Pivot",
                     "Base Depth %", "Base Length D", "OBV Slope 20D %",
                     "Distance from 52W High %", "Spring Trigger", "To Trigger %",
                     "Composite Score", "Risk Level"]
            summary_table(sp, key="spring_tbl", title="Spring / Pre-Breakout stocks",
                          caption="Earliest stage. Set an alert at the Spring Trigger; "
                                  "only buy a volume breakout above it.",
                          detail_cols=scols, default_sort="Spring Score")

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
            # Summary cards
            fc = st.columns(4)
            metric_card(fc[0], "Fresh candidates", len(fresh), "#00897b")
            metric_card(fc[1], "Avg Fresh Score",
                        f"{fresh['Fresh Momentum Score'].mean():.0f}", "#37474f")
            metric_card(fc[2], "Avg Vol Ratio", f"{fresh['Volume Ratio'].mean():.2f}", "#37474f")
            top_sec = (fresh["Sector"].mode().iloc[0]
                       if not fresh["Sector"].dropna().empty else "-")
            metric_card(fc[3], "Top sector", top_sec, "#1f4e79")
            st.write("")
            stock_cards(fresh, min(20, len(fresh)), "#00897b", [
                ("CMP", "CMP"), ("Fresh", "Fresh Momentum Score"), ("RSI", "RSI 14"),
                ("ADX", "ADX 14"), ("Vol", "Volume Ratio"), ("20D High", "20D High"),
                ("RS", "RS Score"), ("Risk", "Risk Level")])
            st.write("")
            st.plotly_chart(px.bar(fresh.sort_values("Fresh Momentum Score").tail(20),
                                   x="Fresh Momentum Score", y="Symbol", orientation="h",
                                   title="Top fresh momentum candidates",
                                   color="Fresh Momentum Score", color_continuous_scale="Teal"),
                            use_container_width=True)
            st.divider()
            fcols = ["Symbol", "Company", "Sector", "CMP", "Fresh Momentum Score", "RSI 14",
                     "ADX 14", "Volume Ratio", "20D High", "RS Score", "Composite Score", "Risk Level"]
            summary_table(fresh, key="fresh_tbl", title="Fresh momentum stocks",
                          caption="New ignition. Prefer entry on a small pullback or "
                                  "breakout sustain.",
                          detail_cols=fcols, default_sort="Fresh Momentum Score")

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
    # TECHNICAL VALUE SCANNER (Phase 2)
    # =====================================================================
    VALUE_COLORS = {
        "Value Reversal Ready": "#0b6e2e", "Value Base Forming": "#1f4e79",
        "Deep Value High Risk": "#e08e0b", "Value Trap Avoid": "#8b1e1e"}
    MATRIX_COLORS = {
        # old (no-fundamentals) labels
        "Best Crossover": "#0b6e2e", "Momentum Leader": "#1e7d32",
        "Value Recovery": "#1f4e79", "Mixed": "#37474f", "Avoid": "#8b1e1e",
        # v2 Phase 3 quality-growth labels (used when fundamentals are loaded)
        "Crossover Buy": "#0b6e2e", "Compounder (accumulate)": "#1e7d32",
        "Quality Watch": "#1f4e79", "Cyclical / Turnaround": "#e08e0b"}

    def _vfilter(cls):
        return (allstocks[allstocks.get("Value Classification") == cls]
                if "Value Classification" in allstocks.columns else pd.DataFrame())

    val_reversal = _vfilter("Value Reversal Ready").sort_values(
        "Value Score", ascending=False) if not allstocks.empty else pd.DataFrame()
    val_base = _vfilter("Value Base Forming").sort_values(
        "Value Score", ascending=False) if not allstocks.empty else pd.DataFrame()
    val_deep = _vfilter("Deep Value High Risk").sort_values(
        "Value Score", ascending=False) if not allstocks.empty else pd.DataFrame()
    val_trap = _vfilter("Value Trap Avoid") if not allstocks.empty else pd.DataFrame()

    # =====================================================================
    # VALUE / QUALITY-GROWTH (v2 Phase 3 - fundamentals-driven 3-5 yr scan)
    # =====================================================================
    VCLASS_COLORS = {
        "Compounder": "#1e7d32", "Quality-Growth Watch": "#1f4e79",
        "Cyclical Value": "#e08e0b", "Turnaround": "#6a1b9a",
        "Fundamentals Missing": "#555", "Value Avoid": "#8b1e1e"}
    vq = result.get("value_quality", pd.DataFrame())
    xover = result.get("crossover", pd.DataFrame())
    with T["Value / Quality-Growth"]:
        st.markdown("## Value / Quality-Growth (3-5 year)")
        st.caption("Fundamentals FIRST: targets businesses that can compound at "
                   "~15-20% for 3-5 years. Needs a fundamentals CSV (sidebar).")
        if vq is None or vq.empty:
            # If fundamentals ARE loaded now but the last scan has none attached,
            # the scan simply predates the fundamentals - tell the user to re-run.
            if fundamentals_data:
                st.warning(f"Fundamentals are loaded for {len(fundamentals_data)} "
                           "stocks, but the LAST SCAN ran before they were available. "
                           "Click **Run Scan** again (sidebar) - fundamentals only "
                           "attach during a scan. This tab will then populate.")
            else:
                st.info("No fundamentals loaded. In the sidebar, either tick **Use "
                        "Yahoo auto-fundamentals** and click **Fetch**, or upload a "
                        "`fundamentals.csv`, then **Run Scan**. Empty by design "
                        "without fundamentals.")
        else:
            def _vqn(cls):
                return int((vq["Value Class"] == cls).sum())
            vc = st.columns(5)
            metric_card(vc[0], "Crossover Buy", len(xover), "#0b6e2e",
                        sub="quality + timing")
            metric_card(vc[1], "Compounder", _vqn("Compounder"), VCLASS_COLORS["Compounder"])
            metric_card(vc[2], "Quality-Growth Watch", _vqn("Quality-Growth Watch"),
                        VCLASS_COLORS["Quality-Growth Watch"])
            metric_card(vc[3], "Cyclical Value", _vqn("Cyclical Value"),
                        VCLASS_COLORS["Cyclical Value"])
            metric_card(vc[4], "Avoid", _vqn("Value Avoid"), VCLASS_COLORS["Value Avoid"])
            st.write("")
            # Crossover Buy is the jackpot list (Section 38) - show first.
            if not xover.empty:
                st.success("**Crossover Buy** - verified quality business that is ALSO "
                           "breaking out or coiling. Highest-priority list.")
                stock_cards(xover, min(10, len(xover)), "#0b6e2e", [
                    ("CMP", "CMP"), ("Comp Value", "Composite Value"),
                    ("CAGR %", "Expected CAGR %"), ("Class", "Value Class"),
                    ("Quality", "Quality Score"), ("Momentum", "Composite Score")])
                st.write("")
            g = st.columns(2)
            g[0].plotly_chart(px.scatter(
                vq, x="Composite Value", y="Expected CAGR %", size="Quality Score",
                color="Value Class", color_discrete_map=VCLASS_COLORS, hover_name="Symbol",
                hover_data=["Sector", "Growth Score", "Valuation Score", "Value Tier"],
                title="Value vs Expected CAGR (bubble = quality)", size_max=26),
                use_container_width=True)
            comp_only = vq[vq["Value Class"] == "Compounder"].sort_values("Expected CAGR %")
            if not comp_only.empty:
                g[1].plotly_chart(px.bar(comp_only.tail(15), x="Expected CAGR %", y="Symbol",
                                         orientation="h", title="Top compounders by Expected CAGR",
                                         color="Composite Value", color_continuous_scale="Greens"),
                                  use_container_width=True)
            st.divider()
            vq_cols = ["Symbol", "Company", "Sector", "CMP", "Value Class", "Value Tier",
                       "Composite Value", "Expected CAGR %", "DCF CAGR %",
                       "CAGR Confidence", "CAGR Divergence", "CAGR Band", "Quality Score",
                       "Growth Score", "Valuation Score", "Valuation Flag",
                       "Balance-Sheet Score", "Promoter Score", "Crossover Buy",
                       "Value Entry Style", "Accumulation Zone", "Value Target 3-5Y"]
            summary_table(vq, key="vq_tbl", title="Value / Quality-Growth stocks",
                          caption="Sorted by Composite Value then Expected CAGR. "
                                  "Compounders pass the hard quality gate (Section 32).",
                          detail_cols=vq_cols, default_sort="Composite Value")

    with T["Technical Recovery"]:
        st.markdown("## Technical Recovery")
        st.caption("Mean-reversion / bounce-off-support setups (technical only). "
                   "This is NOT the long-term value scan - see the **Value / "
                   "Quality-Growth** tab for fundamentals-driven 3-5 yr compounders.")
        if "Value Score" not in allstocks.columns or allstocks.empty:
            st.info("Run a scan to populate technical recovery setups.")
        else:
            vc = st.columns(4)
            metric_card(vc[0], "Reversal Ready", len(val_reversal), VALUE_COLORS["Value Reversal Ready"])
            metric_card(vc[1], "Base Forming", len(val_base), VALUE_COLORS["Value Base Forming"])
            metric_card(vc[2], "Deep Value (High Risk)", len(val_deep), VALUE_COLORS["Deep Value High Risk"])
            metric_card(vc[3], "Value Trap (Avoid)", len(val_trap), VALUE_COLORS["Value Trap Avoid"])

            vsub = st.tabs(["Summary", "Reversal Ready", "Base Forming",
                            "Deep Value High Risk", "Value Trap Avoid", "Value Deep Dive"])

            VAL_CARD_COLS = [
                ("CMP", "CMP"), ("Value Score", "Value Score"),
                ("Composite", "Composite Score"), ("RSI", "RSI 14"),
                ("Below 52W %", "Distance from 52W High %"),
                ("Entry", "Value Entry Style"), ("Trigger", "Value Trigger Price"),
                ("Invalidation", "Value Invalidation Level"), ("Risk", "Risk Level")]

            VAL_TBL_COLS = ["Symbol", "Company", "Sector", "CMP", "Value Score",
                            "Composite Score", "Value Classification", "Value Entry Style",
                            "Value Trigger Price", "Value Invalidation Level",
                            "Value Target Zone", "Distance from 52W High %",
                            "Distance from 200 DMA %", "RSI 14", "ADX 14",
                            "Volume Ratio", "Relative Strength %", "Sector Status",
                            "Risk Level", "Value Remark"]

            def vshow(df, msg, key, title):
                if df is None or df.empty:
                    st.info(msg); return
                summary_table(df, key=key, title=title,
                              caption="Compact view first; open the expander for all columns.",
                              detail_cols=VAL_TBL_COLS, default_sort="Value Score")

            # --- Summary ---
            with vsub[0]:
                gv = st.columns(2)
                # Score distribution
                vd = allstocks["Value Score"].dropna()
                bands = {"75-100": int(((vd >= 75)).sum()),
                         "60-75": int(((vd >= 60) & (vd < 75)).sum()),
                         "40-60": int(((vd >= 40) & (vd < 60)).sum()),
                         "<40":   int((vd < 40).sum())}
                gv[0].plotly_chart(px.bar(pd.DataFrame({"Band": list(bands), "Count": list(bands.values())}),
                                          x="Band", y="Count", title="Value Score distribution",
                                          color="Band", color_discrete_sequence=[
                                              VALUE_COLORS["Value Reversal Ready"], VALUE_COLORS["Value Base Forming"],
                                              VALUE_COLORS["Deep Value High Risk"], VALUE_COLORS["Value Trap Avoid"]]),
                                   use_container_width=True)
                # Top sectors in recovery (Reversal + Base)
                rec = pd.concat([val_reversal, val_base]) if not (val_reversal.empty and val_base.empty) else pd.DataFrame()
                if not rec.empty and "Sector" in rec:
                    sec = rec["Sector"].value_counts().head(8).reset_index()
                    sec.columns = ["Sector", "Count"]
                    gv[1].plotly_chart(px.bar(sec, x="Count", y="Sector", orientation="h",
                                              title="Top sectors in value recovery",
                                              color_discrete_sequence=["#1f4e79"]),
                                       use_container_width=True)
            # --- Reversal Ready ---
            with vsub[1]:
                st.success("Recovery confirmed. Consider only after chart/news review.")
                if not val_reversal.empty:
                    stock_cards(val_reversal, min(20, len(val_reversal)),
                                VALUE_COLORS["Value Reversal Ready"], VAL_CARD_COLS)
                    st.write("")
                    st.plotly_chart(px.bar(val_reversal.sort_values("Value Score").tail(20),
                                           x="Value Score", y="Symbol", orientation="h",
                                           title="Value Reversal Ready - ranking",
                                           color="Value Score", color_continuous_scale="Greens"),
                                    use_container_width=True)
                st.divider()
                vshow(val_reversal, "No Value Reversal Ready candidates.",
                      "val_rev_tbl", "Value Reversal Ready stocks")
            # --- Base Forming ---
            with vsub[2]:
                st.info("Base forming. Set alert above the base resistance / trigger price.")
                if not val_base.empty:
                    stock_cards(val_base, min(20, len(val_base)),
                                VALUE_COLORS["Value Base Forming"], VAL_CARD_COLS)
                    st.write("")
                    nb = val_base.copy()
                    nb["Distance to Trigger %"] = ((nb["Value Trigger Price"] / nb["CMP"] - 1) * 100).round(2)
                    st.plotly_chart(px.bar(nb.sort_values("Distance to Trigger %").head(15),
                                           x="Distance to Trigger %", y="Symbol", orientation="h",
                                           title="Closest to base-breakout trigger",
                                           color_discrete_sequence=["#1f4e79"]),
                                    use_container_width=True)
                st.divider()
                vshow(val_base, "No Value Base Forming candidates.",
                      "val_base_tbl", "Value Base Forming stocks")
            # --- Deep Value High Risk ---
            with vsub[3]:
                st.warning("High-risk recovery candidates. Use as a small watchlist only.")
                vshow(val_deep, "No Deep Value (high-risk) candidates.",
                      "val_deep_tbl", "Deep Value (High Risk) stocks")
            # --- Value Trap Avoid ---
            with vsub[4]:
                st.error("Cheap but technically weak. Avoid until structure improves.")
                vshow(val_trap, "No Value Trap names.",
                      "val_trap_tbl", "Value Trap (Avoid) stocks")
            # --- Value Deep Dive (fragment-isolated) ---
            with vsub[5]:
                @_fragment
                def _value_deep_dive():
                    pool = pd.concat([val_reversal, val_base, val_deep], ignore_index=True) \
                        if not (val_reversal.empty and val_base.empty and val_deep.empty) else pd.DataFrame()
                    if pool.empty:
                        st.info("No value candidates to deep-dive.")
                        return
                    try:
                        pick = st.selectbox("Select a value stock", pool["Symbol"].tolist(),
                                            key="val_dive")
                        r = pool[pool["Symbol"] == pick].iloc[0]
                        cls = r["Value Classification"]
                        st.markdown(
                            f"### {r['Symbol']} - {r['Company']}<br>"
                            f"{badge(cls, VALUE_COLORS.get(cls, '#555'))} &nbsp; "
                            f"{badge(r.get('Risk Level', '-'), RISK_COLORS.get(r.get('Risk Level', ''), '#555'))}",
                            unsafe_allow_html=True)
                        st.caption(r.get("Value Remark", ""))
                        dvc = st.columns(2)
                        dvc[0].plotly_chart(score_gauge(r["Value Score"]), use_container_width=True)
                        bd = pd.DataFrame({
                            "Component": ["Correction", "Stabilisation", "Reversal", "RS", "Risk"],
                            "Score": [r.get("Value Correction Score", 0),
                                      r.get("Value Stabilisation Score", 0),
                                      r.get("Value Reversal Score", 0),
                                      r.get("Value RS Score", 0),
                                      r.get("Value Risk Score", 0)],
                            "Max":   [20, 25, 25, 15, 15]})
                        dvc[1].plotly_chart(px.bar(bd, x="Score", y="Component", orientation="h",
                                                   title="Value-score breakdown",
                                                   color="Score", color_continuous_scale="Tealgrn"),
                                            use_container_width=True)
                        st.write(f"Entry style: **{r.get('Value Entry Style', '-')}**  |  "
                                 f"Trigger: {r.get('Value Trigger Price', '-')}  |  "
                                 f"Invalidation: {r.get('Value Invalidation Level', '-')}  |  "
                                 f"Target zone: {r.get('Value Target Zone', '-')}")
                        make_stock_chart(f"{pick}.NS", period,
                                         trigger=r.get("Value Trigger Price"),
                                         invalidation=r.get("Value Invalidation Level"))
                    except Exception as exc:
                        st.error(f"Could not render Value Deep Dive: {exc}. "
                                 "Try selecting a different stock.")
                _value_deep_dive()

    # =====================================================================
    # MOMENTUM + VALUE MATRIX (Phase 2)
    # =====================================================================
    with T["Momentum + Value Matrix"]:
        if "Value Score" not in allstocks.columns or "Composite Score" not in allstocks.columns or allstocks.empty:
            st.info("Run a scan to build the matrix.")
        else:
            st.caption("Showing the 4 meaningful quadrants only. 'Mixed' "
                       "(average on both axes) is filtered out as noise.")
            cnt = allstocks["Matrix Class"].value_counts().to_dict() if "Matrix Class" in allstocks else {}
            mc = st.columns(4)
            for col, key in zip(mc, ["Best Crossover", "Momentum Leader",
                                     "Value Recovery", "Avoid"]):
                metric_card(col, key, cnt.get(key, 0), MATRIX_COLORS.get(key, "#555"))

            scat = allstocks[allstocks.get("Matrix Class") != "Mixed"].copy()
            scat["Volume Ratio"] = pd.to_numeric(scat["Volume Ratio"], errors="coerce").fillna(1.0).clip(lower=0.1)
            fig = px.scatter(
                scat, x="Value Score", y="Composite Score", size="Volume Ratio",
                color="Matrix Class", color_discrete_map=MATRIX_COLORS,
                hover_name="Symbol",
                hover_data=["Company", "Sector", "Classification", "Value Classification",
                            "Value Entry Style", "Risk Level"],
                title="Momentum (Y) vs Value (X) - bubble = volume ratio "
                      "(Mixed quadrant hidden)", size_max=28)
            # Quadrant guides at 65 / 70 thresholds.
            fig.add_hline(y=65, line_dash="dot", line_color="grey")
            fig.add_vline(x=65, line_dash="dot", line_color="grey")
            st.plotly_chart(fig, use_container_width=True)

            best = scat[scat["Matrix Class"] == "Best Crossover"].sort_values(
                "Composite Score", ascending=False)
            st.subheader("Best Crossover - high momentum AND high value")
            if best.empty:
                st.info("No Best Crossover stocks in this scan.")
            else:
                cols = [c for c in ["Symbol", "Company", "Sector", "CMP", "Composite Score",
                                    "Value Score", "Classification", "Value Classification",
                                    "Value Entry Style", "Value Trigger Price", "Risk Level"]
                        if c in best.columns]
                st.dataframe(best[cols], use_container_width=False, height=420,
                             column_config=SCREENER_COLCFG)

    # =====================================================================
    # 7) STOCK DEEP DIVE
    # =====================================================================
    with T["Stock Deep Dive"]:
        # The fragment isolates the dropdown re-run to JUST this section, so
        # changing the selected stock no longer resets the scroll position or
        # ejects you from the tab. Any rendering error shows a friendly message
        # instead of blanking out the page.
        dd_src = allstocks if not allstocks.empty else allc

        @_fragment
        def _stock_deep_dive():
            if dd_src.empty:
                st.info("Run a scan to deep-dive a stock.")
                return
            try:
                pick = st.selectbox("Select a stock", dd_src["Symbol"].tolist(),
                                    key="sdd_pick")
                r = dd_src[dd_src["Symbol"] == pick].iloc[0]
                cls = r["Classification"]
                left, right = st.columns([1.2, 1])
                with left:
                    mclass = r.get("Momentum Class", cls)
                    st.markdown(
                        f"### {r['Symbol']} - {r['Company']}\n"
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
                    st.plotly_chart(score_gauge(r.get("Composite Score", r["Score"])),
                                    use_container_width=True)
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
                # --- v2 Phase 2: pre-loaded fundamentals sub-scores (from CSV) ---
                if r.get("Fundamentals") == "Loaded":
                    gate = str(r.get("Fundamentals Quality Gate", "-"))
                    gate_color = ("#1e7d32" if gate == "Pass"
                                  else "#8b1e1e" if gate == "Fail" else "#555")
                    st.markdown(f"#### Fundamentals &nbsp; "
                                f"{badge('Quality Gate: ' + gate, gate_color)}",
                                unsafe_allow_html=True)
                    fcols = st.columns(4)
                    metric_card(fcols[0], "Quality", r.get("Quality Score", "-"), "#1f4e79")
                    metric_card(fcols[1], "Growth", r.get("Growth Score", "-"), "#1f4e79")
                    metric_card(fcols[2], "Balance Sheet", r.get("Balance-Sheet Score", "-"),
                                "#1f4e79", sub=("proxy" if r.get("BS Proxy") == "Yes" else ""))
                    metric_card(fcols[3], "Promoter", r.get("Promoter Score", "-"), "#1f4e79")
                    if int(r.get("Fundamentals Partial", 0) or 0) > 2:
                        st.caption("Some fundamental fields were missing - scores are partial.")
                elif r.get("Fundamentals") == "Missing":
                    st.caption("No fundamentals row for this symbol in your CSV.")
                st.markdown(f"#### Fundamentals (live) "
                            f"&nbsp;[Open on Screener.in &#128279;]({fundamentals.screener_url(pick)})")
                with st.expander("Load key fundamentals from Screener.in", expanded=False):
                    if st.button("Fetch fundamentals", key=f"fund_{pick}"):
                        with st.spinner("Fetching from Screener.in ..."):
                            fund = cached_fundamentals(pick)
                        if not fund:
                            st.info("Fundamentals unavailable (Screener may be blocking this "
                                    "server, or the symbol differs on Screener). Use the link above.")
                        else:
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
            except Exception as exc:
                st.error(f"Could not render Stock Deep Dive: {exc}. "
                         "Try selecting a different stock.")

        _stock_deep_dive()

    # =====================================================================
    # BACKTEST (momentum-only, point-in-time, no look-ahead)
    # =====================================================================
    with T["Backtest"]:
        st.markdown("## Backtest (Momentum)")
        st.caption("Replays the momentum signals on PAST dates using only the data "
                   "available then (no look-ahead), and measures the forward 15- and "
                   "30-day return per bucket. Runs on the prices already downloaded "
                   "for this scan - no new downloads.")
        st.warning("The VALUE / Quality-Growth scan is NOT backtested: it needs "
                   "point-in-time fundamentals we do not have. Using today's "
                   "fundamentals on past prices is look-ahead bias. Momentum only here.")
        pdata = st.session_state.get("price_data") or {}
        if not pdata:
            st.info("Run a scan first - the backtest reuses that scan's price data.")
        else:
            bc = st.columns(3)
            look_years = bc[0].selectbox("Look-back window", ["1 year", "2 years", "3 years"],
                                         index=1, key="bt_look")
            freq = bc[1].selectbox("Sample frequency", ["Weekly", "Fortnightly", "Monthly"],
                                   index=2, key="bt_freq")
            min_sc = bc[2].number_input("Min score for Strong gate", 0, 100, 65, 5, key="bt_score")
            look_map = {"1 year": 252, "2 years": 504, "3 years": 756}
            step_map = {"Weekly": 5, "Fortnightly": 10, "Monthly": 21}
            n_syms = len([s for s in pdata if s != "^NSEI"])
            st.caption(f"Universe in cache: {n_syms} stocks. A wider window / finer "
                       "frequency is more thorough but slower.")
            if st.button("Run backtest", type="primary", key="bt_run"):
                prog = st.progress(0.0)
                stat = st.empty()

                def _bp(done, total, sym):
                    prog.progress(done / total)
                    stat.write(f"Backtesting {done}/{total}: {sym}")

                with st.spinner("Replaying historical signals (no new downloads) ..."):
                    bt = BT.run_momentum_backtest(
                        pdata, period_lookback_days=look_map[look_years],
                        sample_step=step_map[freq], min_score=int(min_sc), progress=_bp)
                prog.empty(); stat.empty()
                st.session_state["bt_result"] = bt

            bt = st.session_state.get("bt_result")
            if bt and not bt.get("summary", pd.DataFrame()).empty:
                summ = bt["summary"]
                st.caption(f"Based on {bt['samples']} point-in-time stock-date samples.")
                # Bar chart: avg forward returns per bucket vs baseline
                melt = summ.melt(id_vars="Bucket",
                                 value_vars=["Avg 15D Ret %", "Avg 30D Ret %"],
                                 var_name="Horizon", value_name="Avg Return %")
                st.plotly_chart(px.bar(melt, x="Bucket", y="Avg Return %", color="Horizon",
                                       barmode="group", title="Average forward return by bucket"),
                                use_container_width=True)
                wmelt = summ.melt(id_vars="Bucket",
                                  value_vars=["Win% 15D", "Win% 30D"],
                                  var_name="Horizon", value_name="Win %")
                st.plotly_chart(px.bar(wmelt, x="Bucket", y="Win %", color="Horizon",
                                       barmode="group", title="Win-rate (% of samples positive)"),
                                use_container_width=True)
                st.subheader("Backtest summary")
                st.caption("Compare each signal bucket against the Baseline row. A "
                           "bucket that beats baseline on BOTH avg return and win-rate "
                           "is adding edge. Small sample counts are not reliable.")
                st.dataframe(summ, use_container_width=True, hide_index=True)
                st.caption("Honest limits: per-stock signals only (RS-percentile / "
                           "sector-bonus features not replayed); regime assumed Neutral; "
                           "no costs/slippage; survivorship - the cache only holds names "
                           "that exist today. Treat as directional, not a P&L promise.")
            elif bt:
                st.info("No signal samples in the chosen window. Try a wider look-back "
                        "or finer frequency.")

    with T["Rejected / Failed"]:
        if rejected is not None and not rejected.empty and "Reason" in rejected:
            rc = rejected["Reason"].value_counts().reset_index()
            rc.columns = ["Reason", "Count"]
            # Summary cards
            jc = st.columns(3)
            metric_card(jc[0], "Rejected", len(rejected), "#8b1e1e")
            metric_card(jc[1], "Failed tickers", len(failed), "#555")
            metric_card(jc[2], "Top reason", rc.iloc[0]["Reason"], "#6e0b0b",
                        sub=f"{int(rc.iloc[0]['Count'])} stocks")
            st.write("")
            st.plotly_chart(px.bar(rc, x="Count", y="Reason", orientation="h",
                                   title="Why stocks were rejected",
                                   color_discrete_sequence=["#8b1e1e"]), use_container_width=True)
            st.divider()
            summary_table(rejected, key="rejected_tbl", title="Rejected stocks",
                          caption="Stocks that failed a hard gate or scored below the "
                                  "minimum. Use the filters to find a specific name.",
                          detail_cols=list(rejected.columns))
        else:
            st.info("No rejected stocks.")
        st.subheader("Failed tickers (download error / no data)")
        st.caption("These symbols returned no usable Yahoo data - usually a renamed "
                   "or delisted ticker.")
        if failed:
            st.dataframe(pd.DataFrame({"Failed Tickers": failed}),
                         use_container_width=True, height=240, hide_index=True)
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

        # ---- Phase 2: Value-scanner prompts ----
        VAL_TASK = ("Check latest news, results, sector strength, technical "
                    "structure, support/resistance, and whether this is suitable "
                    "for a 15-30 day swing trade. Do not recommend entry if the "
                    "confirmation condition is not met. Rank them best to weakest.\n\n")

        def _val_prompt(df, header):
            if df is None or df.empty:
                return header + VAL_TASK + "(No stocks in this bucket.)"
            lines = []
            for _, r in df.iterrows():
                lines.append(
                    f"- {r['Symbol']} ({r['Company']}, {r['Sector']}): CMP {r['CMP']}, "
                    f"Value {r.get('Value Score', '-')}, Composite {r.get('Composite Score', '-')}, "
                    f"Entry: {r.get('Value Entry Style', '-')}, "
                    f"Trigger {r.get('Value Trigger Price', '-')}, "
                    f"Invalidation {r.get('Value Invalidation Level', '-')}, "
                    f"RSI {r.get('RSI 14', '-')}, RS {r.get('RS Score', '-')}, "
                    f"Risk {r.get('Risk Level', '-')}")
            return header + VAL_TASK + "\n".join(lines)

        st.subheader("6. Value Reversal Ready")
        st.code(_val_prompt(val_reversal,
                "Review these VALUE REVERSAL READY NSE stocks. "), language="text")
        st.subheader("7. Value Base Forming")
        st.code(_val_prompt(val_base,
                "Review these VALUE BASE FORMING NSE stocks. Setup is developing "
                "but breakout NOT yet confirmed. "), language="text")
        st.subheader("8. Momentum + Value Crossover (Best Crossover)")
        best_cross = (allstocks[allstocks.get("Matrix Class") == "Best Crossover"]
                      .sort_values("Composite Score", ascending=False)
                      if "Matrix Class" in allstocks.columns else pd.DataFrame())
        st.code(_val_prompt(best_cross,
                "Review these BEST CROSSOVER NSE stocks - high momentum AND high "
                "value at the same time. "), language="text")

        # ---- 9. My Holdings Review (Phase-1 addition) ----
        if holdings_df is not None and not holdings_df.empty:
            st.subheader("6. My Holdings Review")
            lines = [
                ("Review my NSE Zerodha holdings. For each: classify as Hold, "
                 "Trail, Add only on confirmation, Reduce, or Exit Review. Use "
                 "the action label + technical context provided. DO NOT recommend "
                 "blind averaging down. Flag risk concentration if any single "
                 "holding > 15% of portfolio.\n")]
            for _, r in holdings_df.iterrows():
                lines.append(
                    f"- {r['symbol']} (qty {r.get('quantity', '-')}, "
                    f"avg {r.get('avg_cost', '-')}, CMP {r.get('CMP') if pd.notna(r.get('CMP')) else r.get('ltp', '-')}, "
                    f"P&L% {r.get('pnl_pct', '-')}, wt {r.get('portfolio_weight_pct', '-')}%): "
                    f"{r.get('Classification', 'No scanner data')}, "
                    f"Composite {r.get('Composite Score', '-')}, RS {r.get('RS Score', '-')}, "
                    f"Trigger {r.get('Trigger Price', '-')}, "
                    f"Invalidation {r.get('Invalidation Level', '-')}, "
                    f"Action: {r.get('holding_action', '-')}")
            st.code("\n".join(lines), language="text")

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
                p = export_outputs(result, holdings_df=holdings_df)
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
