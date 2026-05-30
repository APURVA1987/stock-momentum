# holdings.py
# -----------------------------------------------------------------------------
# Zerodha holdings overlay:
#   - Normalise the broker export (xlsx/xls/csv) to a clean schema.
#   - Persist as data/holdings_latest.xlsx so the app remembers it.
#   - Merge each holding with the scanner output to produce technical/momentum
#     context and a plain-English "holding_action" label.
#
# NOTE FOR NON-CODERS:
# - This is a thin overlay on top of the existing scanner. It does NOT change
#   how the scanner works. It just joins your holdings with the scan result.
# -----------------------------------------------------------------------------

import os
import re

import numpy as np
import pandas as pd

# Possible Zerodha column header variants -> our internal name.
_COL_ALIASES = {
    "symbol":          ["instrument", "symbol", "tradingsymbol", "scrip"],
    "quantity":        ["qty", "qty.", "quantity", "qty available"],
    "avg_cost":        ["avg cost", "avg. cost", "avg. price", "avg price",
                        "average cost", "average price"],
    "ltp":             ["ltp", "last price", "cmp", "current price"],
    "invested":        ["invested", "invested amount", "cost value", "cost"],
    "current_value":   ["cur. val", "cur val", "current value", "current val",
                        "market value", "mkt value"],
    "pnl":             ["p&l", "pnl", "p&l (₹)", "profit & loss", "p & l"],
    "net_change_pct":  ["net chg.", "net chg", "net chg.%", "net change %",
                        "net %", "p&l %"],
    "day_change_pct":  ["day chg.", "day chg", "day chg.%", "day change %", "day %"],
}


def _norm(s) -> str:
    return re.sub(r"[\s_]+", " ", str(s)).strip().lower().rstrip(".")


def _find_col(df: pd.DataFrame, key: str):
    """Find the broker-side column header that maps to our key, fuzzy-matched."""
    cols = {_norm(c): c for c in df.columns}
    aliases = [_norm(a) for a in _COL_ALIASES[key]]
    for a in aliases:
        if a in cols:
            return cols[a]
    for cn, c in cols.items():                   # partial-match fallback
        for a in aliases:
            if a in cn:
                return c
    return None


def normalise_holdings(df: pd.DataFrame) -> pd.DataFrame:
    """Map any reasonable Zerodha export into our clean schema and recompute
    pnl/pnl_pct/weight from invested & current_value (more reliable than the
    broker's columns)."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = pd.DataFrame()
    for key in _COL_ALIASES:
        c = _find_col(df, key)
        if c is not None:
            out[key] = df[c]
    if "symbol" not in out.columns:
        return pd.DataFrame()
    # Clean symbol; drop blanks and total/grand-total rows.
    out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
    out = out[out["symbol"].str.len() > 0]
    out = out[~out["symbol"].str.contains(r"TOTAL|GRAND|^$", regex=True, na=False)]
    # Numeric coercion (handle Indian comma formatting and trailing % signs).
    for k in ["quantity", "avg_cost", "ltp", "invested", "current_value",
              "pnl", "net_change_pct", "day_change_pct"]:
        if k in out.columns:
            out[k] = pd.to_numeric(
                out[k].astype(str).str.replace(",", "", regex=False)
                       .str.replace("%", "", regex=False).str.strip(),
                errors="coerce")
    # Backfill any missing derived fields.
    if "invested" not in out.columns and {"quantity", "avg_cost"} <= set(out.columns):
        out["invested"] = out["quantity"] * out["avg_cost"]
    if "current_value" not in out.columns and {"quantity", "ltp"} <= set(out.columns):
        out["current_value"] = out["quantity"] * out["ltp"]
    # RE-COMPUTE pnl & pnl_pct from invested/current_value to dodge broker quirks.
    if {"invested", "current_value"} <= set(out.columns):
        out["pnl"] = (out["current_value"] - out["invested"]).round(2)
        inv = out["invested"].where(out["invested"] > 0, np.nan)
        out["pnl_pct"] = (out["pnl"] / inv * 100).round(2)
    # Portfolio weight from current value.
    if "current_value" in out.columns:
        tot = float(out["current_value"].sum())
        out["portfolio_weight_pct"] = ((out["current_value"] / tot * 100).round(2)
                                       if tot > 0 else np.nan)
    return out.reset_index(drop=True)


# -----------------------------------------------------------------------------
# Persistence
# -----------------------------------------------------------------------------
def load_persistent(path: str):
    """Read the saved-default holdings file, if any."""
    if not os.path.exists(path):
        return None
    try:
        if path.lower().endswith(".csv"):
            return pd.read_csv(path)
        return pd.read_excel(path)
    except Exception:
        return None


def save_persistent(uploaded_file, path: str) -> bool:
    """Save the uploaded file as the new default holdings file."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else None
        if data is None:
            return False
        with open(path, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


# -----------------------------------------------------------------------------
# Merge with scanner output + holding-action logic
# -----------------------------------------------------------------------------
SCAN_COLS = [
    "Company", "Sector", "Market Cap Category", "CMP", "Classification",
    "Composite Score", "Score", "Momentum Class", "RS Score", "RS Rank",
    "RS Leader", "Sector Strength Score", "Sector Rank", "Sector Status",
    "Breakout Status", "Breakout Quality", "Breakout Quality Status",
    "Pullback Type", "Pullback Quality", "Pullback Remark", "Risk Level",
    "Trigger Price", "Suggested Alert Price", "Invalidation Level",
    "Confirmation Needed", "No Chase Reason", "Wait Condition",
    "Entry Zone", "Stop Loss", "Target 1", "Target 2", "Risk Reward",
    "20 DMA", "50 DMA", "200 DMA", "52W High", "RSI 14", "ADX 14", "ATR 14",
    "Volume Ratio", "Relative Strength %", "RS 20D %", "RS 60D %", "RS 120D %",
    "Distance from 52W High %", "Distance from 200 DMA %",
    "Distance from 20 DMA %", "200 DMA Slope %",
    "Overextended", "Coiled Ready", "Coiled Score",
    "Fresh Momentum", "Fresh Momentum Score",
    # v2 Phase 4: value / quality-growth dual-lens columns
    "Value Class", "Composite Value", "Expected CAGR %", "CAGR Band",
    "Quality Score", "Crossover Buy", "Value Entry Style", "Accumulation Zone",
    "Spring Ready", "Spring Score",
]

ACTION_REMARKS = {
    "Hold / Trail":         "Hold existing position. Trail stop-loss. Add only on pullback or breakout sustain.",
    "Add on Pullback":      "Can consider adding only on controlled pullback or breakout retest with volume.",
    "Hold, Set Alert":      "Hold. Set alert near trigger price. Do not add until confirmation.",
    "Do Not Add / Trail Only": "Continue holding if already owned. Do NOT add fresh. Trail SL.",
    "Review / Reduce":      "Review for reduction. Weak technical structure.",
    "Exit Review":          "Exit / reduce review. Avoid averaging down until structure improves.",
    "Watch Only":           "Watch only. Wait for reclaim of 50 DMA or base breakout.",
    "No Scanner Data":      "Scanner data unavailable for this symbol - see Failed Tickers.",
    # v2 Phase 4 (Section 40) dual-lens actions
    "Core Compounder - Hold / Add in Zones":
        "Verified 3-5 yr compounder. Hold; add in the accumulation zone. Ignore short-term chart noise.",
    "Fundamental + Technical Breakdown - Exit Review":
        "Both lenses negative (weak business AND below falling 200 DMA, in loss). Exit / reduce review; do NOT average down.",
}


def _f(v, default=0.0):
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _action(r) -> str:
    cls = str(r.get("Classification", "") or "")
    if not cls or cls.lower() == "nan":
        return "No Scanner Data"
    comp = _f(r.get("Composite Score"))
    mc = str(r.get("Momentum Class", "") or "")
    rs = _f(r.get("Relative Strength %"))
    rr = _f(r.get("Risk Reward"))
    pnl = _f(r.get("pnl"))
    cmp_ = r.get("CMP") if pd.notna(r.get("CMP")) else r.get("ltp")
    ma50 = r.get("50 DMA")
    ma200 = r.get("200 DMA")
    slope200 = _f(r.get("200 DMA Slope %"))
    overext = str(r.get("Overextended", "")) == "Yes"
    sec_status = str(r.get("Sector Status", ""))
    coiled = str(r.get("Coiled Ready", "")) == "Yes"
    fresh = str(r.get("Fresh Momentum", "")) == "Yes"

    above_200 = pd.notna(cmp_) and pd.notna(ma200) and cmp_ > ma200
    above_50 = pd.notna(cmp_) and pd.notna(ma50) and cmp_ > ma50
    falling_200 = slope200 <= 0
    value_cls = str(r.get("Value Class", "") or "")

    # v2 Section 40: dual-lens (value + technical) takes precedence on the extremes.
    # Both lenses negative -> strongest exit signal.
    if (value_cls == "Value Avoid" and pnl < 0 and (not above_200) and falling_200):
        return "Fundamental + Technical Breakdown - Exit Review"

    # F. Exit Review (structure broken)
    if (not above_200) and falling_200 and (rs < 0 or comp < 55):
        return "Exit Review"
    # E. Review / Reduce (weak but not collapsing)
    if cls == "Rejected" or comp < 55 or rs < 0:
        return "Review / Reduce"
    # v2 Section 40: a verified compounder you already hold -> core long-term hold.
    if value_cls == "Compounder" and not overext:
        return "Core Compounder - Hold / Add in Zones"
    # D. Do Not Add / Trail Only (strong-but-overextended, already in profit)
    if overext and pnl > 0:
        return "Do Not Add / Trail Only"
    # A/B. Strong momentum
    strong_cls = cls in ("Strong Breakout / Actionable",) or mc in (
        "Elite Momentum", "Actionable Breakout")
    if strong_cls and comp >= 75 and above_200:
        if sec_status == "Leading" and rr >= 1.5 and not overext:
            return "Add on Pullback"
        return "Hold / Trail"
    # C. Hold, Set Alert (wait / coiled / fresh)
    if cls == "Wait for Confirmation" or coiled or fresh:
        return "Hold, Set Alert"
    # G. Watch Only (base / early stage)
    if cls == "Early Watchlist":
        return "Watch Only"
    return "Hold, Set Alert"


def merge_with_scan(holdings_df: pd.DataFrame, all_stocks_df: pd.DataFrame) -> pd.DataFrame:
    """Return a holdings frame enriched with scanner columns + technical-vs-cost
    metrics + the rule-based holding_action label."""
    if holdings_df is None or holdings_df.empty:
        return pd.DataFrame()
    h = holdings_df.copy()
    if all_stocks_df is not None and not all_stocks_df.empty:
        keep = [c for c in SCAN_COLS if c in all_stocks_df.columns]
        s = (all_stocks_df[["Symbol"] + keep].rename(columns={"Symbol": "symbol"})
             .drop_duplicates(subset="symbol", keep="first"))
        h = h.merge(s, on="symbol", how="left")
    # Use scanner CMP for technical comparisons, fall back to broker LTP.
    cmp_series = h["CMP"] if "CMP" in h.columns else h.get("ltp")
    if "avg_cost" in h.columns and cmp_series is not None:
        h["avg_vs_cmp_pct"] = ((cmp_series - h["avg_cost"]) / h["avg_cost"] * 100).round(2)
    for n, k in [(20, "20 DMA"), (50, "50 DMA"), (200, "200 DMA")]:
        if k in h.columns and "avg_cost" in h.columns:
            h[f"avg_vs_{n}dma_pct"] = ((h["avg_cost"] - h[k]) / h[k] * 100).round(2)
    if "200 DMA" in h.columns and cmp_series is not None:
        h["cmp_vs_200dma_pct"] = ((cmp_series - h["200 DMA"]) / h["200 DMA"] * 100).round(2)
    h["holding_action"] = h.apply(_action, axis=1)
    h["holding_remark"] = h["holding_action"].map(ACTION_REMARKS).fillna("")
    return h


# -----------------------------------------------------------------------------
# Portfolio-level summary (one-row DataFrame for cards / export)
# -----------------------------------------------------------------------------
def portfolio_summary(h: pd.DataFrame) -> dict:
    if h is None or h.empty:
        return {}
    inv = float(h["invested"].sum()) if "invested" in h.columns else 0.0
    cv = float(h["current_value"].sum()) if "current_value" in h.columns else 0.0
    pnl = float(h["pnl"].sum()) if "pnl" in h.columns else (cv - inv)
    pnl_pct = (pnl / inv * 100) if inv > 0 else 0.0
    in_mom = int(h["holding_action"].isin(["Hold / Trail", "Add on Pullback"]).sum())
    wait = int((h["holding_action"] == "Hold, Set Alert").sum())
    weak = int(h["holding_action"].isin(["Review / Reduce", "Exit Review"]).sum())
    top_weight = float(h["portfolio_weight_pct"].max()) if "portfolio_weight_pct" in h.columns else 0.0
    return {
        "Total Invested": round(inv, 2), "Total Current Value": round(cv, 2),
        "Total P&L": round(pnl, 2), "Total P&L %": round(pnl_pct, 2),
        "Holdings In Momentum": in_mom, "Holdings Waiting": wait,
        "Holdings Weak / Exit": weak, "Top Holding Weight %": round(top_weight, 2),
        "Holdings Count": int(len(h)),
    }


# -----------------------------------------------------------------------------
# Universe + holdings combiner (used BEFORE the scan so we always download
# holding symbols even if they are not in the main universe).
# -----------------------------------------------------------------------------
def combine_universe_holdings(uni: pd.DataFrame, holdings: pd.DataFrame) -> pd.DataFrame:
    if uni is None:
        uni = pd.DataFrame(columns=["symbol", "company", "sector", "market_cap_category"])
    if holdings is None or holdings.empty or "symbol" not in holdings.columns:
        if not uni.empty:
            uni = uni.copy()
            uni["source_type"] = "Universe"
        return uni
    uni_syms = set(uni["symbol"].astype(str).str.upper()) if not uni.empty else set()
    hold_syms = set(holdings["symbol"].astype(str).str.upper())
    extras = sorted(hold_syms - uni_syms)
    if extras:
        extra_rows = pd.DataFrame({
            "symbol": extras, "company": extras, "sector": "-",
            "market_cap_category": "Holding"})
        out = pd.concat([uni, extra_rows], ignore_index=True)
    else:
        out = uni.copy()
    out["source_type"] = out["symbol"].astype(str).str.upper().apply(
        lambda s: "Universe + Holding" if (s in uni_syms and s in hold_syms)
        else ("Holding" if s in hold_syms else "Universe"))
    return out
