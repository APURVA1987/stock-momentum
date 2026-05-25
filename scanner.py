# scanner.py
# -----------------------------------------------------------------------------
# This file contains the SCANNING LOGIC:
#   1. Download daily price data from Yahoo Finance (yfinance).
#   2. Calculate all indicators for each stock (incl. ADX, ATR, candle strength).
#   3. Score each stock out of 100 using a transparent component system.
#   4. CLASSIFY each stock into:
#         - Strong Breakout / Actionable
#         - Wait for Confirmation
#         - Early Watchlist
#         - Rejected
#   5. Build trigger price, alert price, invalidation level, entry/SL/targets.
#   6. Measure Market Regime (Nifty) and Sector Strength.
#
# NOTE FOR NON-CODERS:
# - The TUNABLE NUMBERS live in the "THRESHOLDS" block just below. Change a
#   number there to adjust how strict the scanner is. Sidebar controls override
#   the most common ones (RSI, volume ratio, minimum score).
# -----------------------------------------------------------------------------

import datetime as dt
import time

import numpy as np
import pandas as pd
import yfinance as yf

import indicators as ind


NIFTY_SYMBOL = "^NSEI"   # Yahoo symbol for Nifty 50 (used for relative strength)

# -----------------------------------------------------------------------------
# THRESHOLDS YOU CAN TUNE  (most are also exposed in the sidebar)
# -----------------------------------------------------------------------------
RSI_STRONG = 60.0            # RSI needed for a STRONG breakout
ADX_TREND = 20.0             # ADX above this = trend present
ADX_STRONG = 25.0            # ADX above this = strong trend
CLOSE_POS_STRONG = 0.75      # candle closed in top 25% of its range
MAX_EXT_FROM_20DMA = 10.0    # avoid entries more than this % above the 20 DMA
MAX_EXT_FROM_200DMA = 40.0   # "overextended" from 200 DMA beyond this %
MIN_RR = 1.5                 # minimum acceptable risk-reward ratio
SCORE_STRONG = 80            # score band: Strong
SCORE_WAIT = 65              # score band: Wait for Confirmation
SCORE_WATCH_FLOOR = 55       # score band: Early Watchlist floor (also reject cut)


# -----------------------------------------------------------------------------
# 1. DATA DOWNLOAD
# -----------------------------------------------------------------------------
def download_history(symbol_ns: str, period: str = "5y", retries: int = 2) -> pd.DataFrame:
    """Download daily OHLCV data for one NSE symbol (already ending in '.NS').

    `retries` = extra attempts if the download comes back empty (fights temporary
    Yahoo Finance rate-limits on shared cloud servers).
    Returns a clean DataFrame (Open/High/Low/Close/Volume) or EMPTY on failure.
    """
    df = None
    for attempt in range(retries + 1):
        try:
            df = yf.download(
                symbol_ns, period=period, interval="1d",
                auto_adjust=True, progress=False, threads=False,
            )
        except Exception:
            df = None
        if df is not None and not df.empty:
            break
        if attempt < retries:
            time.sleep(1.5)

    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    keep = ["Open", "High", "Low", "Close", "Volume"]
    df = df[[c for c in keep if c in df.columns]].copy()
    df = df.dropna(subset=["Close"])
    return df


def get_nifty_context(period: str = "5y") -> dict:
    """Download Nifty 50 ONCE and work out the overall MARKET REGIME.

    Regime = Bullish / Neutral / Weak based on:
      - Nifty close > Nifty 50 DMA
      - Nifty close > Nifty 200 DMA
      - Nifty 20-day return positive
    """
    nifty = download_history(NIFTY_SYMBOL, period=period)
    if nifty.empty or len(nifty) < 200:
        return {"nifty_20d_return": np.nan, "regime": "Unknown"}

    close = nifty["Close"]
    n_ret20 = ind.pct_change_over(close, 20)
    n_50 = float(ind.sma(close, 50).iloc[-1])
    n_200 = float(ind.sma(close, 200).iloc[-1])
    n_close = float(close.iloc[-1])

    checks = [n_close > n_50, n_close > n_200, (n_ret20 or 0) > 0]
    passed = sum(bool(c) for c in checks)
    if passed == 3:
        regime = "Bullish"
    elif passed <= 1:
        regime = "Weak"
    else:
        regime = "Neutral"

    return {
        "nifty_20d_return": n_ret20,
        "regime": regime,
        "nifty_close": round(n_close, 2),
        "nifty_50dma": round(n_50, 2),
        "nifty_200dma": round(n_200, 2),
    }


# -----------------------------------------------------------------------------
# 2. INDICATOR PACK (everything we need for ONE stock)
# -----------------------------------------------------------------------------
def compute_metrics(df: pd.DataFrame, nifty_20d_return: float,
                    retest_window: int = 60, retest_tol: float = 7.0) -> dict:
    """Calculate every indicator for a single stock. Returns a dict, or None if
    there is not enough history (need ~200 days for the 200 DMA)."""
    if df.empty or len(df) < 220:
        return None

    close, high, low, volume = df["Close"], df["High"], df["Low"], df["Volume"]

    # --- Moving averages ---
    dma20, dma50, dma200 = ind.sma(close, 20), ind.sma(close, 50), ind.sma(close, 200)
    cmp = float(close.iloc[-1])
    ma20, ma50, ma200 = float(dma20.iloc[-1]), float(dma50.iloc[-1]), float(dma200.iloc[-1])
    slope200 = ind.slope_pct(dma200, 30)

    # --- 52-week high / previous high ---
    last_year = close.tail(252)
    high_52w = float(last_year.max())
    prev_52w_high = float(last_year.iloc[:-1].max()) if len(last_year) > 1 else high_52w
    latest_high = float(high.iloc[-1])
    dist_from_52w = (cmp / high_52w - 1.0) * 100.0
    dist_from_200 = (cmp / ma200 - 1.0) * 100.0
    dist_from_20 = (cmp / ma20 - 1.0) * 100.0

    # --- RSI / ADX / ATR / candle strength ---
    rsi14 = float(ind.rsi(close, 14).iloc[-1])
    adx14 = float(ind.adx(high, low, close, 14).iloc[-1])
    atr14 = float(ind.atr(high, low, close, 14).iloc[-1])
    cpos = ind.close_position(high=latest_high, low=float(low.iloc[-1]), close=cmp)

    # --- Volume ---
    avg_vol_20 = float(volume.tail(20).mean())
    latest_vol = float(volume.iloc[-1])
    vol_ratio = (latest_vol / avg_vol_20) if avg_vol_20 > 0 else np.nan

    # --- Returns / relative strength ---
    ret_20d = ind.pct_change_over(close, 20)
    rel_strength = (ret_20d - nifty_20d_return) if (not np.isnan(nifty_20d_return)
                                                    and not np.isnan(ret_20d)) else np.nan

    # --- 200 DMA retest analysis ---
    win = min(retest_window, len(df) - 1)
    recent = df.tail(win)
    recent_dma200 = dma200.tail(win)
    low_60 = float(recent["Low"].min())

    gap_to_200 = (recent["Low"] / recent_dma200 - 1.0) * 100.0
    retest_mask = (gap_to_200 >= -2.0) & (gap_to_200 <= retest_tol)
    retested = bool(retest_mask.any())
    retest_date = "-"
    if retested:
        retest_date = pd.Timestamp(retest_mask[retest_mask].index[-1]).strftime("%Y-%m-%d")

    days_below_200 = int((recent["Close"] < recent_dma200).sum())

    # --- Pullback volume (was volume drying up during the dip?) ---
    pull_vol = float(recent["Volume"][retest_mask].mean()) if retested else np.nan
    volume_dryup = bool((not np.isnan(pull_vol)) and pull_vol < avg_vol_20)

    # --- 5-day breakout sustain (avoids one-day false breakouts) ---
    last5 = close.tail(5)
    near_break = (last5 >= prev_52w_high * 0.98).sum()
    breakout_sustain = bool(near_break >= 3)

    # --- Breakout status ---
    if cmp > prev_52w_high:
        breakout_status = "Above previous 52W high"
    elif dist_from_52w >= -5.0:
        breakout_status = "Within 5% of 52W high"
    else:
        breakout_status = "Not near breakout"

    # --- Risk-reward (volatility-aware) ---
    atr_stop = cmp - 1.5 * atr14
    stop_used = max(atr_stop, low_60)          # the closer (higher) of the two
    if stop_used >= cmp:                        # safety fallback
        stop_used = cmp * 0.95
    target1 = cmp * 1.08
    risk = cmp - stop_used
    risk_reward = (target1 - cmp) / risk if risk > 0 else np.nan

    return {
        # display values (rounded)
        "CMP": round(cmp, 2), "20 DMA": round(ma20, 2), "50 DMA": round(ma50, 2),
        "200 DMA": round(ma200, 2),
        "200 DMA Slope %": round(slope200, 3) if not np.isnan(slope200) else np.nan,
        "52W High": round(high_52w, 2), "Prev 52W High": round(prev_52w_high, 2),
        "Distance from 52W High %": round(dist_from_52w, 2),
        "Distance from 200 DMA %": round(dist_from_200, 2),
        "Distance from 20 DMA %": round(dist_from_20, 2),
        "RSI 14": round(rsi14, 2),
        "ADX 14": round(adx14, 2) if not np.isnan(adx14) else np.nan,
        "ATR 14": round(atr14, 2) if not np.isnan(atr14) else np.nan,
        "Close Position": round(cpos, 2),
        "Volume Ratio": round(vol_ratio, 2) if not np.isnan(vol_ratio) else np.nan,
        "20-Day Return %": round(ret_20d, 2) if not np.isnan(ret_20d) else np.nan,
        "Nifty 20-Day Return %": round(nifty_20d_return, 2) if not np.isnan(nifty_20d_return) else np.nan,
        "Relative Strength %": round(rel_strength, 2) if not np.isnan(rel_strength) else np.nan,
        "Retest Date": retest_date,
        "Days Below 200 DMA": days_below_200,
        "Breakout Status": breakout_status,
        "Risk Reward": round(risk_reward, 2) if not np.isnan(risk_reward) else np.nan,
        # booleans / raw values reused by scoring + trade plan
        "_retested": retested, "_volume_dryup": volume_dryup,
        "_breakout_sustain": breakout_sustain,
        "_high_52w": high_52w, "_prev_52w_high": prev_52w_high,
        "_latest_high": latest_high, "_ma20": ma20, "_ma50": ma50, "_ma200": ma200,
        "_atr": atr14, "_swing_low": low_60, "_ret20_raw": ret_20d,
    }


# -----------------------------------------------------------------------------
# 3. SCORING (out of 100) — transparent, component-based
# -----------------------------------------------------------------------------
def score_components(m: dict, sector_is_top: bool, regime_supportive: bool) -> tuple:
    """Return (total_score, components_dict). Each bucket is documented so the
    'detailed view' can show exactly where the points came from."""
    cmp = m["CMP"]
    rs = m["Relative Strength %"]
    rs = 0 if (rs is None or np.isnan(rs)) else rs
    nifty_ret = m["Nifty 20-Day Return %"]
    ret20 = m["20-Day Return %"]
    vr = m["Volume Ratio"]
    vr = 0 if (vr is None or np.isnan(vr)) else vr
    adx = m["ADX 14"]
    adx = 0 if (adx is None or np.isnan(adx)) else adx
    rr = m["Risk Reward"]
    rr = 0 if (rr is None or np.isnan(rr)) else rr

    # Trend Quality (25)
    trend = 0
    if cmp > m["200 DMA"]: trend += 7
    if m["50 DMA"] > m["200 DMA"]: trend += 6
    if (m["200 DMA Slope %"] or 0) > 0: trend += 6
    if cmp > m["20 DMA"] and cmp > m["50 DMA"]: trend += 6

    # Pullback Quality (20)
    pullback = 0
    if m["_retested"]: pullback += 8
    if m["Days Below 200 DMA"] <= 5: pullback += 5
    if m["_volume_dryup"]: pullback += 4
    if cmp > m["20 DMA"] and cmp > m["50 DMA"] and m["Days Below 200 DMA"] <= 5:
        pullback += 3   # clean recovery

    # Momentum Quality (20)
    momentum = 0
    if m["RSI 14"] > RSI_STRONG: momentum += 5
    if adx > ADX_TREND: momentum += 5
    if rs > 0: momentum += 5
    if (ret20 is not None and not np.isnan(ret20) and ret20 > 0
            and (nifty_ret is None or np.isnan(nifty_ret) or ret20 > nifty_ret)):
        momentum += 5

    # Breakout Quality (20)
    breakout = 0
    if m["Distance from 52W High %"] >= -5: breakout += 5
    if cmp > m["_prev_52w_high"]: breakout += 6
    if vr > 1.5: breakout += 5
    if m["Close Position"] > CLOSE_POS_STRONG: breakout += 4

    # Risk Quality (15)
    risk = 0
    if m["Distance from 20 DMA %"] <= MAX_EXT_FROM_20DMA: risk += 4
    if m["Distance from 200 DMA %"] <= MAX_EXT_FROM_200DMA: risk += 3
    if rr >= MIN_RR: risk += 4
    if regime_supportive: risk += 4

    total = trend + pullback + momentum + breakout + risk
    # Sector strength is informational + a tiny tie-break bonus, capped at 100
    # (the 5 buckets above already total 100, so we never inflate past it).
    if sector_is_top:
        total = min(100, total + 2)

    comps = {"Trend Score": trend, "Pullback Score": pullback,
             "Momentum Score": momentum, "Breakout Score": breakout,
             "Risk Score": risk}
    return int(total), comps


def risk_level(score: int, days_below_200: int) -> str:
    if score >= SCORE_STRONG and days_below_200 <= 3:
        return "Low Risk"
    if score < SCORE_WAIT or days_below_200 > 10:
        return "High Risk"
    return "Medium Risk"


# -----------------------------------------------------------------------------
# 4. CLASSIFICATION
# -----------------------------------------------------------------------------
def classify(m: dict, score: int, min_rsi: float, min_vol_ratio: float,
             regime: str, min_score: int) -> tuple:
    """Return (classification, reason). Reason is only meaningful for Rejected."""
    cmp = m["CMP"]
    rs = m["Relative Strength %"]
    rs = 0 if (rs is None or np.isnan(rs)) else rs
    vr = m["Volume Ratio"]
    vr = 0 if (vr is None or np.isnan(vr)) else vr

    # --- D. Rejected (hard fails) ---
    if cmp <= m["200 DMA"]:
        return "Rejected", "Below 200 DMA"
    if (m["200 DMA Slope %"] or 0) <= 0:
        return "Rejected", "200 DMA falling"
    if not m["_retested"]:
        return "Rejected", "No recent 200 DMA retest"
    if rs < 0:
        return "Rejected", "Relative strength negative"
    if vr < 1.0:
        return "Rejected", "Liquidity/volume too weak"
    if score < min_score:
        return "Rejected", f"Score {score} below minimum {min_score}"

    # --- A. Strong Breakout / Actionable (all gates + high score) ---
    strong_gates = [
        cmp > m["20 DMA"], cmp > m["50 DMA"], cmp > m["200 DMA"],
        m["50 DMA"] > m["200 DMA"], (m["200 DMA Slope %"] or 0) > 0,
        m["RSI 14"] >= max(RSI_STRONG, min_rsi - 0),
        rs > 0,
        (cmp > m["_prev_52w_high"]) or (m["Distance from 52W High %"] >= -2.0),
        vr >= min_vol_ratio,
        m["Days Below 200 DMA"] <= 5,
    ]
    if score >= SCORE_STRONG and all(strong_gates):
        return "Strong Breakout / Actionable", ""

    # --- B. Wait for Confirmation (good score, setup developing) ---
    if score >= SCORE_WAIT:
        return "Wait for Confirmation", ""

    # --- C. Early Watchlist ---
    if score >= SCORE_WATCH_FLOOR:
        return "Early Watchlist", ""

    return "Rejected", f"Score {score} below minimum {min_score}"


def confirmation_needed(m: dict, min_vol_ratio: float) -> str:
    """Plain-English reason a 'Wait for Confirmation' stock is not yet actionable."""
    cmp = m["CMP"]
    rs = m["Relative Strength %"]
    rs = 0 if (rs is None or np.isnan(rs)) else rs
    vr = m["Volume Ratio"]
    vr = 0 if (vr is None or np.isnan(vr)) else vr

    reasons = []
    if not (cmp > m["_prev_52w_high"] or m["Distance from 52W High %"] >= -2.0):
        reasons.append("close above 52W high (trigger) with volume > 1.5x")
    if m["RSI 14"] < RSI_STRONG:
        reasons.append("RSI to cross 60")
    if vr < min_vol_ratio:
        reasons.append("volume expansion above 1.5x average")
    if cmp < m["50 DMA"]:
        reasons.append("price to sustain above 50 DMA")
    if not m["_breakout_sustain"]:
        reasons.append("2 consecutive closes above breakout level")
    if rs <= 0:
        reasons.append("relative strength vs Nifty to turn positive")

    if not reasons:
        return "Avoid fresh entry until stock closes above trigger price"
    return "Wait for " + "; ".join(reasons[:2])


def trigger_levels(m: dict, risk: str) -> dict:
    """Trigger price, suggested alert price, and invalidation level."""
    cmp = m["CMP"]
    if cmp < m["50 DMA"]:
        trigger = m["50 DMA"]                 # must reclaim the 50 DMA first
    elif cmp < m["_high_52w"]:
        trigger = m["_high_52w"]              # break the 52W high
    else:
        trigger = m["_latest_high"]           # above 52W high but needs follow-through

    alert = trigger * 0.99                     # 1% below trigger

    # Invalidation depends on how much risk we are willing to take.
    if risk == "Low Risk":
        invalidation = m["_swing_low"]
    elif risk == "Medium Risk":
        invalidation = m["50 DMA"]
    else:
        invalidation = m["200 DMA"]

    return {
        "Trigger Price": round(trigger, 2),
        "Suggested Alert Price": round(alert, 2),
        "Invalidation Level": round(invalidation, 2),
    }


# -----------------------------------------------------------------------------
# 5. TRADE PLAN (entry / stop / targets)
# -----------------------------------------------------------------------------
def trade_plan(m: dict) -> dict:
    cmp = m["CMP"]
    ma20 = m["20 DMA"]
    swing_low = m["_swing_low"]
    atr_stop = round(cmp - 1.5 * m["_atr"], 2)

    if m["Breakout Status"] == "Above previous 52W high":
        entry_zone = "Already breakout; buy only if sustains above breakout level"
    elif m["Breakout Status"] == "Within 5% of 52W high":
        entry_zone = "Watch for breakout above 52W high"
    else:
        entry_zone = "Not near breakout"

    stop_loss = (f"Conservative: below 20 DMA ({round(ma20, 2)}); "
                 f"ATR-based: {atr_stop}; Safer: below swing low ({round(swing_low, 2)})")

    return {
        "Entry Zone": entry_zone,
        "Stop Loss": stop_loss,
        "Target 1": f"{round(cmp * 1.08, 2)} (+8%); trail if momentum continues",
        "Target 2": f"{round(cmp * 1.12, 2)} (+12%); trail if momentum continues",
    }


# -----------------------------------------------------------------------------
# 6. SECTOR STRENGTH
# -----------------------------------------------------------------------------
def build_sector_strength(stocks: list) -> pd.DataFrame:
    """Average 20-day return per sector across all stocks that had valid data."""
    rows = [{"Sector": s["sector"], "ret": s["m"].get("_ret20_raw")} for s in stocks]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Sector", "Avg 20-Day Return %", "Stocks", "Rank"])
    g = df.groupby("Sector")["ret"].agg(["mean", "count"]).reset_index()
    g = g.rename(columns={"mean": "Avg 20-Day Return %", "count": "Stocks"})
    g["Avg 20-Day Return %"] = g["Avg 20-Day Return %"].round(2)
    g = g.sort_values("Avg 20-Day Return %", ascending=False).reset_index(drop=True)
    g["Rank"] = range(1, len(g) + 1)
    return g


# -----------------------------------------------------------------------------
# 7. ROW BUILDER (one full record for a classified stock)
# -----------------------------------------------------------------------------
def _build_row(s, m, score, comps, classification, sector_rank_map, min_vol_ratio, regime):
    risk = risk_level(score, m["Days Below 200 DMA"])
    plan = trade_plan(m)
    trig = trigger_levels(m, risk)
    conf = confirmation_needed(m, min_vol_ratio) if classification == "Wait for Confirmation" else "-"

    remark = f"{classification} | {risk}"
    if regime == "Weak":
        remark += " | Trade with caution (weak market)"

    return {
        "Symbol": s["symbol"], "Company": s["company"], "Sector": s["sector"],
        "Market Cap Category": s["cap"], "CMP": m["CMP"], "Score": score,
        "Classification": classification,
        "RSI 14": m["RSI 14"], "ADX 14": m["ADX 14"], "ATR 14": m["ATR 14"],
        "Close Position": m["Close Position"], "Volume Ratio": m["Volume Ratio"],
        "52W High": m["52W High"], "Distance from 52W High %": m["Distance from 52W High %"],
        "20 DMA": m["20 DMA"], "50 DMA": m["50 DMA"], "200 DMA": m["200 DMA"],
        "Distance from 200 DMA %": m["Distance from 200 DMA %"],
        "Distance from 20 DMA %": m["Distance from 20 DMA %"],
        "Retest Date": m["Retest Date"], "Days Below 200 DMA": m["Days Below 200 DMA"],
        "Relative Strength %": m["Relative Strength %"],
        "20-Day Return %": m["20-Day Return %"],
        "Nifty 20-Day Return %": m["Nifty 20-Day Return %"],
        "Breakout Status": m["Breakout Status"],
        "Confirmation Needed": conf,
        "Trigger Price": trig["Trigger Price"],
        "Suggested Alert Price": trig["Suggested Alert Price"],
        "Invalidation Level": trig["Invalidation Level"],
        "Entry Zone": plan["Entry Zone"], "Stop Loss": plan["Stop Loss"],
        "Target 1": plan["Target 1"], "Target 2": plan["Target 2"],
        "Risk Reward": m["Risk Reward"],
        "Sector Strength Rank": sector_rank_map.get(s["sector"], "-"),
        "Risk Level": risk,
        "Trend Score": comps["Trend Score"], "Pullback Score": comps["Pullback Score"],
        "Momentum Score": comps["Momentum Score"], "Breakout Score": comps["Breakout Score"],
        "Risk Score": comps["Risk Score"],
        "Final Remark": remark,
    }


# -----------------------------------------------------------------------------
# 8. MAIN SCAN
# -----------------------------------------------------------------------------
def run_scan(universe_df: pd.DataFrame, period: str = "5y",
             retest_window: int = 60, retest_tol: float = 7.0,
             min_rsi: float = 55.0, min_vol_ratio: float = 1.5,
             min_score: int = 55, progress_callback=None) -> dict:
    """Scan the whole universe and return categorised result tables."""
    ctx = get_nifty_context(period=period)
    nifty_20d = ctx["nifty_20d_return"]
    regime = ctx["regime"]
    regime_supportive = regime in ("Bullish", "Neutral")

    stocks = []            # phase-1 store (so we can compute sector strength first)
    rejected_rows = []
    failed = []

    total = len(universe_df)
    for i, row in enumerate(universe_df.itertuples(index=False), start=1):
        symbol = str(row.symbol).strip().upper()
        company = getattr(row, "company", symbol)
        sector = getattr(row, "sector", "-")
        cap = getattr(row, "market_cap_category", "-")
        try:
            df = download_history(f"{symbol}.NS", period=period)
            if df.empty:
                failed.append(symbol)
            else:
                m = compute_metrics(df, nifty_20d, retest_window, retest_tol)
                if m is None:
                    rejected_rows.append({
                        "Symbol": symbol, "Company": company, "Sector": sector,
                        "Market Cap Category": cap, "Score": "-",
                        "Classification": "Rejected",
                        "Reason": "Data missing / insufficient history"})
                else:
                    stocks.append({"symbol": symbol, "company": company,
                                   "sector": sector, "cap": cap, "m": m})
        except Exception as e:
            failed.append(symbol)
            rejected_rows.append({
                "Symbol": symbol, "Company": company, "Sector": sector,
                "Market Cap Category": cap, "Score": "-",
                "Classification": "Rejected", "Reason": f"Error: {e}"})
        if progress_callback:
            progress_callback(i, total, symbol)

    # --- Sector strength (needs all stocks first) ---
    sector_df = build_sector_strength(stocks)
    top_sectors = list(sector_df.head(3)["Sector"]) if not sector_df.empty else []
    sector_rank_map = dict(zip(sector_df["Sector"], sector_df["Rank"])) if not sector_df.empty else {}

    # --- Phase 2: score + classify ---
    strong_rows, wait_rows, watch_rows = [], [], []
    for s in stocks:
        m = s["m"]
        score, comps = score_components(m, s["sector"] in top_sectors, regime_supportive)
        classification, reason = classify(m, score, min_rsi, min_vol_ratio, regime, min_score)
        if classification == "Rejected":
            rejected_rows.append({
                "Symbol": s["symbol"], "Company": s["company"], "Sector": s["sector"],
                "Market Cap Category": s["cap"], "Score": score,
                "Classification": "Rejected", "Reason": reason})
            continue
        rowd = _build_row(s, m, score, comps, classification, sector_rank_map,
                          min_vol_ratio, regime)
        if classification == "Strong Breakout / Actionable":
            strong_rows.append(rowd)
        elif classification == "Wait for Confirmation":
            wait_rows.append(rowd)
        else:
            watch_rows.append(rowd)

    # --- Build & sort each table ---
    def finalise(rows, sort_cols, ascending):
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values(sort_cols, ascending=ascending).reset_index(drop=True)
            df.insert(0, "Rank", range(1, len(df) + 1))
        return df

    strong_df = finalise(strong_rows, ["Score", "Relative Strength %"], [False, False])
    # Wait: score desc, distance-from-52W-high ascending (closer first), rel-str desc
    wait_df = finalise(wait_rows,
                       ["Score", "Distance from 52W High %", "Relative Strength %"],
                       [False, True, False])
    watch_df = finalise(watch_rows, ["Score"], [False])
    rejected_df = pd.DataFrame(rejected_rows)

    return {
        "strong": strong_df, "wait": wait_df, "watchlist": watch_df,
        "rejected": rejected_df, "failed": failed,
        "sector_strength": sector_df, "top_sectors": top_sectors,
        "regime": regime, "nifty_context": ctx,
        "universe_count": total,
        "scanned_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# -----------------------------------------------------------------------------
# 9. CLAUDE / CHATGPT REVIEW PROMPTS (two separate prompts)
# -----------------------------------------------------------------------------
def build_strong_prompt(strong_df: pd.DataFrame) -> str:
    intro = (
        "Review these STRONG BREAKOUT NSE stocks from my 200 DMA retest momentum "
        "scanner for IMMEDIATE 15-30 day swing trade suitability. Check latest news, "
        "sector strength, result quality, technical structure, breakout validity, "
        "support/resistance, and risk. Rank them from best to weakest.\n\n"
    )
    if strong_df is None or strong_df.empty:
        return intro + "(No strong breakout stocks in this scan.)"
    lines = []
    for _, r in strong_df.iterrows():
        lines.append(
            f"- {r['Symbol']} ({r['Company']}, {r['Sector']}, {r['Market Cap Category']}): "
            f"CMP {r['CMP']}, Score {r['Score']}, {r['Breakout Status']}, RSI {r['RSI 14']}, "
            f"ADX {r['ADX 14']}, VolRatio {r['Volume Ratio']}, RelStr {r['Relative Strength %']}%, "
            f"Risk {r['Risk Level']}")
    return intro + "\n".join(lines)


def build_wait_prompt(wait_df: pd.DataFrame) -> str:
    intro = (
        "Review these WAIT-FOR-CONFIRMATION NSE stocks from my 200 DMA retest "
        "momentum scanner. The setup is developing but the breakout is NOT yet "
        "confirmed. For each, assess whether the confirmation condition is likely "
        "to trigger and how to plan the trade. IMPORTANT: Do not recommend entry "
        "unless the confirmation condition is met.\n\n"
    )
    if wait_df is None or wait_df.empty:
        return intro + "(No wait-for-confirmation stocks in this scan.)"
    lines = []
    for _, r in wait_df.iterrows():
        lines.append(
            f"- {r['Symbol']} ({r['Company']}, {r['Sector']}): CMP {r['CMP']}, "
            f"Trigger {r['Trigger Price']}, Confirmation: {r['Confirmation Needed']}, "
            f"RSI {r['RSI 14']}, VolRatio {r['Volume Ratio']}, "
            f"RelStr {r['Relative Strength %']}%, Risk {r['Risk Level']}")
    return intro + "\n".join(lines)
