# scanner.py
# -----------------------------------------------------------------------------
# This file contains the actual SCANNING LOGIC:
#   1. Download daily price data from Yahoo Finance (yfinance).
#   2. Calculate all the indicators for each stock.
#   3. Apply the 200 DMA retest momentum rules.
#   4. Score each stock out of 100 and assign a risk level.
#   5. Build entry / stop-loss / target suggestions.
#   6. Return a clean table of QUALIFIED stocks + a table of REJECTED stocks.
#
# NOTE FOR NON-CODERS:
# - You usually only tweak the NUMBERS in the rules (e.g. min RSI = 55).
#   Those numbers are passed in from the dashboard sidebar, so you can change
#   them there without editing code.
# -----------------------------------------------------------------------------

import datetime as dt
import time

import numpy as np
import pandas as pd
import yfinance as yf

import indicators as ind


# This is the Yahoo Finance symbol for the Nifty 50 index.
# We use it to measure "relative strength" (is the stock beating the market?).
NIFTY_SYMBOL = "^NSEI"


# -----------------------------------------------------------------------------
# 1. DATA DOWNLOAD
# -----------------------------------------------------------------------------
def download_history(symbol_ns: str, period: str = "5y", retries: int = 2) -> pd.DataFrame:
    """Download daily OHLCV data for one NSE symbol (already ending in '.NS').

    `period` can be '2y', '3y', '5y'.
    `retries` = how many extra attempts to make if the download comes back empty
    (this fights temporary Yahoo Finance rate-limits on shared cloud servers).
    Returns a clean DataFrame with columns: Open, High, Low, Close, Volume.
    Returns an EMPTY DataFrame if the download still fails (so the app never crashes).
    """
    df = None
    for attempt in range(retries + 1):
        try:
            df = yf.download(
                symbol_ns,
                period=period,
                interval="1d",
                auto_adjust=True,   # adjust for splits/dividends
                progress=False,
                threads=False,
            )
        except Exception:
            df = None

        # If we got data, stop retrying.
        if df is not None and not df.empty:
            break
        # Otherwise wait a moment and try again (helps with rate-limits).
        if attempt < retries:
            time.sleep(1.5)

    if df is None or df.empty:
        return pd.DataFrame()

    # Newer yfinance can return multi-level columns. Flatten them.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    keep = ["Open", "High", "Low", "Close", "Volume"]
    df = df[[c for c in keep if c in df.columns]].copy()
    df = df.dropna(subset=["Close"])
    return df


def get_nifty_20day_return(period: str = "5y") -> float:
    """20-day % return of the Nifty 50 index, used for relative strength."""
    nifty = download_history(NIFTY_SYMBOL, period=period)
    if nifty.empty:
        return np.nan
    return ind.pct_change_over(nifty["Close"], 20)


# -----------------------------------------------------------------------------
# 2. INDICATOR PACK (everything we need for ONE stock)
# -----------------------------------------------------------------------------
def compute_metrics(df: pd.DataFrame, nifty_20d_return: float,
                    retest_window: int = 60, retest_tol: float = 7.0) -> dict:
    """Calculate every indicator from the price table for a single stock.

    Returns a dictionary of values. Returns None if there is not enough data
    (we need at least ~200 days to compute the 200 DMA reliably).
    """
    if df.empty or len(df) < 220:
        return None

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    # --- Moving averages ---
    dma20 = ind.sma(close, 20)
    dma50 = ind.sma(close, 50)
    dma200 = ind.sma(close, 200)

    cmp = float(close.iloc[-1])
    ma20 = float(dma20.iloc[-1])
    ma50 = float(dma50.iloc[-1])
    ma200 = float(dma200.iloc[-1])

    # --- 200 DMA slope over last 30 days (rising or falling?) ---
    slope200 = ind.slope_pct(dma200, 30)

    # --- 52-week high (last 252 trading days ~ 1 year) ---
    last_year = close.tail(252)
    high_52w = float(last_year.max())
    # Previous 52W high EXCLUDING the latest candle (today's bar).
    prev_52w_high = float(last_year.iloc[:-1].max()) if len(last_year) > 1 else high_52w

    dist_from_52w = (cmp / high_52w - 1.0) * 100.0      # negative = below high
    dist_from_200 = (cmp / ma200 - 1.0) * 100.0         # % above/below 200 DMA

    # --- RSI 14 ---
    rsi14 = float(ind.rsi(close, 14).iloc[-1])

    # --- Volume ---
    avg_vol_20 = float(volume.tail(20).mean())
    latest_vol = float(volume.iloc[-1])
    vol_ratio = (latest_vol / avg_vol_20) if avg_vol_20 > 0 else np.nan

    # --- Returns / relative strength ---
    ret_20d = ind.pct_change_over(close, 20)
    rel_strength = (ret_20d - nifty_20d_return) if not np.isnan(nifty_20d_return) else np.nan

    # --- 200 DMA retest analysis over the retest window (default 60 days) ---
    win = min(retest_window, len(df) - 1)
    recent = df.tail(win)
    recent_dma200 = dma200.tail(win)

    low_60 = float(recent["Low"].min())

    # How close did each day's LOW get to the 200 DMA, as a % above the 200 DMA?
    # We look for a dip that came within `retest_tol`% of the 200 DMA
    # (the rule wants the pullback low to be roughly 3%-7% from the 200 DMA).
    gap_to_200 = (recent["Low"] / recent_dma200 - 1.0) * 100.0
    # A valid retest = low came down to between 3% and `retest_tol`% above 200 DMA
    # OR slightly pierced it (small negative gap allowed, down to -2%).
    retest_mask = (gap_to_200 >= -2.0) & (gap_to_200 <= retest_tol)

    retested = bool(retest_mask.any())
    retest_date = None
    if retested:
        # Nearest (most recent) retest date.
        retest_date = retest_mask[retest_mask].index[-1]
        retest_date = pd.Timestamp(retest_date).strftime("%Y-%m-%d")

    # Did the low come within the tighter 3%-7% band of the 200 DMA?
    within_band = bool(((gap_to_200 >= 3.0) & (gap_to_200 <= retest_tol)).any()
                       or retested)

    # Days spent BELOW the 200 DMA in the window.
    days_below_200 = int((recent["Close"] < recent_dma200).sum())

    # --- Breakout status ---
    if cmp > prev_52w_high:
        breakout_status = "Above previous 52W high"
    elif dist_from_52w >= -5.0:
        breakout_status = "Within 5% of 52W high"
    else:
        breakout_status = "Not near breakout"

    return {
        "CMP": round(cmp, 2),
        "20 DMA": round(ma20, 2),
        "50 DMA": round(ma50, 2),
        "200 DMA": round(ma200, 2),
        "200 DMA Slope %": round(slope200, 3) if not np.isnan(slope200) else np.nan,
        "52W High": round(high_52w, 2),
        "Prev 52W High": round(prev_52w_high, 2),
        "Distance from 52W High %": round(dist_from_52w, 2),
        "Distance from 200 DMA %": round(dist_from_200, 2),
        "RSI 14": round(rsi14, 2),
        "Avg Vol 20": round(avg_vol_20, 0),
        "Volume Ratio": round(vol_ratio, 2) if not np.isnan(vol_ratio) else np.nan,
        "20-Day Return %": round(ret_20d, 2) if not np.isnan(ret_20d) else np.nan,
        "Nifty 20-Day Return %": round(nifty_20d_return, 2) if not np.isnan(nifty_20d_return) else np.nan,
        "Relative Strength %": round(rel_strength, 2) if not np.isnan(rel_strength) else np.nan,
        "Low 60D": round(low_60, 2),
        "Retest Within Band": within_band,
        "Retested 200 DMA": retested,
        "Retest Date": retest_date if retest_date else "-",
        "Days Below 200 DMA": days_below_200,
        "Breakout Status": breakout_status,
        # raw values reused later for SL/target:
        "_swing_low": low_60,
    }


# -----------------------------------------------------------------------------
# 3. SCORING (out of 100)
# -----------------------------------------------------------------------------
def score_stock(m: dict, min_rsi: float) -> int:
    """Add up points for each condition the stock meets. Max = 100."""
    score = 0
    if m["CMP"] > m["200 DMA"]:
        score += 10
    if m["50 DMA"] > m["200 DMA"]:
        score += 10
    if not np.isnan(m["200 DMA Slope %"]) and m["200 DMA Slope %"] > 0:
        score += 10
    if m["Retested 200 DMA"]:
        score += 15
    if m["Days Below 200 DMA"] <= 10:
        score += 10
    if m["CMP"] > m["20 DMA"] and m["CMP"] > m["50 DMA"]:
        score += 10
    if m["RSI 14"] > min_rsi:
        score += 10
    if not np.isnan(m["Volume Ratio"]) and m["Volume Ratio"] > 1.5:
        score += 10
    if m["Breakout Status"] in ("Above previous 52W high", "Within 5% of 52W high"):
        score += 10
    if not np.isnan(m["Relative Strength %"]) and m["Relative Strength %"] > 0:
        score += 5
    return score


def risk_level(score: int, days_below_200: int) -> str:
    """Translate score + days below 200 DMA into a simple risk label."""
    if score >= 80 and days_below_200 <= 3:
        return "Low Risk"
    if score < 65 or days_below_200 > 10:
        return "High Risk"
    return "Medium Risk"


# -----------------------------------------------------------------------------
# 4. ENTRY / STOP-LOSS / TARGET
# -----------------------------------------------------------------------------
def trade_plan(m: dict) -> dict:
    """Build human-readable entry zone, stop loss, and 15-30 day targets."""
    cmp = m["CMP"]
    ma20 = m["20 DMA"]
    swing_low = m["_swing_low"]

    if m["Breakout Status"] == "Above previous 52W high":
        entry_zone = "Already breakout; buy only if sustains above breakout level"
    elif m["Breakout Status"] == "Within 5% of 52W high":
        entry_zone = "Watch for breakout above 52W high"
    else:
        entry_zone = "Not near breakout"

    stop_loss = (
        f"Conservative SL below 20 DMA ({round(ma20, 2)}); "
        f"Safer SL below recent swing low ({round(swing_low, 2)})"
    )

    target1 = round(cmp * 1.08, 2)   # +8%
    target2 = round(cmp * 1.12, 2)   # +12%

    return {
        "Entry Zone": entry_zone,
        "Stop Loss": stop_loss,
        "Target 1": f"{target1} (+8%); trail if momentum continues",
        "Target 2": f"{target2} (+12%); trail if momentum continues",
    }


# -----------------------------------------------------------------------------
# 5. QUALIFICATION (does the stock pass the rules?)
# -----------------------------------------------------------------------------
def evaluate(m: dict, min_rsi: float, min_vol_ratio: float) -> tuple:
    """Return (qualified: bool, reject_reason: str, tag: str).

    `tag` is 'Strong Breakout', 'Watchlist', or '' when not qualified.
    """
    # --- Primary trend (must be uptrend) ---
    if m["CMP"] <= m["200 DMA"]:
        return False, "Below 200 DMA", ""
    if m["50 DMA"] <= m["200 DMA"]:
        return False, "50 DMA below 200 DMA", ""
    if np.isnan(m["200 DMA Slope %"]) or m["200 DMA Slope %"] <= 0:
        return False, "200 DMA falling", ""

    # --- Pullback (must have retested 200 DMA, not lived below it) ---
    if not m["Retested 200 DMA"]:
        return False, "No recent 200 DMA retest", ""
    if m["Days Below 200 DMA"] > 10:
        return False, "Spent too long below 200 DMA", ""

    # --- Recovery ---
    if not (m["CMP"] > m["20 DMA"] and m["CMP"] > m["50 DMA"]):
        return False, "Not recovered above 20/50 DMA", ""
    if m["RSI 14"] <= min_rsi:
        return False, "RSI weak", ""

    # --- Breakout proximity ---
    if m["Breakout Status"] == "Not near breakout":
        return False, "Not near 52W high", ""
    if np.isnan(m["Relative Strength %"]) or m["Relative Strength %"] <= 0:
        return False, "Relative strength negative", ""

    # --- Volume separates Watchlist vs Strong Breakout ---
    vr = m["Volume Ratio"]
    if np.isnan(vr) or vr < 1.2:
        return False, "Volume weak", ""

    tag = "Strong Breakout" if vr >= min_vol_ratio else "Watchlist"
    return True, "", tag


# -----------------------------------------------------------------------------
# 6. MAIN SCAN LOOP (over the whole universe)
# -----------------------------------------------------------------------------
def run_scan(universe_df: pd.DataFrame,
             period: str = "5y",
             retest_window: int = 60,
             retest_tol: float = 7.0,
             min_rsi: float = 55.0,
             min_vol_ratio: float = 1.5,
             min_score: int = 65,
             progress_callback=None) -> dict:
    """Scan every stock in `universe_df`.

    `progress_callback(done, total, symbol)` is called after each stock so the
    dashboard can update a progress bar. It is optional.

    Returns a dict with: qualified (DataFrame), rejected (DataFrame),
    failed (list of symbols), nifty_return (float).
    """
    # Download Nifty ONCE (not per stock) for relative strength.
    nifty_20d = get_nifty_20day_return(period=period)

    qualified_rows = []
    rejected_rows = []
    failed = []

    total = len(universe_df)
    for i, row in enumerate(universe_df.itertuples(index=False), start=1):
        symbol = str(row.symbol).strip().upper()
        company = getattr(row, "company", symbol)
        sector = getattr(row, "sector", "-")
        cap = getattr(row, "market_cap_category", "-")
        symbol_ns = f"{symbol}.NS"

        try:
            df = download_history(symbol_ns, period=period)
            if df.empty:
                failed.append(symbol)
                if progress_callback:
                    progress_callback(i, total, symbol)
                continue

            m = compute_metrics(df, nifty_20d, retest_window, retest_tol)
            if m is None:
                rejected_rows.append({
                    "Symbol": symbol, "Company": company, "Sector": sector,
                    "Market Cap Category": cap, "Reason": "Data missing / insufficient history",
                })
                if progress_callback:
                    progress_callback(i, total, symbol)
                continue

            qualified, reason, tag = evaluate(m, min_rsi, min_vol_ratio)
            score = score_stock(m, min_rsi)

            if not qualified or score < min_score:
                rejected_rows.append({
                    "Symbol": symbol, "Company": company, "Sector": sector,
                    "Market Cap Category": cap,
                    "Reason": reason if reason else f"Score {score} below minimum {min_score}",
                    "Score": score,
                })
                if progress_callback:
                    progress_callback(i, total, symbol)
                continue

            plan = trade_plan(m)
            risk = risk_level(score, m["Days Below 200 DMA"])

            final_remark = f"{tag} | {risk}"

            qualified_rows.append({
                "Symbol": symbol,
                "Company": company,
                "Sector": sector,
                "Market Cap Category": cap,
                "CMP": m["CMP"],
                "20 DMA": m["20 DMA"],
                "50 DMA": m["50 DMA"],
                "200 DMA": m["200 DMA"],
                "52W High": m["52W High"],
                "Distance from 52W High %": m["Distance from 52W High %"],
                "Distance from 200 DMA %": m["Distance from 200 DMA %"],
                "Retest Date": m["Retest Date"],
                "Days Below 200 DMA": m["Days Below 200 DMA"],
                "RSI 14": m["RSI 14"],
                "Volume Ratio": m["Volume Ratio"],
                "20-Day Return %": m["20-Day Return %"],
                "Nifty 20-Day Return %": m["Nifty 20-Day Return %"],
                "Relative Strength %": m["Relative Strength %"],
                "Breakout Status": m["Breakout Status"],
                "Entry Zone": plan["Entry Zone"],
                "Stop Loss": plan["Stop Loss"],
                "Target 1": plan["Target 1"],
                "Target 2": plan["Target 2"],
                "Risk Level": risk,
                "Score": score,
                "Tag": tag,
                "Final Remark": final_remark,
            })

        except Exception as e:
            # Never let one bad ticker stop the whole scan.
            failed.append(symbol)
            rejected_rows.append({
                "Symbol": symbol, "Company": company, "Sector": sector,
                "Market Cap Category": cap, "Reason": f"Error: {e}",
            })

        if progress_callback:
            progress_callback(i, total, symbol)

    # Build result tables.
    qdf = pd.DataFrame(qualified_rows)
    if not qdf.empty:
        qdf = qdf.sort_values("Score", ascending=False).reset_index(drop=True)
        qdf.insert(0, "Rank", range(1, len(qdf) + 1))

    rdf = pd.DataFrame(rejected_rows)

    return {
        "qualified": qdf,
        "rejected": rdf,
        "failed": failed,
        "nifty_return": nifty_20d,
        "scanned_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# -----------------------------------------------------------------------------
# 7. CLAUDE / CHATGPT REVIEW PROMPT
# -----------------------------------------------------------------------------
def build_claude_prompt(qdf: pd.DataFrame) -> str:
    """Create a ready-to-paste prompt listing the shortlisted stocks."""
    intro = (
        "Review these shortlisted NSE stocks from my 200 DMA retest momentum "
        "scanner. Check latest news, sector strength, result quality, technical "
        "structure, breakout validity, support/resistance, risk, and suitability "
        "for 15-30 day swing trade. Rank them from best to weakest.\n\n"
    )
    if qdf is None or qdf.empty:
        return intro + "(No stocks qualified in this scan.)"

    lines = []
    for _, r in qdf.iterrows():
        lines.append(
            f"- {r['Symbol']} ({r['Company']}, {r['Sector']}, {r['Market Cap Category']}): "
            f"CMP {r['CMP']}, Score {r['Score']}, {r['Breakout Status']}, "
            f"RSI {r['RSI 14']}, RelStr {r['Relative Strength %']}%, "
            f"Risk {r['Risk Level']}"
        )
    return intro + "\n".join(lines)
