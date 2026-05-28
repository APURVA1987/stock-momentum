# value.py
# -----------------------------------------------------------------------------
# TECHNICAL VALUE SCANNER (Phase 2)
# -----------------------------------------------------------------------------
# Identify stocks that are corrected, stabilising, reclaiming key moving
# averages, or forming a base - the "value" complement to the momentum scanner.
#
# This module is technical-first (no fundamentals). It re-uses indicators
# already computed in scanner.compute_metrics, so it adds almost no overhead.
#
# NOTE FOR NON-CODERS:
# - You normally do NOT need to edit this file.
# - Tunable thresholds live at the top of the file (CORR_*, BASE_*, etc.).
# -----------------------------------------------------------------------------

import numpy as np

# ---- Tunable thresholds (Value classification cut-offs) ---------------------
CORR_BAND_MIN = 15.0       # % off 52W-high lower bound for a "valid correction"
CORR_BAND_MAX = 40.0       # upper bound for Value Reversal Ready
CORR_BASE_MAX = 45.0       # upper bound for Value Base Forming
DEEP_VALUE_MIN = 35.0      # % off 52W-high to qualify as Deep Value
RSI_REVERSAL_MIN = 50.0    # RSI threshold for reversal confirmation
SCORE_REVERSAL_READY = 75
SCORE_BASE_FORMING = 60


VALUE_REMARKS = {
    "Value Reversal Ready":
        "Recovery confirmed. Consider only after chart/news review.",
    "Value Base Forming":
        "Base forming. Set alert above base resistance.",
    "Deep Value High Risk":
        "High-risk recovery candidate. Small watchlist only.",
    "Value Trap Avoid":
        "Cheap but technically weak. Avoid until structure improves.",
}


def _f(v, default=0.0):
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


# -----------------------------------------------------------------------------
# Score / classify a single stock
# -----------------------------------------------------------------------------
def score_value(m: dict, sector_status: str = "") -> dict:
    """Compute the Value Score (0-100) + Value Classification + entry style /
    trigger / invalidation / target zone / remark for one stock.

    `m` is the metrics dict produced by scanner.compute_metrics().
    `sector_status` is the stock's sector tier (Leading / Improving / Neutral / Weak)
    so we can avoid awarding "sector not weak" points when the sector is weak.
    """
    dist52 = _f(m.get("Distance from 52W High %"))           # negative if below high
    drawdown = abs(dist52)                                    # % below 52W high
    cmp_ = _f(m["CMP"])
    ma20, ma50, ma200 = _f(m["20 DMA"]), _f(m["50 DMA"]), _f(m["200 DMA"])
    above_20 = cmp_ > ma20
    above_50 = cmp_ > ma50
    above_200 = cmp_ > ma200
    slope50 = _f(m.get("50 DMA Slope %"))
    slope200 = _f(m.get("200 DMA Slope %"))
    rsi = _f(m.get("RSI 14"), 50)
    rsi_change_2w = _f(m.get("RSI Change 2W"))
    macd_bull = bool(m.get("_macd_bullish", False))
    ud_vol = _f(m.get("Up/Down Vol Ratio"), 1.0)
    rs20 = _f(m.get("RS 20D %"))
    rs60 = _f(m.get("RS 60D %"))
    fresh_3m_low = bool(m.get("_fresh_3m_low", False))
    rng10 = _f(m.get("Range 10D %"))
    rng60 = _f(m.get("Range 60D %"))
    tightness = (rng10 / rng60) if rng60 > 0 else 1.0         # lower = tighter
    atrc = _f(m.get("ATR Contraction"), 1.0)
    vdry = _f(m.get("Volume Dryup 10D"), 1.0)
    higher_lows = _f(m.get("Higher Lows 10D"))
    rr = _f(m.get("Risk Reward"))
    swing_low = _f(m.get("_swing_low"))

    # ===== A. Correction Opportunity (20) =====
    corr = 0
    if CORR_BAND_MIN <= drawdown <= CORR_BAND_MAX: corr += 10
    if drawdown <= 50: corr += 5
    if 10 <= drawdown <= 45: corr += 5

    # ===== B. Stabilisation / Base (25) =====
    stab = 0
    if tightness <= 0.5: stab += 8
    elif tightness <= 0.7: stab += 5
    elif tightness <= 0.85: stab += 2
    if atrc < 0.85: stab += 6
    elif atrc < 1.0: stab += 3
    if vdry < 0.8: stab += 5
    elif vdry < 1.0: stab += 2
    if higher_lows >= 6: stab += 6
    elif higher_lows >= 4: stab += 3

    # ===== C. Reversal Confirmation (25) =====
    rev = 0
    if above_20: rev += 5
    if above_50: rev += 7
    elif cmp_ >= ma50 * 0.97: rev += 3                        # reclaiming
    if rsi >= RSI_REVERSAL_MIN: rev += 5
    elif rsi_change_2w >= 10: rev += 3
    if macd_bull: rev += 4
    if ud_vol >= 1.3: rev += 4
    elif ud_vol >= 1.0: rev += 2

    # ===== D. Relative Strength Improvement (15) =====
    rs_pts = 0
    if rs20 > 0: rs_pts += 5
    if rs60 > 0: rs_pts += 5
    if sector_status not in ("Weak",): rs_pts += 5

    # ===== E. Risk Control (15) =====
    risk = 0
    if not (slope200 < 0 and not above_200): risk += 5         # not below falling 200 DMA
    if not fresh_3m_low: risk += 5
    if rr >= 1.5: risk += 5

    total = int(min(100, corr + stab + rev + rs_pts + risk))

    # ===== Classification =====
    # Trap: anything fundamentally broken takes priority.
    is_trap = (
        (slope200 < 0 and not above_200) or fresh_3m_low or
        rs60 < -5 or rsi < 40 or
        (sector_status == "Weak" and not above_50))

    if is_trap:
        cls = "Value Trap Avoid"
    elif (total >= SCORE_REVERSAL_READY and
          CORR_BAND_MIN <= drawdown <= CORR_BAND_MAX and above_20 and
          (above_50 or cmp_ >= ma50 * 0.98) and rsi > RSI_REVERSAL_MIN and
          (rs20 > 0 or rs60 > 0) and not fresh_3m_low):
        cls = "Value Reversal Ready"
    elif (SCORE_BASE_FORMING <= total < SCORE_REVERSAL_READY and
          CORR_BAND_MIN <= drawdown <= CORR_BASE_MAX and tightness <= 0.7 and
          vdry < 0.85 and higher_lows >= 3):
        cls = "Value Base Forming"
    elif (drawdown > DEEP_VALUE_MIN and sector_status != "Weak" and
          (above_200 or atrc < 0.85 or higher_lows >= 3)):
        cls = "Deep Value High Risk"
    else:
        cls = "Value Base Forming" if total >= 50 else "Value Trap Avoid"

    # ===== Entry style =====
    if cls == "Value Reversal Ready":
        if not above_50:
            entry_style = "Reclaiming 50 DMA"
        elif above_20 and rsi >= RSI_REVERSAL_MIN:
            entry_style = "Reversal from oversold"
        else:
            entry_style = "Base breakout"
    elif cls == "Value Base Forming":
        entry_style = "Base breakout"
    elif cls == "Deep Value High Risk":
        entry_style = "200 DMA support"
    else:
        entry_style = "Deep value (wait)"

    # ===== Trigger / Invalidation / Target =====
    if entry_style == "Reclaiming 50 DMA" and ma50 > 0:
        trigger = round(ma50, 2)
    elif entry_style == "Base breakout":
        # Base resistance ~ recent 60-day high (best available proxy).
        trigger = round(_f(m.get("_high_52w")) * (1 + dist52 / 200.0), 2)
        # That nudges the price up from the current level toward the 52W high.
    elif entry_style == "200 DMA support":
        trigger = round(ma200 * 1.02, 2) if ma200 > 0 else round(cmp_, 2)
    else:
        trigger = round(ma50, 2) if ma50 > 0 else round(cmp_ * 1.05, 2)

    invalidation = round(swing_low, 2) if swing_low > 0 else round(cmp_ * 0.92, 2)
    target_zone = f"{round(cmp_ * 1.10, 2)} - {round(cmp_ * 1.20, 2)}"

    return {
        "Value Score": total,
        "Value Classification": cls,
        "Value Entry Style": entry_style,
        "Value Trigger Price": trigger,
        "Value Invalidation Level": invalidation,
        "Value Target Zone": target_zone,
        "Value Remark": VALUE_REMARKS.get(cls, ""),
        "Value Correction Score": corr,
        "Value Stabilisation Score": stab,
        "Value Reversal Score": rev,
        "Value RS Score": rs_pts,
        "Value Risk Score": risk,
    }


# -----------------------------------------------------------------------------
# Momentum + Value matrix label
# -----------------------------------------------------------------------------
def matrix_class(composite_score, value_score) -> str:
    """Tag each stock for the Momentum + Value matrix quadrant."""
    c, v = _f(composite_score), _f(value_score)
    if c >= 65 and v >= 65:
        return "Best Crossover"
    if c >= 70 and v < 60:
        return "Momentum Leader"
    if v >= 70 and c < 60:
        return "Value Recovery"
    if c < 50 and v < 50:
        return "Avoid"
    return "Mixed"


MATRIX_REMARKS = {
    "Best Crossover":   "Corrected stock now regaining momentum. Highest interest.",
    "Momentum Leader":  "Good for a momentum trade; not necessarily cheap.",
    "Value Recovery":   "Recovery setup. Wait for confirmation.",
    "Mixed":            "Average on both axes. Watch only.",
    "Avoid":            "Weak on both momentum and value. Avoid.",
}
