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
import os
import pickle
import time

import numpy as np
import pandas as pd
import yfinance as yf

import indicators as ind
import value as V
import fundamentals as F

# Folder for the optional LOCAL price cache (used only in "local mode").
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


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

# --- v2 (Phase 1): Spring / Pre-Breakout + Accumulation + liquidity floor ---
MAX_EXT_FROM_10DMA = 6.0       # pocket-pivot freshness (close not far above 10 DMA)
SPRING_READY_MIN = 70          # Spring Score needed for "Spring Ready"
SPRING_BASE_MAX_DEPTH = 25.0   # base must be tighter than 25% to be a coil
SPRING_BASE_MIN_LEN = 15       # base at least ~3 weeks old
VCP_MIN_CONTRACTIONS = 2       # min successive shrinking pullbacks
OBV_ACCUM_SLOPE_MIN = 0.0      # OBV rising while price flat = accumulation
# Liquidity floor: 20-day avg turnover (Rupees/day) by market-cap band.
MIN_TURNOVER_LARGE = 50_00_00_000   # Rs 50 Cr/day
MIN_TURNOVER_MID = 5_00_00_000      # Rs 5 Cr/day
MIN_TURNOVER_SMALL = 1_00_00_000    # Rs 1 Cr/day


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


def _extract_one(df, sym_ns):
    """Pull a single ticker's OHLCV out of a multi-ticker yf.download frame."""
    if df is None or df.empty:
        return None
    try:
        if isinstance(df.columns, pd.MultiIndex):
            if sym_ns not in df.columns.get_level_values(0):
                return None
            sub = df[sym_ns].copy()
        else:
            sub = df.copy()
        keep = ["Open", "High", "Low", "Close", "Volume"]
        sub = sub[[c for c in keep if c in sub.columns]].dropna(subset=["Close"])
        return sub if not sub.empty else None
    except Exception:
        return None


def download_batch(symbols, period: str = "5y", chunk: int = 50, retries: int = 2,
                   progress=None) -> dict:
    """Download MANY NSE symbols in a few BATCHED, threaded requests instead of
    one request per symbol.

    WHY: Yahoo rate-limits per request. For a 600+ stock universe, one-per-symbol
    means 600+ requests (rate-limited + slow). Batching ~50 tickers per call turns
    that into ~13 requests, which is far friendlier and much faster.

    Returns a dict {SYMBOL (no .NS): cleaned OHLCV DataFrame}. Missing/failed
    symbols are simply absent from the dict (the caller treats them as failed).
    `progress(done, total)` is called after each batch so the UI can show a bar.
    """
    out = {}
    syms_ns = [f"{str(s).strip().upper()}.NS" for s in symbols]
    total = len(syms_ns)
    done = 0
    for i in range(0, total, chunk):
        part = syms_ns[i:i + chunk]
        df = None
        for attempt in range(retries + 1):
            try:
                df = yf.download(part, period=period, interval="1d", auto_adjust=True,
                                 progress=False, threads=True, group_by="ticker")
            except Exception:
                df = None
            if df is not None and not df.empty:
                break
            if attempt < retries:
                time.sleep(2.0)   # brief pause before retrying a failed batch
        for sym_ns in part:
            sub = _extract_one(df, sym_ns)
            if sub is not None:
                out[sym_ns[:-3]] = sub      # strip ".NS"
        done += len(part)
        if progress:
            progress(done, total)
    return out


# -----------------------------------------------------------------------------
# LOCAL PRICE CACHE + HYBRID DOWNLOAD (Yahoo history + bhavcopy latest day)
# -----------------------------------------------------------------------------
def _cache_path(period):
    return os.path.join(DATA_DIR, f"price_cache_{period}.pkl")


def load_price_cache(period: str) -> dict:
    """Load the local {symbol: DataFrame} cache, or {} if none/unreadable."""
    p = _cache_path(period)
    if os.path.exists(p):
        try:
            with open(p, "rb") as f:
                return pickle.load(f)
        except Exception:
            return {}
    return {}


def save_price_cache(period: str, data: dict):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(_cache_path(period), "wb") as f:
            pickle.dump(data, f)
    except Exception:
        pass


def _overlay_bhavcopy(data: dict, bc) -> int:
    """Append/replace the latest official NSE day onto each Yahoo series.
    Returns how many symbols were updated."""
    if bc is None or bc.empty:
        return 0
    bdate = pd.Timestamp(bc["Date"].iloc[0]).normalize()
    n = 0
    for sym, df in data.items():
        if sym not in bc.index or df is None or df.empty:
            continue
        row = bc.loc[sym]
        if isinstance(row, pd.DataFrame):     # guard against duplicate symbols
            row = row.iloc[0]
        try:
            vals = [float(row["Open"]), float(row["High"]), float(row["Low"]),
                    float(row["Close"]), float(row["Volume"])]
        except Exception:
            continue
        last = df.index[-1].normalize()
        if bdate > last:                      # new day -> append
            df.loc[bdate] = vals
            n += 1
        elif bdate == last:                   # same day -> replace with official
            df.loc[df.index[-1], ["Open", "High", "Low", "Close", "Volume"]] = vals
            n += 1
    return n


# -----------------------------------------------------------------------------
# Intraday-bar handling
# -----------------------------------------------------------------------------
# During NSE market hours (Mon-Fri 09:15-15:30 IST) Yahoo returns a PARTIAL bar
# for today: Close = current LTP and Volume = only what has traded so far. That
# breaks the scanner because (a) Volume Ratio collapses (~0.2x at 11 AM) so the
# breakout-volume gate fails for almost every stock, and (b) MA comparisons
# flip noisily on a single tick. Dropping the partial bar gives consistent
# results whether you scan at 10 AM or after the close.
def _is_nse_market_hours_ist() -> bool:
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime, time as dtime
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        if now.weekday() >= 5:          # Sat / Sun
            return False
        return dtime(9, 15) <= now.time() <= dtime(15, 30)
    except Exception:
        return False


def _strip_intraday_bar(df):
    """Drop the last row if it's today (IST) AND the market is currently open
    AND the volume looks suspiciously partial. Safe: returns df unchanged when
    in doubt."""
    if df is None or df.empty or not _is_nse_market_hours_ist():
        return df
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        last_date = pd.Timestamp(df.index[-1]).date()
        if last_date == today_ist and len(df) >= 21:
            # Cross-check: partial bar's volume should be markedly below the
            # 20-day average. (Catches the case where Yahoo already gave EOD.)
            last_vol = float(df["Volume"].iloc[-1])
            avg20 = float(df["Volume"].iloc[-21:-1].mean())
            if avg20 > 0 and last_vol < avg20 * 0.85:
                return df.iloc[:-1]
    except Exception:
        pass
    return df


def _strip_intraday_all(data: dict) -> dict:
    """Apply _strip_intraday_bar to every symbol's history."""
    return {k: _strip_intraday_bar(v) for k, v in data.items()}


def download_universe(symbols, period="5y", local_mode=False, progress=None,
                      eod_only=True) -> dict:
    """Get OHLCV for the whole universe.

    Default (cloud): batched Yahoo download for all symbols.
    Local mode: reuse a local cache for fresh symbols (skipping Yahoo), download
    only the stale/missing ones from Yahoo, then overlay the latest NSE bhavcopy
    day, and save the cache. This makes repeated local daily runs fast and far
    less dependent on Yahoo.

    `eod_only=True` (default) drops the partial intraday bar during NSE market
    hours so the scan is consistent whether run at 10 AM or after close.
    """
    if not local_mode:
        data = download_batch(symbols, period=period, progress=progress)
        return _strip_intraday_all(data) if eod_only else data

    cache = load_price_cache(period)
    fresh_cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=6)
    data, need = {}, []
    for s in symbols:
        s = str(s).strip().upper()
        df = cache.get(s)
        if df is not None and not df.empty and df.index[-1].normalize() >= fresh_cutoff:
            data[s] = df.copy()
        else:
            need.append(s)
    if need:
        data.update(download_batch(need, period=period, progress=progress))

    # Overlay the latest official NSE close (local only).
    try:
        import bhavcopy
        bc = bhavcopy.fetch_bhavcopy()
        _overlay_bhavcopy(data, bc)
    except Exception:
        pass

    save_price_cache(period, data)
    return _strip_intraday_all(data) if eod_only else data


def load_sector_pe() -> dict:
    """Optional data/sector_pe.csv -> {sector_lower: median_pe}. Empty if absent."""
    path = os.path.join(DATA_DIR, "sector_pe.csv")
    if not os.path.exists(path):
        return {}
    try:
        df = pd.read_csv(path)
        cols = {c.strip().lower(): c for c in df.columns}
        sc = cols.get("sector"); pc = cols.get("median_pe") or cols.get("pe")
        if not sc or not pc:
            return {}
        return {str(r[sc]).strip().lower(): float(r[pc])
                for _, r in df.iterrows() if pd.notna(r[pc])}
    except Exception:
        return {}


def get_nifty_context(period: str = "5y") -> dict:
    """Download Nifty 50 ONCE and work out the overall MARKET REGIME.

    Regime = Bullish / Neutral / Weak based on:
      - Nifty close > Nifty 50 DMA
      - Nifty close > Nifty 200 DMA
      - Nifty 20-day return positive
    """
    nifty = download_history(NIFTY_SYMBOL, period=period)
    if nifty.empty or len(nifty) < 200:
        return {"nifty_20d_return": np.nan, "regime": "Unknown",
                "nifty_returns": {h: np.nan for h in (5, 20, 60, 120, 252)}}

    close = nifty["Close"]
    # Multi-timeframe Nifty returns (used for relative strength on each horizon).
    nifty_returns = {h: ind.pct_change_over(close, h) for h in (5, 20, 60, 120, 252)}
    n_ret20 = nifty_returns[20]
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
        "nifty_returns": nifty_returns,
        "regime": regime,
        "nifty_close": round(n_close, 2),
        "nifty_50dma": round(n_50, 2),
        "nifty_200dma": round(n_200, 2),
    }


# -----------------------------------------------------------------------------
# v2 (Section 11A): VCP contraction count
# -----------------------------------------------------------------------------
def _vcp_contractions(df: pd.DataFrame) -> int:
    """Count successive SHRINKING pullbacks (Volatility Contraction Pattern).

    Walk swing pivots over the window; each time a pullback's depth is smaller
    than the previous pullback's depth, that's one contraction. Returns the
    length of the final run of shrinking contractions ending at the last bar.
    """
    if df is None or len(df) < 20:
        return 0
    close = df["Close"].values
    # Find local peaks (a bar higher than its immediate neighbours).
    peaks = [i for i in range(1, len(close) - 1)
             if close[i] >= close[i - 1] and close[i] > close[i + 1]]
    if len(peaks) < 2:
        return 0
    # Depth of the pullback after each peak (peak -> following trough).
    depths = []
    for k in range(len(peaks)):
        start = peaks[k]
        end = peaks[k + 1] if k + 1 < len(peaks) else len(close) - 1
        trough = close[start:end + 1].min()
        if close[start] > 0:
            depths.append((close[start] - trough) / close[start] * 100)
    # Count the trailing run of strictly shrinking depths.
    run = 0
    for k in range(len(depths) - 1, 0, -1):
        if depths[k] < depths[k - 1]:
            run += 1
        else:
            break
    return int(run)


# -----------------------------------------------------------------------------
# 2. INDICATOR PACK (everything we need for ONE stock)
# -----------------------------------------------------------------------------
def compute_metrics(df: pd.DataFrame, nifty_returns: dict,
                    retest_window: int = 60, retest_tol: float = 7.0) -> dict:
    """Calculate every indicator for a single stock. Returns a dict, or None if
    there is not enough history (need ~200 days for the 200 DMA).

    `nifty_returns` is a dict {5,20,60,120,252: return%} from get_nifty_context,
    used to compute multi-timeframe relative strength.
    """
    if df.empty or len(df) < 220:
        return None

    close, high, low, volume = df["Close"], df["High"], df["Low"], df["Volume"]
    open_ = df["Open"]

    # --- Moving averages (100 DMA added for deep-dive chart) ---
    dma20, dma50, dma200 = ind.sma(close, 20), ind.sma(close, 50), ind.sma(close, 200)
    dma100 = ind.sma(close, 100)
    cmp = float(close.iloc[-1])
    ma20, ma50, ma200 = float(dma20.iloc[-1]), float(dma50.iloc[-1]), float(dma200.iloc[-1])
    ma100 = float(dma100.iloc[-1]) if not pd.isna(dma100.iloc[-1]) else np.nan
    slope200 = ind.slope_pct(dma200, 30)

    # --- 52-week high / previous high ---
    last_year = close.tail(252)
    high_52w = float(last_year.max())
    prev_52w_high = float(last_year.iloc[:-1].max()) if len(last_year) > 1 else high_52w
    latest_high = float(high.iloc[-1])
    dist_from_52w = (cmp / high_52w - 1.0) * 100.0
    dist_from_200 = (cmp / ma200 - 1.0) * 100.0
    dist_from_20 = (cmp / ma20 - 1.0) * 100.0
    dist_from_50 = (cmp / ma50 - 1.0) * 100.0

    # --- Gap up % (latest open vs previous close) ---
    gap_up = ((float(open_.iloc[-1]) / float(close.iloc[-2]) - 1.0) * 100.0
              if len(close) > 1 and float(close.iloc[-2]) > 0 else 0.0)

    # --- RSI / ADX / ATR / candle strength ---
    rsi14 = float(ind.rsi(close, 14).iloc[-1])
    adx14 = float(ind.adx(high, low, close, 14).iloc[-1])
    atr14 = float(ind.atr(high, low, close, 14).iloc[-1])
    cpos = ind.close_position(high=latest_high, low=float(low.iloc[-1]), close=cmp)

    # --- Volume ---
    avg_vol_20 = float(volume.tail(20).mean())
    latest_vol = float(volume.iloc[-1])
    vol_ratio = (latest_vol / avg_vol_20) if avg_vol_20 > 0 else np.nan

    # --- Multi-timeframe returns & relative strength (vs Nifty) ---
    rets = {h: ind.pct_change_over(close, h) for h in (5, 20, 60, 120, 252)}

    def rel(h):
        nr = nifty_returns.get(h, np.nan)
        if np.isnan(nr) or np.isnan(rets[h]):
            return np.nan
        return rets[h] - nr

    rs_tf = {h: rel(h) for h in (5, 20, 60, 120, 252)}
    ret_20d = rets[20]
    nifty_20d_return = nifty_returns.get(20, np.nan)
    rel_strength = rs_tf[20]   # keep the existing 20-day relative strength field

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

    # --- PHASE 2: Coiled / tightness metrics ---
    def rng_pct(k):
        seg = df.tail(k)
        return (float(seg["High"].max()) - float(seg["Low"].min())) / cmp * 100 if cmp > 0 else np.nan
    range_5d, range_10d, range_20d, range_60d = rng_pct(5), rng_pct(10), rng_pct(20), rng_pct(60)
    range_30d, range_90d = rng_pct(30), rng_pct(90)
    # Slope of the 50 DMA (Phase-2 value scanner).
    slope50 = ind.slope_pct(dma50, 30)
    atr50 = float(ind.atr(high, low, close, 50).iloc[-1])
    atr_contraction = (atr14 / atr50) if (atr50 and atr50 > 0) else np.nan
    avg_vol_10, avg_vol_50 = float(volume.tail(10).mean()), float(volume.tail(50).mean())
    vol_dryup_10 = (avg_vol_10 / avg_vol_50) if avg_vol_50 > 0 else np.nan
    lows10 = low.tail(10).values
    higher_lows = int(sum(1 for i in range(1, len(lows10)) if lows10[i] > lows10[i - 1]))

    # --- PHASE 2: Fresh momentum metrics ---
    ma20_rising = bool(dma20.iloc[-1] > dma20.iloc[-6]) if dma20.notna().sum() > 6 else False
    ma50_rising = bool(dma50.iloc[-1] > dma50.iloc[-11]) if dma50.notna().sum() > 11 else False
    high_20d = float(high.tail(20).max())
    near_20d_high = bool(cmp >= 0.98 * high_20d)
    at_20d_high = bool(cmp >= high_20d * 0.999)
    ma_aligned = bool(cmp > ma20 > ma50 > ma200)

    # --- PHASE 2: Pullback analysis ---
    lows_arr = recent["Low"].values
    idx_min = int(np.argmin(lows_arr)) if len(lows_arr) else 0
    fall_seg, rec_seg = recent.iloc[:idx_min + 1], recent.iloc[idx_min:]
    vol_on_fall = float(fall_seg["Volume"].mean()) if len(fall_seg) else np.nan
    vol_on_rec = float(rec_seg["Volume"].mean()) if len(rec_seg) else np.nan
    recovery_speed = int(len(rec_seg) - 1)
    pullback_duration = int(len(fall_seg) - 1)
    drawdown_52w = (low_60 / high_52w - 1.0) * 100 if high_52w > 0 else np.nan

    def gp(ma):
        return (low_60 / ma - 1.0) if (ma and not np.isnan(ma) and ma > 0) else np.nan
    cand = {"200 DMA Retest": gp(ma200), "100 DMA Bounce": gp(ma100),
            "50 DMA Bounce": gp(ma50), "20 DMA Bounce": gp(ma20)}
    ptype, best = "No Valid Pullback", None
    for name, g in cand.items():
        if g is None or np.isnan(g):
            continue
        if -0.03 <= g <= 0.05 and (best is None or abs(g) < abs(best[1])):
            best = (name, g)
    if best:
        ptype = best[0]
    elif days_below_200 > 0 and cmp > ma200:
        ptype = "Broken 200 DMA Recovery"

    # --- PHASE 2: Value-scanner specific metrics ---
    # Max drawdowns over 6m / 1y (negative pct values).
    hi_6m = float(close.tail(126).max()) if len(close) >= 126 else high_52w
    hi_1y = float(close.tail(252).max()) if len(close) >= 252 else high_52w
    lo_6m = float(close.tail(126).min()) if len(close) >= 126 else cmp
    lo_1y = float(close.tail(252).min()) if len(close) >= 252 else cmp
    max_dd_6m = (lo_6m / hi_6m - 1) * 100 if hi_6m > 0 else np.nan
    max_dd_1y = (lo_1y / hi_1y - 1) * 100 if hi_1y > 0 else np.nan

    # Lower-highs count over the last 10 sessions (mirror of higher_lows).
    highs10 = high.tail(10).values
    lower_highs = int(sum(1 for i in range(1, len(highs10)) if highs10[i] < highs10[i - 1]))

    # Fresh 3-month low flag: latest close within 0.5% of the prior 63-day min.
    recent3m = close.tail(63)
    fresh_3m_low = bool(len(recent3m) > 5
                        and close.iloc[-1] <= recent3m.iloc[:-1].min() * 1.005)

    # RSI recovery over the last ~2 weeks.
    rsi_series = ind.rsi(close, 14)
    rsi_change_2w = (float(rsi_series.iloc[-1] - rsi_series.iloc[-11])
                     if rsi_series.dropna().shape[0] > 11 else 0.0)

    # MACD bullish flag (12/26/9, manual EMA).
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_bullish = bool(macd_line.iloc[-1] > signal_line.iloc[-1] and macd_line.iloc[-1] > 0)

    # Up-day volume vs down-day volume over the last 30 days.
    last30 = df.tail(30)
    delta30 = last30["Close"].diff()
    up_v = float(last30["Volume"][delta30 > 0].mean()) if (delta30 > 0).any() else np.nan
    dn_v = float(last30["Volume"][delta30 < 0].mean()) if (delta30 < 0).any() else np.nan
    up_down_vol = (up_v / dn_v) if (dn_v and dn_v > 0 and not np.isnan(up_v)) else np.nan

    # Distance from 100 DMA.
    dist_from_100 = ((cmp / ma100 - 1) * 100) if (ma100 and ma100 > 0) else np.nan

    # ====================================================================
    # v2 PHASE 1: volume-accumulation, spring / pre-breakout, liquidity
    # ====================================================================
    ma10 = float(ind.sma(close, 10).iloc[-1])
    dist_from_10 = ((cmp / ma10 - 1) * 100) if ma10 > 0 else np.nan

    # On-Balance Volume + Accumulation/Distribution slopes
    obv_series = ind.obv(close, volume)
    ad_series = ind.ad_line(high, low, close, volume)
    obv_slope_raw = ind.linslope(obv_series, 20)
    obv_mean = float(obv_series.tail(20).abs().mean()) or 1.0
    obv_slope_pct = (obv_slope_raw / obv_mean * 100) if not np.isnan(obv_slope_raw) else np.nan
    ad_slope = ind.linslope(ad_series, 20)

    # Volume pocket: count of last 10 days where a DOWN day had very dry volume
    last10 = df.tail(10)
    d10 = last10["Close"].diff()
    vol_pocket_10 = int(((d10 < 0) & (last10["Volume"] < 0.6 * avg_vol_20)).sum())

    # Pocket pivot: today is an up-day whose volume tops the max down-day volume
    # of the prior 10 sessions, while holding above the 10 DMA.
    prior10 = df.iloc[-11:-1] if len(df) > 11 else df.tail(10)
    pd10 = prior10["Close"].diff()
    max_down_vol = float(prior10["Volume"][pd10 < 0].max()) if (pd10 < 0).any() else 0.0
    pocket_pivot = bool(close.iloc[-1] > close.iloc[-2] and latest_vol > max_down_vol
                        and cmp > ma10)

    # NR7 / inside bar (tight-bar signals)
    last7 = df.tail(7)
    bar_range = last7["High"] - last7["Low"]
    nr7 = bool(len(last7) == 7 and bar_range.iloc[-1] == bar_range.min())
    inside_bar = bool(len(df) >= 2 and high.iloc[-1] < high.iloc[-2]
                      and low.iloc[-1] > low.iloc[-2])

    # Base geometry over the last 40 sessions
    base40 = df.tail(40)
    base_high = float(base40["High"].max())
    base_low = float(base40["Low"].min())
    base_depth = ((base_high - base_low) / base_high * 100) if base_high > 0 else np.nan
    near_hi = base40["High"] >= base_high * 0.97
    base_length = int(len(base40) - (near_hi.values.argmax())) if near_hi.any() else 0

    # 52-week-high age (days since the high printed)
    yr = df.tail(252)
    hi_idx = int(yr["High"].values.argmax())
    high_52w_age = int(len(yr) - 1 - hi_idx)

    # 20-day average turnover (Rs/day)
    avg_turnover_20 = float((close.tail(20) * volume.tail(20)).mean())

    # VCP contraction count over last ~90 sessions
    vcp_contractions = _vcp_contractions(df.tail(90))

    tightness_ratio = (range_10d / range_60d) if (range_60d and range_60d > 0) else np.nan

    return {
        # display values (rounded)
        "CMP": round(cmp, 2), "20 DMA": round(ma20, 2), "50 DMA": round(ma50, 2),
        "200 DMA": round(ma200, 2),
        "200 DMA Slope %": round(slope200, 3) if not np.isnan(slope200) else np.nan,
        "52W High": round(high_52w, 2), "Prev 52W High": round(prev_52w_high, 2),
        "Distance from 52W High %": round(dist_from_52w, 2),
        "Distance from 200 DMA %": round(dist_from_200, 2),
        "Distance from 20 DMA %": round(dist_from_20, 2),
        "Distance from 50 DMA %": round(dist_from_50, 2),
        "Gap Up %": round(gap_up, 2),
        "RSI 14": round(rsi14, 2),
        "ADX 14": round(adx14, 2) if not np.isnan(adx14) else np.nan,
        "ATR 14": round(atr14, 2) if not np.isnan(atr14) else np.nan,
        "Close Position": round(cpos, 2),
        "Volume Ratio": round(vol_ratio, 2) if not np.isnan(vol_ratio) else np.nan,
        "20-Day Return %": round(ret_20d, 2) if not np.isnan(ret_20d) else np.nan,
        "Nifty 20-Day Return %": round(nifty_20d_return, 2) if not np.isnan(nifty_20d_return) else np.nan,
        "Relative Strength %": round(rel_strength, 2) if not np.isnan(rel_strength) else np.nan,
        # Multi-timeframe returns & relative strength
        "Return 5D %": round(rets[5], 2) if not np.isnan(rets[5]) else np.nan,
        "Return 20D %": round(rets[20], 2) if not np.isnan(rets[20]) else np.nan,
        "Return 60D %": round(rets[60], 2) if not np.isnan(rets[60]) else np.nan,
        "Return 120D %": round(rets[120], 2) if not np.isnan(rets[120]) else np.nan,
        "Return 252D %": round(rets[252], 2) if not np.isnan(rets[252]) else np.nan,
        "RS 5D %": round(rs_tf[5], 2) if not np.isnan(rs_tf[5]) else np.nan,
        "RS 20D %": round(rs_tf[20], 2) if not np.isnan(rs_tf[20]) else np.nan,
        "RS 60D %": round(rs_tf[60], 2) if not np.isnan(rs_tf[60]) else np.nan,
        "RS 120D %": round(rs_tf[120], 2) if not np.isnan(rs_tf[120]) else np.nan,
        "RS 252D %": round(rs_tf[252], 2) if not np.isnan(rs_tf[252]) else np.nan,
        "Retest Date": retest_date,
        "Days Below 200 DMA": days_below_200,
        "Breakout Status": breakout_status,
        "Risk Reward": round(risk_reward, 2) if not np.isnan(risk_reward) else np.nan,
        # Phase 2: coiled / fresh / pullback display values
        "Range 5D %": round(range_5d, 2) if not np.isnan(range_5d) else np.nan,
        "Range 10D %": round(range_10d, 2) if not np.isnan(range_10d) else np.nan,
        "Range 20D %": round(range_20d, 2) if not np.isnan(range_20d) else np.nan,
        "Range 30D %": round(range_30d, 2) if not np.isnan(range_30d) else np.nan,
        "Range 60D %": round(range_60d, 2) if not np.isnan(range_60d) else np.nan,
        "Range 90D %": round(range_90d, 2) if not np.isnan(range_90d) else np.nan,
        "50 DMA Slope %": round(slope50, 3) if not np.isnan(slope50) else np.nan,
        "Max Drawdown 6M %": round(max_dd_6m, 2) if not np.isnan(max_dd_6m) else np.nan,
        "Max Drawdown 1Y %": round(max_dd_1y, 2) if not np.isnan(max_dd_1y) else np.nan,
        "Lower Highs 10D": lower_highs,
        "RSI Change 2W": round(rsi_change_2w, 2),
        "Up/Down Vol Ratio": round(up_down_vol, 2) if not np.isnan(up_down_vol) else np.nan,
        "Distance from 100 DMA %": round(dist_from_100, 2) if not np.isnan(dist_from_100) else np.nan,
        # --- v2 Phase 1 display columns ---
        "10 DMA": round(ma10, 2),
        "Distance from 10 DMA %": round(dist_from_10, 2) if not np.isnan(dist_from_10) else np.nan,
        "OBV Slope 20D %": round(obv_slope_pct, 2) if not np.isnan(obv_slope_pct) else np.nan,
        "AD Slope 20D": round(ad_slope, 1) if not np.isnan(ad_slope) else np.nan,
        "Up/Down Vol Ratio 30D": round(up_down_vol, 2) if not np.isnan(up_down_vol) else np.nan,
        "Volume Pocket 10D": vol_pocket_10,
        "Pocket Pivot": "Yes" if pocket_pivot else "No",
        "NR7": "Yes" if nr7 else "No",
        "Inside Bar": "Yes" if inside_bar else "No",
        "VCP Contractions": vcp_contractions,
        "Tightness Ratio": round(tightness_ratio, 2) if not np.isnan(tightness_ratio) else np.nan,
        "Base Depth %": round(base_depth, 2) if not np.isnan(base_depth) else np.nan,
        "Base Length D": base_length,
        "52W High Age D": high_52w_age,
        "Avg Turnover 20D": round(avg_turnover_20, 0),
        "_macd_bullish": macd_bullish,
        "_fresh_3m_low": fresh_3m_low,
        "_lower_highs": lower_highs,
        "_slope50": slope50,
        "_ma10": ma10, "_obv_slope_pct": obv_slope_pct, "_ad_slope": ad_slope,
        "_pocket_pivot": pocket_pivot, "_nr7": nr7, "_inside_bar": inside_bar,
        "_vcp": vcp_contractions, "_tightness": tightness_ratio,
        "_base_depth": base_depth, "_base_length": base_length,
        "_high_52w_age": high_52w_age, "_avg_turnover20": avg_turnover_20,
        "_base_high": base_high, "_vol_pocket10": vol_pocket_10,
        "ATR 50": round(atr50, 2) if not np.isnan(atr50) else np.nan,
        "ATR Contraction": round(atr_contraction, 2) if not np.isnan(atr_contraction) else np.nan,
        "Volume Dryup 10D": round(vol_dryup_10, 2) if not np.isnan(vol_dryup_10) else np.nan,
        "Higher Lows 10D": higher_lows,
        "20D High": round(high_20d, 2),
        "Pullback Type": ptype,
        "Pullback Depth %": round(abs(drawdown_52w), 2) if not np.isnan(drawdown_52w) else np.nan,
        "Pullback Duration Days": pullback_duration,
        "Recovery Speed Days": recovery_speed,
        # booleans / raw values reused by scoring + trade plan
        "_retested": retested, "_volume_dryup": volume_dryup,
        "_ma20_rising": ma20_rising, "_ma50_rising": ma50_rising,
        "_near_20d_high": near_20d_high, "_at_20d_high": at_20d_high, "_ma_aligned": ma_aligned,
        "_range10": range_10d, "_range60": range_60d, "_atr_contraction": atr_contraction,
        "_vol_dryup10": vol_dryup_10, "_higher_lows": higher_lows,
        "_vol_on_fall": vol_on_fall, "_vol_on_rec": vol_on_rec,
        "_recovery_speed": recovery_speed, "_drawdown_52w": drawdown_52w, "_ptype": ptype,
        "_breakout_sustain": breakout_sustain,
        "_high_52w": high_52w, "_prev_52w_high": prev_52w_high,
        "_latest_high": latest_high, "_ma20": ma20, "_ma50": ma50, "_ma200": ma200,
        "_ma100": ma100, "_atr": atr14, "_swing_low": low_60, "_ret20_raw": ret_20d,
        "_ret60_raw": rets[60], "_gap_up": gap_up,
        "_above_50": cmp > ma50, "_above_200": cmp > ma200,
        "_rs20": rs_tf[20], "_rs60": rs_tf[60], "_rs120": rs_tf[120], "_rs252": rs_tf[252],
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


def _f(v, default=0.0):
    """Treat None/NaN as a default so comparisons never crash."""
    try:
        return default if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v)
    except (TypeError, ValueError):
        return default


# -----------------------------------------------------------------------------
# v2 Section 4A: liquidity floor
# -----------------------------------------------------------------------------
def is_illiquid(m: dict, cap: str) -> bool:
    """True if 20-day avg turnover is below the market-cap band's floor."""
    t = _f(m.get("_avg_turnover20"))
    c = str(cap or "").strip().lower()
    if "large" in c:
        return t < MIN_TURNOVER_LARGE
    if "mid" in c:
        return t < MIN_TURNOVER_MID
    return t < MIN_TURNOVER_SMALL   # small cap / holding / unknown


# -----------------------------------------------------------------------------
# v2 Section 10C: Volume Accumulation layer
# -----------------------------------------------------------------------------
def accumulation_score(m: dict) -> tuple:
    """Return (score 0-100, A/D State label)."""
    obv_sl = _f(m.get("_obv_slope_pct"))
    ad_sl = _f(m.get("_ad_slope"))
    udv = _f(m.get("Up/Down Vol Ratio 30D"), 1.0)
    pocket = _f(m.get("_vol_pocket10"))
    sc = 0
    # OBV slope (35)
    if obv_sl > 1.0: sc += 35
    elif obv_sl > 0.2: sc += 25
    elif obv_sl > 0: sc += 15
    # A/D slope (25)
    if ad_sl > 0: sc += 25
    elif ad_sl == 0: sc += 10
    # Up/down volume (25)
    if udv >= 1.3: sc += 25
    elif udv >= 1.1: sc += 15
    elif udv >= 1.0: sc += 8
    # Dry down-volume pockets (15)
    if pocket >= 4: sc += 15
    elif pocket >= 2: sc += 8
    sc = int(min(100, sc))
    state = "Accumulation" if sc >= 70 else ("Neutral" if sc >= 45 else "Distribution")
    return sc, state


# -----------------------------------------------------------------------------
# v2 Section 10A/10B: Pre-Breakout / Coiled Spring
# -----------------------------------------------------------------------------
def spring_score(m: dict, accum_score: float) -> tuple:
    """Return (score 0-100, spring_ready bool, trigger, alert)."""
    tight = _f(m.get("_tightness"), 9)
    atrc = _f(m.get("_atr_contraction"), 9)
    vcp = _f(m.get("_vcp"))
    obv_sl = _f(m.get("_obv_slope_pct"))
    udv = _f(m.get("Up/Down Vol Ratio 30D"), 0)
    vdry = _f(m.get("_vol_dryup10"), 9)
    d52 = _f(m.get("Distance from 52W High %"), -99)
    cmp_ = _f(m["CMP"]); ma50 = _f(m["50 DMA"]); ma200 = _f(m["200 DMA"])
    slope200 = _f(m.get("200 DMA Slope %"))
    base_len = _f(m.get("_base_length"))

    sc = 0
    # tightness (20)
    if tight <= 0.40: sc += 20
    elif tight <= 0.60: sc += 14
    elif tight <= 0.80: sc += 7
    # ATR contraction (15)
    if atrc < 0.70: sc += 15
    elif atrc < 0.85: sc += 10
    elif atrc < 1.0: sc += 4
    # VCP structure (15)
    if vcp >= 3: sc += 15
    elif vcp == 2: sc += 10
    elif vcp == 1: sc += 4
    # accumulation (15)
    if obv_sl > 0 and udv >= 1.1: sc += 15
    elif obv_sl > 0: sc += 8
    # volume dry-up (10)
    if vdry < 0.60: sc += 10
    elif vdry < 0.80: sc += 6
    # proximity to pivot (10)
    if d52 >= -5: sc += 10
    elif d52 >= -10: sc += 6
    elif d52 >= -15: sc += 3
    # trend backdrop (10)
    if cmp_ > ma50 > ma200 and slope200 > 0: sc += 10
    elif cmp_ > ma200: sc += 5
    # base maturity (5)
    if SPRING_BASE_MIN_LEN <= base_len <= 90: sc += 5
    # pocket-pivot bonus (10B)
    if str(m.get("Pocket Pivot")) == "Yes": sc += 5
    sc = int(min(100, sc))

    ready = bool(
        sc >= SPRING_READY_MIN and cmp_ > ma50 and cmp_ > ma200 and slope200 > 0
        and _f(m.get("_base_depth"), 99) <= SPRING_BASE_MAX_DEPTH
        and base_len >= SPRING_BASE_MIN_LEN and vcp >= VCP_MIN_CONTRACTIONS
        and obv_sl >= OBV_ACCUM_SLOPE_MIN and atrc < 0.85 and d52 >= -15
        and accum_score >= 45)        # not a Distribution state

    trigger = round(max(_f(m.get("_base_high")), _f(m.get("_prev_52w_high"))), 2)
    alert = round(trigger * 0.99, 2)
    return sc, ready, trigger, alert


# --- Breakout Quality (0-100): how clean/healthy is the breakout? ---
def breakout_quality(m: dict) -> tuple:
    bq = 0
    if m["CMP"] > m["_prev_52w_high"]: bq += 25      # above previous 52W high
    if _f(m["Volume Ratio"]) >= 1.5: bq += 20        # volume confirmation
    if _f(m["Close Position"]) >= 0.75: bq += 20     # strong candle close
    if m["_breakout_sustain"]: bq += 20              # 2/3 day sustain
    if _f(m["Distance from 20 DMA %"]) <= 10: bq += 15   # not overextended
    if bq >= 80: status = "Excellent"
    elif bq >= 60: status = "Good"
    elif bq >= 40: status = "Weak"
    else: status = "Failed"
    return bq, status


# --- Overextension / Do-Not-Chase: strong but too far for a fresh entry ---
def overextension(m: dict) -> tuple:
    reasons = []
    if _f(m["Distance from 20 DMA %"]) > 10: reasons.append("More than 10% above 20 DMA")
    if _f(m["Distance from 50 DMA %"]) > 20: reasons.append("More than 20% above 50 DMA")
    if _f(m["Distance from 200 DMA %"]) > 40: reasons.append("More than 40% above 200 DMA")
    if _f(m["RSI 14"]) > 75: reasons.append("RSI overheated (>75)")
    if _f(m["Gap Up %"]) > 5: reasons.append("Large gap up (>5%)")
    if _f(m["Risk Reward"], 99) < 1.2: reasons.append("Poor risk-reward (<1.2)")
    over = len(reasons) > 0
    # Suggested wait condition (first applicable).
    if _f(m["Distance from 20 DMA %"]) > 10:
        wait = "Wait for pullback to 20 DMA"
    elif _f(m["Distance from 50 DMA %"]) > 20 or _f(m["Distance from 200 DMA %"]) > 40:
        wait = "Wait for consolidation / breakout retest"
    elif _f(m["RSI 14"]) > 75:
        wait = "Wait for RSI to cool down"
    elif _f(m["Gap Up %"]) > 5:
        wait = "Wait for gap fill / consolidation"
    elif _f(m["Risk Reward"], 99) < 1.2:
        wait = "Avoid until risk-reward improves"
    else:
        wait = "-"
    return over, reasons, wait


def composite_class(score: int) -> str:
    if score >= 85: return "Elite Momentum"
    if score >= 75: return "Actionable Breakout"
    if score >= 65: return "Wait for Confirmation"
    if score >= 55: return "Early Watchlist"
    return "Ignore"


def sector_status_from_score(v: float) -> str:
    if v >= 75: return "Leading"
    if v >= 60: return "Improving"
    if v >= 40: return "Neutral"
    return "Weak"


# --- PHASE 2: Coiled / tight setup (range contraction before a breakout) ---
def coiled_score(m: dict, rs_score: float) -> tuple:
    """Return (score 0-100, is_coiled bool). Higher = tighter & readier."""
    r10, r60 = _f(m["_range10"], np.nan), _f(m["_range60"], np.nan)
    tight_ratio = (r10 / r60) if (r60 and not np.isnan(r60) and r60 > 0) else np.nan
    atrc = _f(m["_atr_contraction"], 99)
    vdry = _f(m["_vol_dryup10"], 99)
    d52 = _f(m["Distance from 52W High %"], -99)

    sc = 0
    # price tightness (25)
    if not np.isnan(tight_ratio):
        if tight_ratio <= 0.4: sc += 25
        elif tight_ratio <= 0.6: sc += 18
        elif tight_ratio <= 0.8: sc += 10
    # ATR contraction (20)
    if atrc < 0.70: sc += 20
    elif atrc < 0.85: sc += 12
    elif atrc < 1.0: sc += 5
    # volume dry-up (20)
    if vdry < 0.60: sc += 20
    elif vdry < 0.80: sc += 12
    elif vdry < 1.0: sc += 5
    # RS score (20)
    sc += round(_f(rs_score) / 100 * 20)
    # near 52W high (15)
    if d52 >= -3: sc += 15
    elif d52 >= -7: sc += 10
    elif d52 >= -10: sc += 5

    is_coiled = bool(
        m["CMP"] > m["50 DMA"] and m["CMP"] > m["200 DMA"] and d52 >= -10
        and atrc < 0.85 and vdry < 0.80 and _f(rs_score) >= 65
        and _f(m["Distance from 20 DMA %"]) <= 10
        and (not np.isnan(tight_ratio) and tight_ratio <= 0.7))
    return int(min(100, sc)), is_coiled


# --- PHASE 2: Fresh momentum ignition (new move, may have skipped 200 DMA) ---
def fresh_momentum_score(m: dict, rs_score: float) -> tuple:
    cmp = m["CMP"]
    vr = _f(m["Volume Ratio"])
    rsi = _f(m["RSI 14"])
    adx = _f(m["ADX 14"])
    sc = 0
    # MA alignment (25)
    if cmp > m["20 DMA"] > m["50 DMA"] > m["200 DMA"]: sc += 25
    elif cmp > m["50 DMA"] > m["200 DMA"]: sc += 12
    # volume expansion (20)
    if vr >= 1.5: sc += 20
    elif vr >= 1.2: sc += 10
    # RSI zone (15)
    if 55 <= rsi <= 72: sc += 15
    elif 50 <= rsi < 55 or 72 < rsi <= 78: sc += 7
    # ADX / trend strength (15)
    if adx > 25: sc += 15
    elif adx > 20: sc += 10
    elif adx > 15: sc += 5
    # 20D breakout (15)
    if m["_at_20d_high"]: sc += 15
    elif m["_near_20d_high"]: sc += 8
    # RS score (10)
    sc += round(_f(rs_score) / 100 * 10)

    is_fresh = bool(
        m["_ma_aligned"] and m["_ma20_rising"] and m["_ma50_rising"] and vr >= 1.5
        and 55 <= rsi <= 72 and (adx > 20 or m["_ma20_rising"]) and m["_near_20d_high"]
        and _f(m["_rs20"]) > 0 and _f(rs_score) >= 70)
    return int(min(100, sc)), is_fresh


# --- PHASE 2: Pullback quality (how healthy was the dip-and-recover?) ---
def pullback_quality(m: dict) -> tuple:
    """Return (score 0-100, remark)."""
    ptype = m["_ptype"]
    vfall, vrec = _f(m["_vol_on_fall"], np.nan), _f(m["_vol_on_rec"], np.nan)
    rec_days = _f(m["_recovery_speed"], 999)
    depth = abs(_f(m["_drawdown_52w"], 99))
    cmp = m["CMP"]

    sc = 0
    # respected a moving average (25)
    if ptype in ("20 DMA Bounce", "50 DMA Bounce", "100 DMA Bounce", "200 DMA Retest"):
        sc += 25
    elif ptype == "Broken 200 DMA Recovery":
        sc += 12
    # fall volume lower than recovery volume (25)
    if not np.isnan(vfall) and not np.isnan(vrec):
        if vfall < vrec: sc += 25
        elif vfall < vrec * 1.1: sc += 12
    # quick recovery (20)
    if rec_days <= 15: sc += 20
    elif rec_days <= 30: sc += 12
    elif rec_days <= 45: sc += 6
    # controlled drawdown (15)
    if depth <= 15: sc += 15
    elif depth <= 25: sc += 8
    # reclaimed 20/50 DMA (15)
    if cmp > m["20 DMA"] and cmp > m["50 DMA"]: sc += 15
    elif cmp > m["50 DMA"]: sc += 8

    remark = (f"{ptype}; fall {'<' if (not np.isnan(vfall) and not np.isnan(vrec) and vfall < vrec) else '>='} "
              f"recovery volume; recovered in ~{int(rec_days)}d; drawdown {round(depth, 1)}%")
    return int(min(100, sc)), remark


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
def _build_row(s, m, score, comps, classification, sector_rank_map, min_vol_ratio,
               regime, sector_status_map=None):
    risk = risk_level(score, m["Days Below 200 DMA"])
    plan = trade_plan(m)
    trig = trigger_levels(m, risk)
    conf = confirmation_needed(m, min_vol_ratio) if classification == "Wait for Confirmation" else "-"

    remark = f"{classification} | {risk}"
    if regime == "Weak":
        remark += " | Trade with caution (weak market)"

    row = {
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
    # Phase 2: value-scanner columns + Matrix class.
    sec_status = sector_status_map.get(s["sector"], "") if isinstance(
        sector_status_map, dict) else ""
    val = V.score_value(m, sector_status=sec_status)
    row.update(val)
    row["Matrix Class"] = V.matrix_class(row.get("Composite Score"), val["Value Score"])
    row["Matrix Remark"] = V.MATRIX_REMARKS.get(row["Matrix Class"], "")

    # --- v2 Phase 1: accumulation + spring + liquidity + readiness ---
    acc_sc, acc_state = accumulation_score(m)
    spr_sc, spr_ready, spr_trig, spr_alert = spring_score(m, acc_sc)
    illiquid = is_illiquid(m, s.get("cap"))
    # Liquidity floor: an illiquid name can't be Spring-Ready / actionable.
    if illiquid:
        spr_ready = False
    row["Accumulation Score"] = acc_sc
    row["A/D State"] = acc_state
    row["Spring Score"] = spr_sc
    row["Spring Ready"] = "Yes" if spr_ready else "No"
    row["Spring Trigger"] = spr_trig
    row["Spring Alert"] = spr_alert
    row["Pocket Pivot"] = m.get("Pocket Pivot", "No")
    row["VCP Contractions"] = m.get("VCP Contractions", 0)
    row["Base Depth %"] = m.get("Base Depth %")
    row["Base Length D"] = m.get("Base Length D")
    row["52W High Age D"] = m.get("52W High Age D")
    row["OBV Slope 20D %"] = m.get("OBV Slope 20D %")
    row["Avg Turnover 20D"] = m.get("Avg Turnover 20D")
    row["Illiquid"] = "Yes" if illiquid else "No"
    # Momentum Readiness blend (Section 15): confirmed + early both rank.
    comp = _f(row.get("Composite Score"))
    row["Momentum Readiness"] = round(0.5 * comp + 0.3 * spr_sc + 0.2 * acc_sc, 1)
    # Section 13: fresh-high bonus on Breakout Quality (cap 100).
    if _f(m.get("52W High Age D"), 99) <= 5 and "Breakout Quality" in row:
        row["Breakout Quality"] = min(100, _f(row["Breakout Quality"]) + 5)
    return row


# -----------------------------------------------------------------------------
# 8. MAIN SCAN
# -----------------------------------------------------------------------------
def run_scan(universe_df: pd.DataFrame, period: str = "5y",
             retest_window: int = 60, retest_tol: float = 7.0,
             min_rsi: float = 55.0, min_vol_ratio: float = 1.5,
             min_score: int = 55, local_mode: bool = False,
             eod_only: bool = True, fundamentals=None,
             momentum_quality_gate: bool = False, progress_callback=None) -> dict:
    """Scan the whole universe and return categorised result tables.

    `fundamentals` (optional): {SYMBOL: {field: value}} from
    fundamentals.load_fundamentals(). When provided, each row gets the four
    fundamental sub-scores + a `Fundamentals Quality Gate` flag. With
    `momentum_quality_gate=True` (Section 5A), a Strong Breakout in a low-quality
    business (Quality Score < 40) is demoted to Wait for Confirmation."""
    ctx = get_nifty_context(period=period)
    nifty_20d = ctx["nifty_20d_return"]
    regime = ctx["regime"]
    regime_supportive = regime in ("Bullish", "Neutral")
    sector_pe_map = load_sector_pe()      # optional data/sector_pe.csv (Phase 3)

    stocks = []            # phase-1 store (so we can compute sector strength first)
    rejected_rows = []
    failed = []

    total = len(universe_df)

    # --- BATCHED DOWNLOAD: fetch the whole universe in a few threaded requests
    #     (instead of one request per symbol) to avoid Yahoo rate-limits. ---
    all_symbols = [str(r.symbol).strip().upper() for r in universe_df.itertuples(index=False)]

    def _dl_progress(done, tot):
        if progress_callback:
            progress_callback(done, tot, "downloading market data (batched)")

    data = download_universe(all_symbols, period=period, local_mode=local_mode,
                             progress=_dl_progress, eod_only=eod_only)

    for i, row in enumerate(universe_df.itertuples(index=False), start=1):
        symbol = str(row.symbol).strip().upper()
        company = getattr(row, "company", symbol)
        sector = getattr(row, "sector", "-")
        cap = getattr(row, "market_cap_category", "-")
        try:
            df = data.get(symbol)              # from the batched download above
            if df is None or df.empty:
                failed.append(symbol)
            else:
                m = compute_metrics(df, ctx["nifty_returns"], retest_window, retest_tol)
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

    # --- Simple sector strength (kept for backward-compatible export) ---
    sector_df = build_sector_strength(stocks)
    top_sectors = list(sector_df.head(3)["Sector"]) if not sector_df.empty else []
    sector_rank_map = dict(zip(sector_df["Sector"], sector_df["Rank"])) if not sector_df.empty else {}

    # =========================================================================
    # PHASE A: per-stock score, classification and breakout quality
    # =========================================================================
    for s in stocks:
        m = s["m"]
        score, comps = score_components(m, s["sector"] in top_sectors, regime_supportive)
        bq, bq_status = breakout_quality(m)
        classification, reason = classify(m, score, min_rsi, min_vol_ratio, regime, min_score)
        s.update(score=score, comps=comps, bq=bq, bq_status=bq_status,
                 classification=classification, reason=reason)

    # =========================================================================
    # PHASE B: RS Score = percentile rank of relative strength across universe
    # =========================================================================
    if stocks:
        rsdf = pd.DataFrame({
            "rs20": [_f(s["m"]["_rs20"], np.nan) for s in stocks],
            "rs60": [_f(s["m"]["_rs60"], np.nan) for s in stocks],
            "rs120": [_f(s["m"]["_rs120"], np.nan) for s in stocks],
            "rs252": [_f(s["m"]["_rs252"], np.nan) for s in stocks]})

        def prank(col):
            x = rsdf[col]
            x = x.fillna(x.min() if x.notna().any() else 0)   # missing horizon ranks low
            return x.rank(pct=True) * 100

        rs_score = (0.30 * prank("rs20") + 0.30 * prank("rs60")
                    + 0.25 * prank("rs120") + 0.15 * prank("rs252")).round(0)
        rs_rank = rs_score.rank(ascending=False, method="min")
        for i, s in enumerate(stocks):
            m = s["m"]
            s["rs_score"] = int(rs_score.iloc[i])
            s["rs_rank"] = int(rs_rank.iloc[i])
            s["rs_leader"] = bool(
                s["rs_score"] >= 80 and _f(m["_rs20"]) > 0 and _f(m["_rs60"]) > 0
                and m["_above_50"] and m["_above_200"])

    # =========================================================================
    # PHASE C: Sector Rotation (aggregate per sector, percentile-ranked score)
    # =========================================================================
    sector_rotation = pd.DataFrame()
    sector_score_map, sector_rank2_map, sector_status_map = {}, {}, {}
    if stocks:
        sdata = pd.DataFrame([{
            "Sector": s["sector"], "ret20": _f(s["m"]["_ret20_raw"], np.nan),
            "ret60": _f(s["m"]["_ret60_raw"], np.nan), "rs_score": s["rs_score"],
            "above50": s["m"]["_above_50"], "above200": s["m"]["_above_200"],
            "vol": _f(s["m"]["Volume Ratio"], np.nan), "cls": s["classification"],
            "rsl": s["rs_leader"]} for s in stocks])
        g = sdata.groupby("Sector").agg(
            Avg_Return_20D=("ret20", "mean"), Avg_Return_60D=("ret60", "mean"),
            Avg_RS_Score=("rs_score", "mean"),
            Pct_Above_50DMA=("above50", lambda x: 100 * x.mean()),
            Pct_Above_200DMA=("above200", lambda x: 100 * x.mean()),
            Strong=("cls", lambda x: (x == "Strong Breakout / Actionable").sum()),
            Wait=("cls", lambda x: (x == "Wait for Confirmation").sum()),
            RS_Leaders=("rsl", "sum"), Avg_Volume_Ratio=("vol", "mean")).reset_index()
        g["Strong_Wait"] = g["Strong"] + g["Wait"]
        rk = lambda c: g[c].rank(pct=True)
        sss = (25 * rk("Avg_Return_20D") + 25 * rk("Avg_Return_60D")
               + 25 * rk("Avg_RS_Score") + 15 * rk("Pct_Above_50DMA")
               + 10 * rk("Strong_Wait")).round(0)
        g["Sector Strength Score"] = sss
        g = g.sort_values("Sector Strength Score", ascending=False).reset_index(drop=True)
        g["Sector Rank"] = range(1, len(g) + 1)
        g["Sector Status"] = g["Sector Strength Score"].apply(sector_status_from_score)
        for c in ["Avg_Return_20D", "Avg_Return_60D", "Avg_RS_Score", "Pct_Above_50DMA",
                  "Pct_Above_200DMA", "Avg_Volume_Ratio"]:
            g[c] = g[c].round(2)
        sector_rotation = g
        sector_score_map = dict(zip(g["Sector"], g["Sector Strength Score"]))
        sector_rank2_map = dict(zip(g["Sector"], g["Sector Rank"]))
        sector_status_map = dict(zip(g["Sector"], g["Sector Status"]))

    # =========================================================================
    # PHASE D: composite momentum score + build rows + route
    # =========================================================================
    strong_rows, wait_rows, watch_rows, all_rows = [], [], [], []
    coiled_rows, fresh_rows, spring_rows = [], [], []
    for s in stocks:
        m, comps, score = s["m"], s["comps"], s["score"]
        classification = s["classification"]
        sec_sss = _f(sector_score_map.get(s["sector"]), 0)
        trend100 = comps["Trend Score"] * 4.0          # 25 -> 100
        risk100 = comps["Risk Score"] * (100.0 / 15)   # 15 -> 100
        composite = int(round(0.25 * trend100 + 0.25 * s["rs_score"] + 0.20 * s["bq"]
                              + 0.15 * sec_sss + 0.15 * risk100))
        over, reasons, wait_cond = overextension(m)
        # --- PHASE 2 engines ---
        c_score, is_coiled = coiled_score(m, s["rs_score"])
        f_score, is_fresh = fresh_momentum_score(m, s["rs_score"])
        pq_score, pq_remark = pullback_quality(m)
        extra = {
            "RS Score": s["rs_score"], "RS Rank": s["rs_rank"],
            "RS Leader": "Yes" if s["rs_leader"] else "No",
            "Return 5D %": m["Return 5D %"], "Return 20D %": m["Return 20D %"],
            "Return 60D %": m["Return 60D %"], "Return 120D %": m["Return 120D %"],
            "Return 252D %": m["Return 252D %"],
            "RS 5D %": m["RS 5D %"], "RS 20D %": m["RS 20D %"], "RS 60D %": m["RS 60D %"],
            "RS 120D %": m["RS 120D %"], "RS 252D %": m["RS 252D %"],
            "Sector Strength Score": sec_sss,
            "Sector Rank": sector_rank2_map.get(s["sector"], "-"),
            "Sector Status": sector_status_map.get(s["sector"], "-"),
            "Breakout Quality": s["bq"], "Breakout Quality Status": s["bq_status"],
            "Composite Score": composite, "Momentum Class": composite_class(composite),
            "Distance from 50 DMA %": m["Distance from 50 DMA %"], "Gap Up %": m["Gap Up %"],
            "Overextended": "Yes" if over else "No",
            "No Chase Reason": "; ".join(reasons) if reasons else "-",
            "Wait Condition": wait_cond if over else "-",
            # Phase 2 columns
            "Coiled Score": c_score, "Coiled Ready": "Yes" if is_coiled else "No",
            "Fresh Momentum Score": f_score, "Fresh Momentum": "Yes" if is_fresh else "No",
            "Pullback Type": m["Pullback Type"], "Pullback Quality": pq_score,
            "Pullback Remark": pq_remark,
            "ATR Contraction": m["ATR Contraction"], "Volume Dryup 10D": m["Volume Dryup 10D"],
            "Range 10D %": m["Range 10D %"], "20D High": m["20D High"],
            "Pullback Depth %": m["Pullback Depth %"], "Recovery Speed Days": m["Recovery Speed Days"],
        }
        rowd = _build_row(s, m, score, comps, classification, sector_rank_map,
                          min_vol_ratio, regime, sector_status_map=sector_status_map)
        rowd.update(extra)
        # Recompute Momentum Readiness now that Composite Score is final.
        rowd["Momentum Readiness"] = round(
            0.5 * composite + 0.3 * _f(rowd.get("Spring Score"))
            + 0.2 * _f(rowd.get("Accumulation Score")), 1)

        # --- v2 Phase 2 + 3: fundamentals + value/quality-growth (if provided) ---
        if fundamentals:
            fdata = fundamentals.get(s["symbol"])
            if fdata:
                fsc = F.score_fundamentals(fdata, s["sector"])
                rowd.update(fsc)
                gate_pass = F.fundamentals_quality_gate(fsc, fdata)
                rowd["Fundamentals Quality Gate"] = "Pass" if gate_pass else "Fail"
                rowd["Fundamentals"] = "Loaded"
                # Section 5A optional momentum gate: demote junk-quality breakouts.
                if (momentum_quality_gate
                        and classification == "Strong Breakout / Actionable"
                        and _f(fsc.get("Quality Score"), 100) < 40):
                    classification = "Wait for Confirmation"
                    rowd["Classification"] = classification
                    rowd["Final Remark"] = (str(rowd.get("Final Remark", ""))
                                            + " | demoted: weak fundamentals")
                # --- Phase 3: valuation -> CAGR -> composite value -> class ---
                sec_pe = sector_pe_map.get(str(s["sector"]).strip().lower(), float("nan"))
                vsc = V.score_valuation(fdata, fsc.get("Growth Score"),
                                        s["sector"], sec_pe)
                rowd.update(vsc)
                cagr = V.expected_cagr(fdata, fsc.get("Quality Score"),
                                       s["sector"], sec_pe)
                rowd.update(cagr)
                # DCF-lite cross-check (Section 45): a second, independent estimate.
                dcf = V.dcf_lite_cagr(fdata, fsc.get("Quality Score"), s["sector"], sec_pe)
                rowd.update(dcf)
                rowd.update(V.cagr_cross_check(cagr.get("Expected CAGR %"),
                                               dcf.get("DCF CAGR %")))
                comp_val = V.composite_value(fsc.get("Quality Score"), fsc.get("Growth Score"),
                                             vsc.get("Valuation Score"),
                                             fsc.get("Balance-Sheet Score"), fsc.get("Promoter Score"))
                rowd["Composite Value"] = comp_val
                vc = V.value_class({**fsc, **vsc, "Composite Value": comp_val}, fdata,
                                   cagr.get("Expected CAGR %"), gate_pass,
                                   rowd.get("Sector Status", "-"),
                                   rowd.get("Illiquid") == "Yes",
                                   _f(m.get("200 DMA Slope %")))
                rowd.update(vc)
                rowd.update(V.value_timing(m, vc["Value Class"], cagr.get("Expected CAGR %")))
                # Section 38/39: crossover + quality-growth matrix
                xover = V.crossover_buy(vc["Value Class"], rowd.get("Momentum Class", ""),
                                        rowd.get("Spring Ready") == "Yes",
                                        rowd.get("Overextended") == "Yes",
                                        rowd.get("Illiquid") == "Yes")
                rowd["Crossover Buy"] = "Yes" if xover else "No"
                rowd["Matrix Class"] = V.matrix_class_qg(composite, comp_val,
                                                         vc["Value Class"], xover)
                rowd["Matrix Remark"] = V.MATRIX_QG_REMARKS.get(rowd["Matrix Class"], "")
            else:
                rowd["Fundamentals"] = "Missing"
                rowd["Fundamentals Quality Gate"] = "No Data"
                rowd["Value Class"] = "Fundamentals Missing"

        all_rows.append(rowd)
        if is_coiled:
            coiled_rows.append(rowd)
        if is_fresh:
            fresh_rows.append(rowd)
        if rowd.get("Spring Ready") == "Yes":
            spring_rows.append(rowd)

        if classification == "Strong Breakout / Actionable":
            strong_rows.append(rowd)
        elif classification == "Wait for Confirmation":
            wait_rows.append(rowd)
        elif classification == "Early Watchlist":
            watch_rows.append(rowd)
        else:  # Rejected by rule
            rejected_rows.append({
                "Symbol": s["symbol"], "Company": s["company"], "Sector": s["sector"],
                "Market Cap Category": s["cap"], "Score": score,
                "Composite Score": composite, "RS Score": s["rs_score"],
                "Classification": "Rejected", "Reason": s["reason"]})

    # --- Build & sort each table ---
    def finalise(rows, sort_cols, ascending):
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values(sort_cols, ascending=ascending).reset_index(drop=True)
            df.insert(0, "Rank", range(1, len(df) + 1))
        return df

    strong_df = finalise(strong_rows, ["Composite Score", "Relative Strength %"], [False, False])
    wait_df = finalise(wait_rows,
                       ["Composite Score", "Distance from 52W High %", "Relative Strength %"],
                       [False, True, False])
    watch_df = finalise(watch_rows, ["Composite Score"], [False])
    coiled_df = finalise(coiled_rows, ["Coiled Score", "Distance from 52W High %"], [False, True])
    fresh_df = finalise(fresh_rows, ["Fresh Momentum Score", "RS Score"], [False, False])
    spring_df = finalise(spring_rows, ["Spring Score", "Accumulation Score"], [False, False])
    all_df = finalise(all_rows, ["Momentum Readiness"], [False])
    # --- Phase 3 value frames (only populated when fundamentals were provided) ---
    value_quality_df, crossover_df = pd.DataFrame(), pd.DataFrame()
    if fundamentals and all_rows:
        vq = pd.DataFrame([r for r in all_rows if "Composite Value" in r])
        if not vq.empty:
            value_quality_df = vq.sort_values(
                ["Composite Value", "Expected CAGR %"], ascending=[False, False]
            ).reset_index(drop=True)
            crossover_df = value_quality_df[
                value_quality_df.get("Crossover Buy") == "Yes"].reset_index(drop=True)
    # Accumulation view: top names by Accumulation Score (independent of class).
    accumulation_df = pd.DataFrame()
    if all_rows:
        accumulation_df = (pd.DataFrame(all_rows)
                           .sort_values("Accumulation Score", ascending=False)
                           .reset_index(drop=True))
    rejected_df = pd.DataFrame(rejected_rows)

    return {
        "strong": strong_df, "wait": wait_df, "watchlist": watch_df,
        "coiled": coiled_df, "fresh": fresh_df,
        "spring": spring_df, "accumulation": accumulation_df,
        "value_quality": value_quality_df, "crossover": crossover_df,
        "rejected": rejected_df, "failed": failed,
        "all_stocks": all_df, "sector_rotation": sector_rotation,
        "price_data": data,   # in-memory OHLCV cache for the Deep-Dive chart
        "sector_strength": sector_df, "top_sectors": top_sectors,
        "regime": regime, "nifty_context": ctx,
        "universe_count": total,
        "scanned_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# -----------------------------------------------------------------------------
# 9. CLAUDE / CHATGPT REVIEW PROMPTS
# -----------------------------------------------------------------------------
_REVIEW_TASK = (
    "Check latest news, results, sector strength, technical structure, "
    "support/resistance, and whether this is suitable for a 15-30 day swing trade. "
    "Do not recommend entry if the confirmation condition is not met. "
    "Rank them from best to weakest.\n\n"
)


def _g(r, key, default="-"):
    """Safe column getter for a row (works whether or not the column exists)."""
    try:
        v = r[key]
        return default if (v is None or (isinstance(v, float) and np.isnan(v))) else v
    except (KeyError, TypeError):
        return default


def build_review_prompt(df: pd.DataFrame, header: str) -> str:
    """Generic review prompt: one rich line per stock with all key fields."""
    intro = header + _REVIEW_TASK
    if df is None or df.empty:
        return intro + "(No stocks in this bucket for this scan.)"
    lines = []
    for _, r in df.iterrows():
        lines.append(
            f"- {_g(r, 'Symbol')} ({_g(r, 'Company')}, {_g(r, 'Sector')}): "
            f"CMP {_g(r, 'CMP')}, Composite {_g(r, 'Composite Score')}, "
            f"RS {_g(r, 'RS Score')}, Sector {_g(r, 'Sector Status')} "
            f"({_g(r, 'Sector Strength Score')}), Breakout {_g(r, 'Breakout Status')} "
            f"[{_g(r, 'Breakout Quality Status')}], Pullback {_g(r, 'Pullback Type')}, "
            f"Confirmation: {_g(r, 'Confirmation Needed')}, Trigger {_g(r, 'Trigger Price')}, "
            f"Invalidation {_g(r, 'Invalidation Level')}, Risk {_g(r, 'Risk Level')}")
    return intro + "\n".join(lines)


# The five Phase-2 prompts -----------------------------------------------------
def build_strong_prompt(strong_df: pd.DataFrame) -> str:
    return build_review_prompt(
        strong_df, "Review these ELITE / ACTIONABLE BREAKOUT NSE stocks for an "
        "IMMEDIATE 15-30 day swing trade. ")


def build_wait_prompt(wait_df: pd.DataFrame) -> str:
    return build_review_prompt(
        wait_df, "Review these WAIT-FOR-CONFIRMATION NSE stocks. The setup is "
        "developing but the breakout is NOT yet confirmed. ")


def build_coiled_prompt(coiled_df: pd.DataFrame) -> str:
    return build_review_prompt(
        coiled_df, "Review these COILED / TIGHT NSE stocks that look like they are "
        "preparing for a breakout (range contraction + volume dry-up). ")


def build_fresh_prompt(fresh_df: pd.DataFrame) -> str:
    return build_review_prompt(
        fresh_df, "Review these FRESH MOMENTUM NSE stocks that appear to be starting "
        "a new up-move. ")


def build_donotchase_prompt(nc_df: pd.DataFrame) -> str:
    return build_review_prompt(
        nc_df, "Review these strong-but-OVEREXTENDED NSE stocks (Do Not Chase). "
        "Assess where a lower-risk re-entry might appear. ")
