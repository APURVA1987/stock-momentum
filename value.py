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


# =============================================================================
# v2 PHASE 3 - VALUE / QUALITY-GROWTH SCAN (Sections 33-39)
# =============================================================================
# Fundamentals-FIRST 3-5 year scan. Consumes the sub-scores produced by
# fundamentals.score_fundamentals() (Phase 2) plus the raw fundamentals dict.
# value.py imports NOTHING from scanner.py (rule Section 46).
# -----------------------------------------------------------------------------
import math

NONFIN_PE_CAP = 25.0           # fair-PE cap when no sector median is available
CYCLICAL_PE_CAP = 18.0         # tighter cap for cyclical sectors
GSEC_YIELD = 7.0               # ~10Y G-Sec yield (%) for the earnings-yield test
CYCLICAL_SECTORS = {"metals", "mining", "cement", "auto", "auto ancillary",
                    "sugar", "realty", "infrastructure", "capital goods",
                    "chemicals", "energy", "power", "shipping"}


def _vf(f, k, default=float("nan")):
    """Safe float getter for the fundamentals dict (NaN-tolerant)."""
    v = (f or {}).get(k, default)
    try:
        return default if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)
    except (TypeError, ValueError):
        return default


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def fair_pe(f, sector: str, sector_pe_median: float) -> float:
    """Fair P/E = min(sector median, own 5Y median) when available, else a cap."""
    cands = []
    if not math.isnan(_vf({"x": sector_pe_median}, "x", float("nan"))) and sector_pe_median > 0:
        cands.append(sector_pe_median)
    own5 = _vf(f, "pe_5y_median")
    if not math.isnan(own5) and own5 > 0:
        cands.append(own5)
    if cands:
        return float(min(cands))
    sec = str(sector or "").strip().lower()
    return CYCLICAL_PE_CAP if sec in CYCLICAL_SECTORS else NONFIN_PE_CAP


# -----------------------------------------------------------------------------
# Section 33: Valuation engine (growth-adjusted)
# -----------------------------------------------------------------------------
def score_valuation(f: dict, growth_score: float, sector: str = "",
                    sector_pe_median: float = float("nan")) -> dict:
    """Return {Valuation Score, Valuation Flag}."""
    if not f:
        return {"Valuation Score": float("nan"), "Valuation Flag": "No Data"}
    pe = _vf(f, "pe_ttm")
    pb = _vf(f, "pb")
    peg = _vf(f, "peg")
    sc = 0
    flag = "-"
    # PEG (30)
    if not math.isnan(peg):
        sc += 30 if peg <= 1.0 else 22 if peg <= 1.5 else 12 if peg <= 2.0 else 4 if peg <= 3 else 0
    # P/E vs sector median (25)
    if not math.isnan(pe) and not math.isnan(sector_pe_median) and sector_pe_median > 0:
        ratio = pe / sector_pe_median
        sc += 25 if ratio <= 0.8 else 18 if ratio <= 1.0 else 9 if ratio <= 1.3 else 3
    elif not math.isnan(pe):
        sc += 18 if pe <= 18 else 9 if pe <= 30 else 3
    # Earnings yield vs G-Sec (20)
    if not math.isnan(pe) and pe > 0:
        ey = 100.0 / pe
        spread = ey - GSEC_YIELD
        sc += 20 if spread > 0 else 10 if spread > -2 else 0
    # P/B (15) - skip for asset-light
    if not math.isnan(pb):
        sc += 15 if pb <= 3 else 9 if pb <= 5 else 4 if pb <= 8 else 0
    else:
        sc += 7
    # P/E below own 5Y median (10)
    own5 = _vf(f, "pe_5y_median")
    if not math.isnan(own5) and not math.isnan(pe) and own5 > 0:
        sc += 10 if pe <= own5 else 5 if pe <= own5 * 1.1 else 0
    sc = int(min(100, sc))
    # Growth-adjusted guard (Section 33): expensive non-compounder
    if not math.isnan(peg) and peg > 2.5 and _vf({"g": growth_score}, "g", 0) < 60:
        sc = min(sc, 30)
        flag = "Expensive vs Growth"
    return {"Valuation Score": sc, "Valuation Flag": flag}


# -----------------------------------------------------------------------------
# Section 35: Expected 3-5 year CAGR estimator (transparent heuristic)
# -----------------------------------------------------------------------------
def expected_cagr(f: dict, quality_score: float, sector: str = "",
                  sector_pe_median: float = float("nan")) -> dict:
    """Return {Expected CAGR %, CAGR from Growth, CAGR from Re-rating,
    CAGR from Yield, CAGR Band}. An ESTIMATE, never a promise."""
    if not f:
        return {"Expected CAGR %": float("nan"), "CAGR from Growth": float("nan"),
                "CAGR from Re-rating": float("nan"), "CAGR from Yield": float("nan"),
                "CAGR Band": "No Data"}
    p3 = _vf(f, "pat_cagr_3y", 0); p5 = _vf(f, "pat_cagr_5y", 0); rv3 = _vf(f, "rev_cagr_3y", 0)
    g_earn = _clamp(0.5 * p3 + 0.3 * p5 + 0.2 * rv3, 0, 30)
    qf = _clamp(_vf({"q": quality_score}, "q", 50) / 100.0, 0, 1)
    g_sustained = g_earn * (0.6 + 0.4 * qf)
    pe = _vf(f, "pe_ttm")
    fpe = fair_pe(f, sector, sector_pe_median)
    if not math.isnan(pe) and pe > 0 and fpe > 0:
        pe_gap = (fpe - pe) / pe
        rerate = _clamp(pe_gap, -0.40, 0.40) / 5 * 100
    else:
        rerate = 0.0
    dy = _vf(f, "div_yield", 0)
    if math.isnan(dy):
        dy = 0.0
    total = round(_clamp(g_sustained + rerate + dy, -10, 35), 1)
    band = ("High Compounder" if total >= 20 else "Target Compounder" if total >= 15
            else "Steady" if total >= 10 else "Below Goal")
    return {"Expected CAGR %": total,
            "CAGR from Growth": round(g_sustained, 1),
            "CAGR from Re-rating": round(rerate, 1),
            "CAGR from Yield": round(dy, 1),
            "CAGR Band": band}


# -----------------------------------------------------------------------------
# Section 45 (future->now): DCF-lite cross-check on Expected CAGR
# -----------------------------------------------------------------------------
def dcf_lite_cagr(f: dict, quality_score: float, sector: str = "",
                  sector_pe_median: float = float("nan"), years: int = 4) -> dict:
    """A SECOND, independent CAGR estimate using a simple forward earnings model.

    Works entirely in P/E space (we have P/E + price, not absolute EPS):
        E0  = P0 / pe                       (today's earnings per share, scaled)
        E_n = E0 * (1+g)^n                  (grow earnings n years)
        P_n = E_n * fair_pe                 (exit at the fair multiple)
        price CAGR = (P_n/P0)^(1/n) - 1 = (1+g) * (fair_pe/pe)^(1/n) - 1
    Then add the dividend yield. This COMPOUNDS the re-rating (vs the heuristic
    Expected CAGR which spreads it linearly), so the two genuinely differ and
    their gap is a confidence signal - not a second copy of the same number.
    """
    if not f:
        return {"DCF CAGR %": float("nan"), "CAGR Confidence": "No Data",
                "CAGR Divergence": float("nan")}
    pe = _vf(f, "pe_ttm")
    if math.isnan(pe) or pe <= 0:
        return {"DCF CAGR %": float("nan"), "CAGR Confidence": "No PE",
                "CAGR Divergence": float("nan")}
    p3 = _vf(f, "pat_cagr_3y", 0); p5 = _vf(f, "pat_cagr_5y", 0); rv3 = _vf(f, "rev_cagr_3y", 0)
    g_earn = _clamp(0.5 * p3 + 0.3 * p5 + 0.2 * rv3, 0, 30) / 100.0
    qf = _clamp(_vf({"q": quality_score}, "q", 50) / 100.0, 0, 1)
    g = g_earn * (0.6 + 0.4 * qf)                     # quality-haircut growth
    fpe = fair_pe(f, sector, sector_pe_median)
    rerate_factor = (fpe / pe) ** (1.0 / max(1, years))
    dy = _vf(f, "div_yield", 0)
    dy = 0.0 if math.isnan(dy) else dy
    dcf = ((1 + g) * rerate_factor - 1) * 100 + dy
    dcf = round(_clamp(dcf, -15, 40), 1)
    return {"DCF CAGR %": dcf}


def cagr_cross_check(expected_cagr: float, dcf_cagr: float) -> dict:
    """Compare the heuristic Expected CAGR with the DCF-lite estimate.
    Small gap = high confidence; large gap = the two models disagree."""
    e, d = _f(expected_cagr, float("nan")), _f(dcf_cagr, float("nan"))
    if math.isnan(e) or math.isnan(d):
        return {"CAGR Divergence": float("nan"), "CAGR Confidence": "No Data"}
    gap = abs(e - d)
    conf = "High" if gap <= 3 else "Medium" if gap <= 6 else "Low"
    return {"CAGR Divergence": round(e - d, 1), "CAGR Confidence": conf}


# -----------------------------------------------------------------------------
# Section 36: Composite Value Score
# -----------------------------------------------------------------------------
def composite_value(quality, growth, valuation, balance, promoter) -> float:
    q, g, v = _f(quality), _f(growth), _f(valuation)
    b, p = _f(balance), _f(promoter)
    return int(round(0.30 * q + 0.25 * g + 0.20 * v + 0.15 * b + 0.10 * p))


# -----------------------------------------------------------------------------
# Section 34 + 36: Value Trap precedence, then Value Class
# -----------------------------------------------------------------------------
VALUE_CLASS_REMARKS = {
    "Compounder": "Core 3-5 yr candidate. Accumulate in zones.",
    "Quality-Growth Watch": "Good business; wait for a better price or more proof.",
    "Cyclical Value": "Cyclical / re-rating play. Size smaller, watch the cycle.",
    "Turnaround": "Speculative recovery. Small position, proof required.",
    "Fundamentals Missing": "Cannot verify. Technical-only - do not size as core.",
    "Value Avoid": "Avoid. Weak business / governance / solvency.",
}


def value_class(scores: dict, f: dict, exp_cagr: float, gate_pass: bool,
                sector_status: str, illiquid: bool, slope200: float) -> dict:
    """Return {Value Class, Value Tier, Value Class Remark}."""
    q = _f(scores.get("Quality Score")); g = _f(scores.get("Growth Score"))
    val = _f(scores.get("Valuation Score")); comp = _f(scores.get("Composite Value"))
    pledge = _vf(f, "pledge", 0); pc = _vf(f, "promoter_change_3y", 0)
    ocf = _vf(f, "ocf_3y", 1); ic = _vf(f, "interest_coverage", 9); de = _vf(f, "debt_to_equity", 0)
    rv3 = _vf(f, "rev_cagr_3y", 0); p3 = _vf(f, "pat_cagr_3y", 0)

    # ---- Section 34: Trap / Avoid precedence (runs FIRST) ----
    trap = (
        q < 35 or pledge > 40 or pc < -8 or (not math.isnan(ocf) and ocf <= 0)
        or (ic < 1.0 and de > 1.5) or illiquid
        or (rv3 < 0 and p3 < 0 and slope200 < 0))
    if trap:
        cls = "Value Avoid"
    elif gate_pass and comp >= 70 and exp_cagr >= 15:
        cls = "Compounder"
    elif gate_pass and (60 <= comp < 70 or 12 <= exp_cagr < 15):
        cls = "Quality-Growth Watch"
    elif 45 <= q < 60 and val >= 65 and sector_status != "Weak":
        cls = "Cyclical Value"
    elif 35 <= q < 50 and p3 > 0 and (not math.isnan(ocf) and ocf > 0):
        cls = "Turnaround"
    else:
        cls = "Quality-Growth Watch" if comp >= 55 else "Value Avoid"

    # Conviction tier within Compounder
    tier = "-"
    if cls == "Compounder":
        promoter = _f(scores.get("Promoter Score"))
        if comp >= 78 and exp_cagr >= 18 and promoter >= 70 and val >= 55:
            tier = "A"
        elif val < 45:
            tier = "C"
        else:
            tier = "B"
    return {"Value Class": cls, "Value Tier": tier,
            "Value Class Remark": VALUE_CLASS_REMARKS.get(cls, "")}


# -----------------------------------------------------------------------------
# Section 37: Value entry / timing overlay (technicals as servant)
# -----------------------------------------------------------------------------
def value_timing(m: dict, cls: str, exp_cagr: float) -> dict:
    cmp_ = _f(m.get("CMP")); ma200 = _f(m.get("200 DMA")); ma50 = _f(m.get("50 DMA"))
    slope200 = _f(m.get("200 DMA Slope %"))
    over = str(m.get("Overextended", "No")) == "Yes"
    dist200 = _f(m.get("Distance from 200 DMA %"), 99)

    if cls not in ("Compounder", "Quality-Growth Watch", "Cyclical Value"):
        style = "No accumulation (not a core candidate)"
    elif over:
        style = "Wait for pullback (alert at 20/50 DMA)"
    elif abs(dist200) <= 5 and slope200 > 0:
        style = "Accumulate near 200 DMA (1/3 now, add on 5% dips)"
    elif cmp_ > ma50:
        style = "SIP / staggered (monthly tranches)"
    else:
        style = "Wait for reclaim of 50 DMA"

    lo = max(ma200, cmp_ * 0.90) if ma200 > 0 else cmp_ * 0.90
    zone = f"{round(lo, 2)} - {round(cmp_ * 1.02, 2)}"
    t3 = round(cmp_ * (1 + _f(exp_cagr) / 100.0) ** 3, 2) if cmp_ > 0 else None
    t5 = round(cmp_ * (1 + _f(exp_cagr) / 100.0) ** 5, 2) if cmp_ > 0 else None
    return {
        "Accumulation Zone": zone,
        "Value Entry Style": style,
        "Value Invalidation": ("Reassess if 2 quarters of PAT decline, ROCE < 12, "
                               "D/E > 1.5, or promoter pledge appears."),
        "Value Target 3-5Y": f"{t3} - {t5}" if t3 else "-",
    }


# -----------------------------------------------------------------------------
# Section 38/39: Crossover Buy + new Momentum+Value matrix
# -----------------------------------------------------------------------------
def crossover_buy(value_cls: str, momentum_class: str, spring_ready: bool,
                  overextended: bool, illiquid: bool) -> bool:
    return bool(
        value_cls in ("Compounder", "Quality-Growth Watch")
        and (spring_ready or momentum_class in ("Actionable Breakout", "Elite Momentum"))
        and not overextended and not illiquid)


def matrix_class_qg(composite_momentum, composite_value, value_cls,
                    crossover: bool) -> str:
    """Section 39 matrix using the FUNDAMENTALS composite value."""
    cm, cv = _f(composite_momentum), _f(composite_value)
    if crossover:
        return "Crossover Buy"
    if value_cls == "Compounder" and cm < 65:
        return "Compounder (accumulate)"
    if cm >= 70 and cv < 55:
        return "Momentum Leader"
    if 60 <= cv <= 70:
        return "Quality Watch"
    if value_cls in ("Cyclical Value", "Turnaround"):
        return "Cyclical / Turnaround"
    if value_cls == "Value Avoid" or (cm < 50 and cv < 50):
        return "Avoid"
    return "Mixed"


MATRIX_QG_REMARKS = {
    "Crossover Buy": "Best - quality business + timing align.",
    "Compounder (accumulate)": "Buy in zones, ignore short-term chart.",
    "Momentum Leader": "Trade only; not a hold. Trail tight.",
    "Quality Watch": "Wait for price or proof.",
    "Cyclical / Turnaround": "Smaller size, cycle-aware.",
    "Avoid": "Skip.",
    "Mixed": "Average on both - watch only.",
}
