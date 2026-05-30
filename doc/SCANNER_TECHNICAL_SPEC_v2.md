# SCANNER_TECHNICAL_SPEC.md  (v2 — Two-Scan Architecture)

> Technical reference for the NSE dual-engine dashboard. v2 separates the
> system into **two distinct scans that never share scoring logic**:
>
> 1. **MOMENTUM SCAN** — 15–30 day swing + early pre-breakout detection.
> 2. **VALUE / QUALITY-GROWTH SCAN** — 3–5 year hold, targeting businesses with
>    a modelled ~15–20% CAGR. This scan is NO LONGER technical-only; it now has
>    a required fundamentals layer.
>
> Companion file: `WEBSITE_HANDOFF.md` — UI, tabs, exports, dev rules.
>
> CHANGE LOG v1 -> v2 (read this first):
> - The old "Technical Value Scanner" (v1 Sections 16–19) was a second momentum
>   scanner mislabelled as value. It is REPLACED by the Value/Quality-Growth
>   scan (Sections 30–37). The old mean-reversion logic is preserved but renamed
>   **"Technical Recovery"** and demoted to a momentum-side sub-engine — it is no
>   longer the thing that answers "find me a 3–5 year compounder".
> - Momentum gains a real **Pre-Breakout / Coiled Spring** ranked engine, a
>   **Volume Accumulation layer**, and **VCP contraction counting** (Sections
>   10A–10C, 11A).
> - A **Fundamentals layer** (Section 30) is now mandatory input to the Value
>   scan and an optional gate on Momentum.

---

## 0. The Two Scans At A Glance

| | MOMENTUM SCAN | VALUE / QUALITY-GROWTH SCAN |
|---|---|---|
| Horizon | 15–30 day swing | 3–5 years |
| Question answered | "What is breaking out or about to?" | "What can compound at 15–20% for 3–5 yrs?" |
| Primary inputs | Price/volume/trend technicals | Fundamentals FIRST, technicals as timing |
| Fundamentals required? | Optional gate | **Mandatory** |
| Headline outputs | Strong Breakout, Spring Ready, Fresh Momentum, Elite Momentum | Compounder, Quality-Growth Watch, Cyclical Value, Avoid |
| Hard "do not chase" guard | Yes (Section 12) | Replaced by valuation-vs-growth guard (Section 34) |
| Entry style | Breakout / pullback retest | Staggered accumulation / SIP in zones |

The two scans run off the **same `compute_metrics` core** (Sections 4 + 30) and
the **same universe** (Section 3) so a single download serves both. A stock can
appear in both lists — that overlap (cheap-ish quality stock that is ALSO
breaking out) is the single highest-value signal and is flagged
**"Crossover Buy"** (Section 38).

---

## 1. Objective (per scan)

### Momentum scan outputs
| Engine | Output |
|--------|--------|
| Trend / momentum | Strong Breakout / Actionable, Wait for Confirmation, Early Watchlist, Rejected |
| Composite momentum class | Elite Momentum, Actionable Breakout, Wait for Confirmation, Early Watchlist, Ignore |
| Relative Strength | RS Score (0–100), RS Rank, RS Leader flag |
| Sector Rotation | Sector Strength Score, Sector Rank, Sector Status |
| **Pre-Breakout / Coiled Spring** | Spring Score (0–100) + **Spring Ready** flag + VCP contraction count + trigger (Section 10A) |
| **Volume Accumulation** | Accumulation Score (0–100) + A/D state (Section 10C) |
| Fresh Momentum | Fresh Momentum Score + flag |
| Technical Recovery (was "Value") | Recovery Score + Recovery Class (Section 11B) |
| Do Not Chase | Overextended flag + reason + wait condition |
| Breakout Quality | 0–100 + status |
| Pullback Quality | Type + 0–100 + remark |
| Holdings overlay | holding_action + holding_remark |

### Value / Quality-Growth scan outputs
| Engine | Output |
|--------|--------|
| **Fundamentals** | Quality Score, Growth Score, Balance-Sheet Score, Promoter Score (Section 31) |
| **Valuation** | Valuation Score + PEG-style growth-adjusted flag (Section 33) |
| **Expected CAGR** | Modelled 3–5 yr CAGR % estimate (Section 35) |
| **Composite Value** | 0–100 + Value Class: Compounder / Quality-Growth Watch / Cyclical Value / Turnaround / Avoid (Section 36) |
| Timing overlay | Accumulation Zone, staggered-entry plan, invalidation (Section 37) |

---

## 2. Data Source

(unchanged from v1 — Yahoo Finance via `yfinance`, `.NS` suffix, daily OHLCV,
batched download, local cache + bhavcopy overlay, intraday-bar stripping.)

**v2 addition — fundamentals feed:**
- **Provider**: a **Screener.in CSV export** (per-stock or a combined batch
  CSV), loaded by `fundamentals.load_fundamentals(path)`.
- Optional secondary: a single bulk fundamentals CSV the user maintains
  (`data/fundamentals.csv`) keyed by `symbol`.
- The fundamentals load is **cached** (`data/fundamentals_cache.pkl`) and only
  refreshed on demand — it does NOT add a per-stock network call to the scan
  (respects the Section 27 rule 9 speed budget).
- If fundamentals are missing for a symbol, that symbol can still appear in the
  **Momentum** scan but is held out of the **Compounder** value class and tagged
  `Fundamentals Missing` (it may still surface as `Cyclical Value` on technicals
  alone, clearly flagged as unverified).

---

## 3. Stock Universe

(unchanged — `universe.csv`, 751 stocks / 43 sectors, NSE constituent uploads
override, holdings always appended. See v1 Section 3.)

**v2 note:** add an optional `isin` column to `universe.csv` to make
Screener.in CSV joins reliable when symbols rename (ZOMATO->ETERNAL etc.).

---

## 4. Core Technical Indicators

All of v1 Section 4 is retained verbatim. The following metrics are **ADDED** to
`compute_metrics` (raw keys prefixed `_`, display keys named):

| Metric | Formula | Used by |
|--------|---------|---------|
| `OBV` | running sum of `sign(close.diff) * volume` | Accumulation (10C) |
| `OBV Slope 20D %` | linear fit of last 20 OBV values, % of mean | Accumulation, Spring |
| `A/D Line` | cumulative `((close-low)-(high-close))/(high-low) * volume` | Accumulation (10C) |
| `A/D Slope 20D` | linear fit of last 20 A/D values | Accumulation (10C) |
| `Up/Down Vol Ratio 30D` | (already in v1) avg up-day vol / avg down-day vol | Accumulation |
| `Volume Pocket 10D` | count of last 10 days where `down-day vol < 0.6 * avg_vol_20` | Pocket pivot (10A) |
| `Pocket Pivot` | up-day where `vol > max(down-day vol of last 10 days)` AND `cmp > 10 DMA` | Spring trigger (10A) |
| `VCP Contractions` | count of successive lower-amplitude pullbacks in last 90D (Section 11A) | Spring (10A) |
| `Tightness Ratio` | `Range 10D % / Range 60D %` (already implied; now a named col) | Spring, Recovery |
| `NR7` | last bar range is the narrowest of last 7 bars (bool) | Spring (10A) |
| `Inside Bar` | last bar high<prev high AND low>prev low (bool) | Spring (10A) |
| `Base Depth %` | `(base_high - base_low)/base_high * 100` over last 40D | Spring (10A) |
| `Base Length D` | trading days since the base's first touch of base_high*0.97 | Spring (10A) |
| `52W High Age D` | days since the 52W high print | Spring, Breakout |
| `Distance from 10 DMA %` | `(cmp/ma10 - 1)*100` | Pocket pivot, overextension |
| `10 DMA` | `close.rolling(10).mean()` | Pocket pivot |
| `Avg Turnover 20D ₹` | `mean(close*volume, 20)` | **Liquidity floor** (4A) |

### 4A. Liquidity floor (NEW — applies to BOTH scans)
v1 only rejected `Volume Ratio < 1.0`, which is not a turnover floor. Add a hard
gate by market-cap band, evaluated before any scoring:

```python
MIN_TURNOVER_LARGE  = 50_00_00_000   # ₹50 Cr/day  20D avg
MIN_TURNOVER_MID    = 5_00_00_000    # ₹5 Cr/day
MIN_TURNOVER_SMALL  = 1_00_00_000    # ₹1 Cr/day
```
A stock below its band's floor is tagged `Illiquid` and excluded from
**actionable** buckets in both scans (still shown, greyed, for holdings).
Rationale: prevents the value scan from surfacing untradeable operator microcaps
(directly addresses your Aartech/Omega pump-pattern concern).

### Tunable thresholds (top of `scanner.py`) — unchanged from v1 plus:
```python
RSI_STRONG          = 60.0
ADX_TREND           = 20.0
ADX_STRONG          = 25.0
CLOSE_POS_STRONG    = 0.75
MAX_EXT_FROM_10DMA  = 6.0     # NEW — pocket-pivot freshness
MAX_EXT_FROM_20DMA  = 10.0
MAX_EXT_FROM_200DMA = 40.0
MIN_RR              = 1.5
SCORE_STRONG        = 80
SCORE_WAIT          = 65
SCORE_WATCH_FLOOR   = 55
# NEW — Spring engine
SPRING_READY_MIN        = 70
SPRING_BASE_MAX_DEPTH   = 25.0   # base tighter than 25% to qualify as a coil
SPRING_BASE_MIN_LEN     = 15     # at least 3 weeks of base
VCP_MIN_CONTRACTIONS    = 2
OBV_ACCUM_SLOPE_MIN     = 0.0    # OBV rising while price flat = accumulation
```

---

# ============================================================
# PART I — MOMENTUM SCAN
# ============================================================

## 5–9. (Unchanged from v1)
Momentum base logic, composite scoring, Wait-for-Confirmation, RS engine,
Sector Rotation — all retained exactly as v1 Sections 5–9. Only additions
below.

### 5A. Optional fundamentals gate on Momentum (NEW, default OFF)
Sidebar toggle `momentum_quality_gate`. When ON, a Strong Breakout is demoted to
"Wait for Confirmation" if `Quality Score < 40` (Section 31) — keeps you from
chasing breakouts in junk businesses while leaving pure-technical traders free
to turn it off. Default OFF preserves v1 behaviour.

---

## 10. Coiled / Ready Engine  →  REPLACED BY 10A Pre-Breakout / Coiled Spring

The v1 Coiled engine (Section 10) is **superseded** by the richer Spring engine
below. The old Coiled Score formula is retained as one of the Spring inputs but
the flag `Coiled Ready` is replaced by `Spring Ready`. (Keep the old column for
one release for backward compat, then deprecate.)

### 10A. Pre-Breakout / Coiled Spring Score (0–100)  — YOUR EARLY-CANDIDATE DETECTOR

Goal: catch the stock **before** the breakout, while the spring is still
compressing, but only when accumulation (not neglect) is causing the
compression. A tight stock with *dying* volume on falling OBV is a dead stock;
a tight stock with *dry* down-volume but *rising* OBV is a coil. The v1 coiled
engine could not tell these apart — this one can.

| Points (max) | Condition | What it captures |
|--------------|-----------|------------------|
| 20 (tightness) | Tightness Ratio <=0.40 ->20 ; <=0.60 ->14 ; <=0.80 ->7 | range compressing |
| 15 (ATR contraction) | ATR Contraction <0.70 ->15 ; <0.85 ->10 ; <1.0 ->4 | volatility compressing |
| 15 (VCP structure) | VCP Contractions >=3 ->15 ; ==2 ->10 ; ==1 ->4 | Minervini-style tightening |
| 15 (accumulation) | OBV Slope 20D >0 AND Up/Down Vol >=1.1 ->15 ; OBV Slope>0 ->8 | smart money buying the base |
| 10 (volume dry-up) | Volume Dryup 10D <0.60 ->10 ; <0.80 ->6 | sellers exhausted |
| 10 (proximity to pivot) | Dist from 52W High >=-5 ->10 ; >=-10 ->6 ; >=-15 ->3 | near the launch point |
| 10 (trend backdrop) | cmp>50 DMA>200 DMA AND 200 DMA Slope>0 ->10 ; cmp>200 DMA ->5 | uptrend intact |
| 5 (base maturity) | SPRING_BASE_MIN_LEN<=Base Length<=90 ->5 | base neither too young nor stale |

### Spring Ready (boolean) — ALL of:
- `Spring Score >= SPRING_READY_MIN (70)`
- `cmp > 50 DMA AND cmp > 200 DMA AND 200 DMA Slope % > 0`
- `Base Depth % <= SPRING_BASE_MAX_DEPTH (25)`
- `Base Length D >= SPRING_BASE_MIN_LEN (15)`
- `VCP Contractions >= VCP_MIN_CONTRACTIONS (2)`
- `OBV Slope 20D % >= OBV_ACCUM_SLOPE_MIN (0)`  ← accumulation, not neglect
- `ATR Contraction < 0.85`
- `Distance from 52W High % >= -15`
- NOT Overextended (Section 12)

### Spring trigger / alert
```
spring_trigger = max(base_high, prev_52w_high)        # the pivot to clear
spring_alert   = spring_trigger * 0.99
breakout_confirm = close > spring_trigger AND Volume Ratio >= 1.5
```
**Decision label**: "Coiled and accumulating. Alert at pivot; enter only on
volume breakout above trigger."

### Spring vs Fresh vs Strong — when each fires (mutually informative, not exclusive)
- **Spring Ready**: tight base, near pivot, NOT yet broken out → *earliest*.
- **Fresh Momentum** (Section 11): just cleared a 20-day high with volume →
  *just triggered*.
- **Strong Breakout** (Section 5): cleared 52W high with volume, RS strong →
  *confirmed*.
A stock that is Spring Ready today and Fresh Momentum next week is the ideal
sequence; surface that transition in the dashboard as **"Spring → Fired"**.

### 10B. Pocket Pivot (NEW sub-signal)
A `Pocket Pivot` day = an up-day whose volume exceeds the highest down-day
volume of the prior 10 sessions, while `cmp > 10 DMA` and within a base. Pocket
pivots inside a Spring base add **+5** to Spring Score and set a
`Pocket Pivot` badge — an early institutional-entry footprint that often
precedes the breakout by days.

### 10C. Volume Accumulation Layer (NEW)
`scanner.accumulation_score(m)` → 0–100, surfaced as `Accumulation Score` and an
`A/D State` label. Used both as a Spring input and as a standalone column.

| Points (max) | Condition |
|--------------|-----------|
| 35 | OBV Slope 20D %: rank-scaled, rising strongly ->35, flat ->15, falling ->0 |
| 25 | A/D Slope 20D > 0 ->25 ; flat ->10 |
| 25 | Up/Down Vol Ratio 30D >=1.3 ->25 ; >=1.1 ->15 ; >=1.0 ->8 |
| 15 | Volume Pocket 10D >= 4 ->15 ; >=2 ->8  (dry down-volume) |

`A/D State`: `>=70` Accumulation · `>=45` Neutral · `else` Distribution.
**Use:** a Distribution state vetoes Spring Ready even if the chart looks tight.

---

## 11. Fresh Momentum Engine  (unchanged from v1) + 11A + 11B

### 11A. VCP Contraction Count (NEW helper, feeds Spring 10A)
Walk the last 90 sessions, segment into successive swing pullbacks (peak→trough
→ next peak). Count a "contraction" each time a pullback's depth is **smaller**
than the previous pullback's depth AND its volume is lower. `VCP Contractions` =
number of successive shrinking contractions ending at the current bar. 3+ tight,
shrinking, lower-volume pullbacks is the classic Volatility Contraction Pattern.

### 11B. Technical Recovery Engine (RENAMED from v1 "Value Scanner")
The entire v1 Section 16–19 mean-reversion logic moves here, **unchanged in
math**, but renamed and re-homed as a momentum-side sub-engine for catching
bounces off support. Columns rename:
- `Value Score` → `Recovery Score`
- `Value Classification` → `Recovery Class` (Reversal Ready / Base Forming /
  Deep Value High Risk / Trap Avoid → renamed "Bounce Trap Avoid")
- `Value Entry Style` → `Recovery Entry Style`

This keeps the useful "fell and is bouncing technically" signal but stops it
masquerading as long-term value. **Nothing in the Value/Quality-Growth scan
(Part II) reads these columns.**

---

## 12. Do Not Chase / Overextension Engine
(unchanged from v1) — now also gates Spring Ready (above) and is shown on the
momentum dashboard only.

## 13. Breakout Quality Score
(unchanged) + add **+5 if `52W High Age D <= 5`** (a *fresh* high beats a stale
one). Cap stays 100.

## 14. Pullback Quality Score
(unchanged from v1.)

## 15. Composite Momentum Score
(unchanged formula.) **v2 addition:** expose `Spring Score` and
`Accumulation Score` as columns so the momentum table can be sorted by
"earliness" (Spring) vs "confirmation" (Composite).

### Momentum dashboard ordering recommendation
Default sort the momentum actionable list by a blended **Momentum Readiness**:
```
readiness = 0.5 * Composite + 0.3 * Spring Score + 0.2 * Accumulation Score
```
so confirmed breakouts and high-quality coils both rank, and dead tight stocks
(low accumulation) sink.

---

# ============================================================
# PART II — VALUE / QUALITY-GROWTH SCAN  (NEW — replaces v1 16–19)
# ============================================================

## 30. Fundamentals Layer (mandatory input)

`fundamentals.load_fundamentals()` returns, per symbol, the fields below. All are
optional-but-scored; missing fields cost points rather than crash. Source:
Screener.in CSV export (the "Export to Excel" data sheet) parsed by
`fundamentals.parse_screener`.

| Field | Screener source | Notes |
|-------|-----------------|-------|
| `rev_cagr_3y %` | Sales growth 3Y | top-line durability |
| `rev_cagr_5y %` | Sales growth 5Y | |
| `pat_cagr_3y %` | Profit growth 3Y | |
| `pat_cagr_5y %` | Profit growth 5Y | |
| `roce_ttm %` | ROCE | capital efficiency |
| `roce_5y_avg %` | ROCE 5Y avg | consistency |
| `roe_ttm %` | ROE | |
| `roe_5y_avg %` | ROE 5Y avg | |
| `opm_ttm %` | OPM | margin level |
| `opm_trend` | last 4 OPM points | expanding / stable / contracting |
| `debt_to_equity` | Debt/Equity | balance-sheet risk |
| `interest_coverage` | EBIT / Interest | solvency |
| `ocf_3y ₹` | Cash from operations 3Y sum | earnings quality |
| `ocf_to_pat` | OCF / net profit (3Y) | >0.7 = real earnings |
| `promoter_holding %` | Promoter holding latest | skin in the game |
| `promoter_change_3y %` | promoter holding delta 3Y | declining = red flag |
| `pledge %` | promoter pledge | >25% = serious risk |
| `pe_ttm` | P/E | for valuation engine |
| `pb` | P/B | |
| `peg` | PEG (or computed pe/pat_cagr) | growth-adjusted |
| `sales_5y ₹` , `mcap ₹` | for size/quality sanity | |

Cache + on-demand refresh as in Section 2. No per-stock network call during the
scan.

---

## 31. Fundamental Sub-Scores

`fundamentals.score_fundamentals(f)` returns four sub-scores. Each handles
missing data by awarding the neutral midpoint and flagging `partial`.

### Quality Score (0–100) — "is this a good business?"
| Points (max) | Condition |
|--------------|-----------|
| 25 | ROCE TTM >=20 ->25 ; >=15 ->18 ; >=12 ->10 ; else 0 |
| 15 | ROCE 5Y avg >=15 ->15 ; >=12 ->9 |
| 15 | ROE TTM >=18 ->15 ; >=14 ->10 ; >=10 ->5 |
| 15 | OCF/PAT >=0.8 ->15 ; >=0.6 ->9 ; >=0.4 ->4  (earnings quality) |
| 15 | OPM trend expanding ->15 ; stable ->9 ; contracting ->0 |
| 15 | Interest coverage >=5 ->15 ; >=3 ->9 ; >=1.5 ->4 |

### Growth Score (0–100) — "is it compounding?"
| Points (max) | Condition |
|--------------|-----------|
| 30 | PAT CAGR 3Y >=20 ->30 ; >=15 ->22 ; >=10 ->12 ; >=5 ->5 |
| 20 | PAT CAGR 5Y >=18 ->20 ; >=12 ->12 ; >=8 ->6 |
| 25 | Rev CAGR 3Y >=18 ->25 ; >=12 ->17 ; >=8 ->9 ; >=5 ->4 |
| 15 | Rev CAGR 5Y >=15 ->15 ; >=10 ->9 ; >=6 ->4 |
| 10 | PAT CAGR 3Y >= Rev CAGR 3Y (operating leverage / margin expansion) ->10 |

### Balance-Sheet Score (0–100)
| Points (max) | Condition |
|--------------|-----------|
| 40 | D/E <=0.3 ->40 ; <=0.6 ->28 ; <=1.0 ->15 ; <=1.5 ->5 ; else 0  (NBFC/finance exempt — see note) |
| 30 | Interest coverage >=6 ->30 ; >=3 ->18 ; >=1.5 ->6 |
| 30 | OCF 3Y > 0 AND OCF/PAT >=0.6 ->30 ; OCF>0 ->15 |

> **Financials exemption:** for `sector in {Banking, NBFC, Finance, Insurance}`,
> D/E is structurally high and meaningless — substitute the D/E points with a
> proxy: GNPA trend / CASA / capital-adequacy if present in the CSV, else award
> the neutral midpoint and flag `bs_proxy`. (Directly handles your CHOLAFIN-style
> "D/E 5.8x is normal for an NBFC" point.)

### Promoter / Governance Score (0–100)
| Points (max) | Condition |
|--------------|-----------|
| 40 | Promoter holding >=50 ->40 ; >=40 ->28 ; >=30 ->15 ; else 5 |
| 30 | Promoter change 3Y >=0 ->30 ; >=-2 ->18 ; >=-5 ->8 ; else 0 (declining = penalty) |
| 30 | Pledge ==0 ->30 ; <=10 ->18 ; <=25 ->8 ; else 0 |

---

## 32. Fundamentals Quality Gate (hard, for Compounder class)
A stock can only be classed **Compounder** (Section 36) if ALL of:
- `Quality Score >= 60`
- `Growth Score >= 55`
- `Balance-Sheet Score >= 55` (or financials proxy passed)
- `Promoter Score >= 50` AND `pledge <= 25` AND `promoter_change_3y >= -5`
- fundamentals not `partial` on more than 2 fields

Fails → routes to a lower class but is NOT auto-rejected (may be Cyclical Value
or Quality-Growth Watch).

---

## 33. Valuation Engine (growth-adjusted)

`value.score_valuation(f, sector_pe_median)` → `Valuation Score` 0–100.

| Points (max) | Condition |
|--------------|-----------|
| 30 | PEG <=1.0 ->30 ; <=1.5 ->22 ; <=2.0 ->12 ; <=3 ->4 ; else 0 |
| 25 | P/E vs sector median: <=0.8x median ->25 ; <=1.0x ->18 ; <=1.3x ->9 ; else 3 |
| 20 | Earnings yield (1/PE) vs 10Y G-Sec: spread >0 ->20 ; >-2 ->10 |
| 15 | P/B <=3 ->15 ; <=5 ->9 ; <=8 ->4  (skip for asset-light/IT — flag) |
| 10 | P/E below own 5Y median P/E (if available) ->10 ; near ->5 |

**Growth-adjusted guard (the anti-"expensive non-compounder" rule):** if
`PEG > 2.5` AND `Growth Score < 60`, force `Valuation Score <= 30` and tag
`Expensive vs Growth`. This is what stops the scan calling a 70x-P/E, 8%-growth
stock a value buy.

---

## 34. Value Trap / Avoid Precedence (overrides classification)
`Value Avoid` if ANY of:
- `Quality Score < 35` (poor business — most important)
- `pledge > 40` OR `promoter_change_3y < -8` (governance)
- `OCF 3Y <= 0` (no real cash — earnings suspect)
- `interest_coverage < 1.0` AND `debt_to_equity > 1.5` (solvency)
- `Illiquid` (Section 4A)
- `rev_cagr_3y < 0 AND pat_cagr_3y < 0 AND 200 DMA Slope % < 0` (declining
  business in a downtrend — classic value trap)

This precedence runs FIRST, before any positive class is assigned.

---

## 35. Expected 3–5 Year CAGR Estimator (NEW — answers your headline goal)

`value.expected_cagr(f)` produces a transparent, conservative modelled CAGR so
the scan literally surfaces the ~15–20% candidates. It is an ESTIMATE, labelled
as such, never a promise.

```
# 1. Earnings growth driver (blend, weighted to recent + sustainable)
g_earn = 0.5*pat_cagr_3y + 0.3*pat_cagr_5y + 0.2*rev_cagr_3y
g_earn = clamp(g_earn, 0, 30)          # cap optimism at 30%

# 2. Sustainability haircut from quality
quality_factor = QualityScore/100      # 0..1
g_sustained = g_earn * (0.6 + 0.4*quality_factor)   # weak quality -> bigger haircut

# 3. Valuation re-rating / de-rating drag over the holding period (5y normalisation)
#    If currently cheap vs fair (sector median PE), allow modest re-rating; if
#    expensive, subtract de-rating drag.
pe_gap = (fair_pe - pe_ttm) / pe_ttm           # +ve = cheap
rerate_cagr = clamp(pe_gap, -0.40, 0.40) / 5 * 100   # spread the gap over 5 yrs

# 4. Dividend yield add-back (if present)
expected_cagr = g_sustained + rerate_cagr + div_yield
expected_cagr = round(clamp(expected_cagr, -10, 35), 1)
```
`fair_pe` = min(sector median P/E, own 5Y median P/E) when available, else a
cap of 25 for non-financials / 18 for cyclicals.

Output columns: `Expected CAGR %`, plus the three components
(`CAGR from Growth`, `CAGR from Re-rating`, `CAGR from Yield`) for transparency
in the Value Deep Dive.

**CAGR Band label:** `>=20%` High Compounder · `15–20%` Target Compounder ·
`10–15%` Steady · `<10%` Below Goal.

---

## 36. Composite Value Score & Classification

```
Composite Value = 0.30*Quality + 0.25*Growth + 0.20*Valuation
                + 0.15*BalanceSheet + 0.10*Promoter
```
(All sub-scores 0–100. Technicals are NOT in this score — they only affect
*timing* in Section 37.)

### Value Class (Trap precedence from Section 34 runs first)
| Class | Rule | Meaning / Action |
|-------|------|------------------|
| **Compounder** | passes Section 32 gate AND Composite Value >=70 AND Expected CAGR >=15 | "Core 3–5 yr candidate. Accumulate in zones." |
| **Quality-Growth Watch** | passes gate AND Composite Value 60–70, OR Expected CAGR 12–15 | "Good business, wait for better price or proof." |
| **Cyclical Value** | Quality 45–60 AND Valuation >=65 AND sector upturn (Sector Status != Weak) | "Cyclical / re-rating play. Size smaller, watch the cycle." |
| **Turnaround** | Quality 35–50 AND Growth improving (latest>prior) AND OCF>0 | "Speculative recovery. Small position, proof required." |
| **Fundamentals Missing** | fundamentals absent | "Cannot verify. Technical-only — do not size as core." |
| **Avoid** | Section 34 trap precedence | "Avoid. Weak business / governance / solvency." |

### Conviction tiers within Compounder
- **A (highest)**: Composite Value >=78 AND Expected CAGR >=18 AND
  Promoter Score >=70 AND Valuation Score >=55.
- **B**: meets Compounder gate, Composite 70–78.
- **C**: meets gate but Valuation Score < 45 (great business, rich price → wait
  for dips).

---

## 37. Value Entry / Timing Overlay (technicals as servant, not master)

Technicals do not pick the value stock; they only choose *when* to deploy into
an already-qualified one.

| Situation (for Compounder/Quality-Growth) | Entry style | Trigger |
|-------------------|-------------|---------|
| `cmp` within 5% of 200 DMA AND 200 DMA Slope>0 | **Accumulate near 200 DMA** | staggered: 1/3 now, add on each 5% dip |
| `cmp > 50 DMA`, uptrend, not extended | **SIP / staggered** | monthly tranches, ignore noise |
| Overextended (Section 12) | **Wait for pullback** | alert at 20/50 DMA |
| In a Spring base (Section 10A) AND Compounder | **Crossover Buy (best)** | buy the Spring breakout — fundamentals + timing align |

```
accumulation_zone = [max(200 DMA, cmp*0.90), cmp*1.02]
invalidation      = thesis-based, NOT a tight technical stop:
                    "Reassess if 2 consecutive quarters of PAT decline OR
                     ROCE drops below 12 OR D/E rises above 1.5 OR
                     promoter pledge appears."
target_zone       = 3–5 yr, from Expected CAGR compounding:
                    cmp * (1 + Expected CAGR/100)^3   to   ^5
```
Note the deliberate difference from momentum: value invalidation is a
**fundamental** trigger, not a price stop. This matches your "exit only on real
deterioration" rule.

---

## 38. Crossover Buy — the dual-scan jackpot signal (NEW)

`crossover.flag(momentum_row, value_row)`:
```
Crossover Buy if:
  value_class in {Compounder, Quality-Growth Watch}
  AND ( Spring Ready  OR  Momentum Class in {Actionable Breakout, Elite Momentum} )
  AND NOT Overextended
  AND NOT Illiquid
```
Meaning: a verified 15–20% CAGR business that is ALSO technically breaking out
or coiling. This is the highest-priority list in the whole dashboard — surface
it as its own tab/section at the very top.

---

## 39. Momentum + Value Matrix (replaces v1 Section 20)

`matrix_class(composite_momentum, composite_value, expected_cagr)`:

| Label | Rule | Meaning |
|-------|------|---------|
| **Crossover Buy** | Section 38 passes | Best — quality + timing. |
| **Compounder (accumulate)** | value Compounder, momentum < 65 | Buy in zones, ignore short-term chart. |
| **Momentum Leader** | momentum >=70, value < 55 | Trade only; not a hold. Trail tight. |
| **Quality Watch** | value 60–70, momentum any | Wait for price or proof. |
| **Cyclical / Turnaround** | value Cyclical/Turnaround | Smaller size, cycle-aware. |
| **Avoid** | value Avoid OR (momentum<50 AND value<50) | Skip. |

Scatter viz: `x = Composite Value`, `y = Composite Momentum`,
`size = Expected CAGR`, `color = Matrix Class`, quadrant guides at 65/65,
Crossover Buy points starred.

---

## 40–43.  (Holdings overlay, Risk mgmt, Market regime, Exports)
Unchanged from v1 Sections 21–24, with these v2 additions:

- **Holdings overlay** now also pulls `Value Class`, `Expected CAGR %`,
  `Quality Score`, and `Crossover Buy` so a held stock is judged on BOTH lenses.
  New holding-action rows:
  - if held AND `Value Class == Compounder` AND not overextended →
    **"Core compounder — hold / add in zones."**
  - if held AND `Value Class == Avoid` AND `pnl<0` AND below 200 DMA →
    **"Fundamental + technical breakdown — exit review (Section 6 exit rules)."**
- **Market regime** (Section 23) gates momentum entries only; the value scan
  uses regime merely to *favour* staggered entry in Weak markets (better prices),
  not to reject.

---

## 44. Limitations (updated)
- Value scan quality is only as good as the **Screener.in CSV freshness** —
  refresh quarterly after results season.
- Expected CAGR is a transparent heuristic, **not** a DCF; treat the band, not
  the decimal.
- Fundamentals CSV must be maintained by the user; symbols that rename need the
  `isin` join (Section 3).
- Sector P/E medians need a maintained `data/sector_pe.csv` (else falls back to
  the 25/18 caps in Section 35).
- Everything else from v1 Section 25 still applies (Yahoo data quirks, no
  result-date filter, educational not advice).

## 45. Future enhancements
v1 Section 26 list PLUS:
- **DCF-lite** module to cross-check Expected CAGR.
- **Quarterly results delta** feed (YoY/ QoQ surprise) to upgrade Turnaround →
  Quality-Growth automatically.
- **Auto-fetch Screener** (behind a sidebar opt-in, batched, respecting speed
  budget rule 9).
- Backtest BOTH scans separately: momentum on 15–30d forward returns, value on
  1–3yr forward returns.

## 46. Development rules
All v1 Section 27 rules hold. Additions:
- The two scans MUST keep separate scoring modules: `scanner.py` (momentum) and
  `value.py` (value/quality-growth). `value.py` must NOT import momentum
  classification, and vice-versa, except via the shared `compute_metrics` core
  and the read-only `Crossover Buy` join.
- New constants (`SPRING_*`, `VCP_*`, `OBV_*`, fundamentals thresholds) must be
  documented here in the same commit.
- `run_scan` return shape: ADD keys `spring`, `accumulation`, `value_quality`,
  `crossover`, `fundamentals`; do not remove existing keys.


---

## v2 IMPLEMENTATION STATUS (live)

- **Phase 1 DONE** (commit): Section 4 new indicators (10 DMA, OBV/OBV-slope, A/D line+slope, Volume Pocket, Pocket Pivot, NR7, Inside Bar, Base Depth/Length, 52W High Age, Avg Turnover, VCP Contractions, Tightness Ratio); Section 4A liquidity floor (Illiquid flag); Section 10A Spring engine (Spring Score + Spring Ready + trigger/alert); 10B Pocket Pivot bonus; 10C Accumulation layer (Accumulation Score + A/D State); 11A VCP count; 13 fresh-high bonus; 15 Momentum Readiness sort. New `run_scan` keys: `spring`, `accumulation`. New tab **Spring / Pre-Breakout**. Export sheet `Spring_PreBreakout` + `spring_prebreakout.csv`.
- **Phase 2 PENDING**: Section 30-32 fundamentals layer (Screener CSV ingest + sub-scores + quality gate).
- **Phase 3 PENDING**: Section 33-36 valuation/CAGR/composite-value/value-class + 11B rename of old Value->Technical Recovery.
- **Phase 4 PENDING**: Section 38-39 Crossover Buy + new matrix + holdings dual-lens.
