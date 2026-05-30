# backtest.py
# -----------------------------------------------------------------------------
# MOMENTUM-ONLY backtest (point-in-time, no look-ahead).
#
# For each sampled past date T and each stock, we slice the price history to
# ONLY the data available up to T, recompute the real momentum signals
# (scanner.compute_metrics + classify + fresh/spring/accumulation), label the
# stock's bucket as-of T, then measure the FORWARD 15- and 30-trading-day
# return. Aggregating across all (stock, date) samples gives an honest
# hit-rate and average forward return per bucket.
#
# WHY MOMENTUM ONLY (read doc/SCANNER_TECHNICAL_SPEC_v2.md "Backtesting"):
# The VALUE / Quality-Growth scan is driven by a CURRENT fundamentals snapshot.
# Backtesting it would require point-in-time fundamentals (ROCE / growth / P/E
# as they were known on date T). Using today's fundamentals on past prices is
# look-ahead + survivorship bias and would invent fake outperformance, so the
# value scan is deliberately EXCLUDED here.
#
# Faithfulness notes (simplifications, all documented):
# - Per-stock signals only. Cross-sectional features that need the WHOLE
#   universe ranked at date T (RS Score percentile, RS Leader, sector bonus)
#   are NOT replayed. The Strong/Wait gates and the Spring/Fresh flags are
#   per-stock and ARE replayed faithfully.
# - regime is assumed Neutral and sector-top bonus off at each T (we don't
#   reconstruct the historical sector table). This makes scores marginally
#   conservative, never optimistic.
# -----------------------------------------------------------------------------

import numpy as np
import pandas as pd

import indicators as ind
import scanner


def _nifty_returns_asof(nifty_close: pd.Series, asof_date) -> dict:
    """Reconstruct the {5,20,60,120,252: return%} dict using ONLY Nifty data
    up to `asof_date` (no look-ahead)."""
    s = nifty_close[nifty_close.index <= asof_date]
    return {h: ind.pct_change_over(s, h) for h in (5, 20, 60, 120, 252)}


def _bucket_asof(m: dict, min_rsi, min_vol_ratio, min_score) -> list:
    """Return the list of buckets this stock belongs to as-of T (a stock can be
    in more than one, e.g. Strong Breakout AND Fresh Momentum)."""
    buckets = []
    # Score + classification (per-stock; sector bonus off, regime Neutral).
    score, _ = scanner.score_components(m, sector_is_top=False, regime_supportive=True)
    cls, _ = scanner.classify(m, score, min_rsi, min_vol_ratio, "Neutral", min_score)
    if cls == "Strong Breakout / Actionable":
        buckets.append("Strong Breakout")
    elif cls == "Wait for Confirmation":
        buckets.append("Wait for Confirmation")
    elif cls == "Early Watchlist":
        buckets.append("Early Watchlist")
    # Fresh momentum flag
    _, is_fresh = scanner.fresh_momentum_score(m, 70)        # rs_score proxy = 70
    if is_fresh:
        buckets.append("Fresh Momentum")
    # Spring-ready flag (needs accumulation score)
    acc_sc, _ = scanner.accumulation_score(m)
    _, spr_ready, _, _ = scanner.spring_score(m, acc_sc)
    if spr_ready:
        buckets.append("Spring Ready")
    return buckets


def run_momentum_backtest(price_data: dict, period_lookback_days: int = 504,
                          sample_step: int = 21, fwd_days=(15, 30),
                          min_rsi: float = 55.0, min_vol_ratio: float = 1.5,
                          min_score: int = 65, progress=None) -> dict:
    """Replay momentum signals over history and measure forward returns.

    `price_data`: {SYMBOL: OHLCV DataFrame} (reuse the scan's in-memory cache).
    `period_lookback_days`: how far back to sample (trading days, ~252/yr).
    `sample_step`: spacing between as-of dates (21 ~ monthly).
    `fwd_days`: forward horizons to measure.
    Returns {summary: DataFrame, samples: int, dates: int, baseline: dict}.
    """
    nifty = price_data.get("^NSEI")
    if nifty is None or nifty.empty:
        return {"summary": pd.DataFrame(), "samples": 0, "dates": 0,
                "error": "Nifty (^NSEI) history not in price cache."}
    nclose = nifty["Close"]
    max_fwd = max(fwd_days)

    rows = []                  # one record per (stock, date, bucket)
    base_rows = []             # baseline: every sampled stock-date (any signal or not)
    symbols = [s for s in price_data if s != "^NSEI"]
    total = len(symbols)

    for si, sym in enumerate(symbols, start=1):
        df = price_data.get(sym)
        if df is None or len(df) < 240 + max_fwd:
            if progress:
                progress(si, total, sym)
            continue
        close = df["Close"].values
        n = len(df)
        # Sample positions: need >=220 history behind and max_fwd ahead.
        start_i = max(220, n - period_lookback_days)
        for i in range(start_i, n - max_fwd, sample_step):
            asof = df.index[i]
            sliced = df.iloc[:i + 1]
            try:
                nr = _nifty_returns_asof(nclose, asof)
                m = scanner.compute_metrics(sliced, nr)
                if m is None:
                    continue
                fwd = {f"fwd{d}": (close[i + d] / close[i] - 1.0) * 100 for d in fwd_days}
                base_rows.append(fwd)
                for b in _bucket_asof(m, min_rsi, min_vol_ratio, min_score):
                    rows.append({"bucket": b, **fwd})
            except Exception:
                continue
        if progress:
            progress(si, total, sym)

    def agg(records, label):
        if not records:
            return None
        d = pd.DataFrame(records)
        out = {"Bucket": label, "Samples": len(d)}
        for fd in fwd_days:
            col = f"fwd{fd}"
            out[f"Avg {fd}D Ret %"] = round(d[col].mean(), 2)
            out[f"Median {fd}D Ret %"] = round(d[col].median(), 2)
            out[f"Win% {fd}D"] = round((d[col] > 0).mean() * 100, 1)
        return out

    summary = []
    base = agg(base_rows, "Baseline (all stock-dates)")
    if base:
        summary.append(base)
    if rows:
        rdf = pd.DataFrame(rows)
        for b in ["Strong Breakout", "Wait for Confirmation", "Fresh Momentum",
                  "Spring Ready", "Early Watchlist"]:
            sub = rdf[rdf["bucket"] == b].to_dict("records")
            a = agg(sub, b)
            if a:
                summary.append(a)
    return {"summary": pd.DataFrame(summary),
            "samples": len(base_rows),
            "dates": len(base_rows),
            "baseline": base}
