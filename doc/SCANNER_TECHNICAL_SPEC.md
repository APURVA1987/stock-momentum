# SCANNER_TECHNICAL_SPEC.md

> Technical reference for the NSE Momentum Breakout Dashboard's scanning
> engines. This file documents every indicator, score, classification rule
> and threshold actually used in the code (paths and constants are accurate
> to the current `scanner.py` and `value.py`). Use this when changing any
> scoring or classification logic.
>
> Companion file: [`WEBSITE_HANDOFF.md`](WEBSITE_HANDOFF.md) - describes UI,
> tabs, exports and dev rules.

---

## 1. Objective

The engines together identify, on a single scan of the universe:

| Engine | Output |
|--------|--------|
| Trend / momentum | Strong Breakout / Actionable, Wait for Confirmation, Early Watchlist, Rejected |
| Composite + momentum class | Elite Momentum, Actionable Breakout, Wait for Confirmation, Early Watchlist, Ignore |
| Relative Strength | RS Score (0-100), RS Rank, RS Leader flag |
| Sector Rotation | Sector Strength Score (0-100), Sector Rank, Sector Status (Leading/Improving/Neutral/Weak) |
| Coiled / Tight setup | Coiled Score + Coiled Ready flag |
| Fresh Momentum | Fresh Momentum Score + Fresh Momentum flag |
| Do Not Chase | Overextended flag + No Chase Reason + Wait Condition |
| Breakout Quality | 0-100 + status (Excellent / Good / Weak / Failed) |
| Pullback Quality | Pullback Type + 0-100 + remark |
| Technical Value | Value Score + Value Classification + Value Entry Style + trigger / invalidation / target zone |
| Momentum + Value | Matrix Class (Best Crossover / Momentum Leader / Value Recovery / Mixed / Avoid) |
| Holdings overlay | holding_action label + holding_remark |

Trading horizon: **15-30 day swing**. The watchlist tiers (Wait / Coiled / Base
Forming) are useful for longer pre-entry observation.

---

## 2. Data Source

- **Provider**: Yahoo Finance via `yfinance.download(...)`.
- **Ticker convention**: NSE symbols suffixed with `.NS` (e.g. `RELIANCE.NS`).
  Bombay Stock Exchange `.BO` is not used.
- **Benchmark**: Nifty 50 via `^NSEI` (constant `NIFTY_SYMBOL` in
  `scanner.py`).
- **Granularity**: daily OHLCV (`interval="1d"`).
- **Default period**: 5 years; sidebar allows 2 or 3 years.
- **Adjustments**: `auto_adjust=True` so splits/bonuses are baked in
  (corporate-action artefacts in the MA series are minimised).
- **Download mode**: batched (`download_batch`) - all symbols in one threaded
  call, drastically fewer rate-limit hits than per-symbol fetches.
- **Local mode** (`local_mode=True`, sidebar toggle): reads
  `data/price_cache_<period>.pkl`, fetches only stale/missing symbols from
  Yahoo, and optionally overlays the latest NSE bhavcopy day for the
  most-recent official close.
- **Intraday-bar stripping** (`eod_only=True`, default ON): when the scan
  runs during NSE market hours (Mon-Fri 09:15-15:30 IST) and the most-recent
  bar's volume is < 85% of the 20-day average, that partial bar is dropped.
  Without this, Volume Ratio collapses (~0.2x at 11 AM) and Strong Breakout
  rejects almost every stock.
- **Quality caveats**: occasional missing days, occasional split mis-adjust,
  occasional symbol changes (e.g. ZOMATO -> ETERNAL, TATAMOTORS demerger ->
  TMCV + TMPV, PEL -> PIRAMALFIN). NSE `DUMMY*` placeholder symbols (e.g.
  Vedanta demerger stubs) are filtered out by the universe parser.

---

## 3. Stock Universe

### Default file: `universe.csv`

Current snapshot: **751 stocks across 43 sectors** (97 Large Cap, 368 Mid Cap,
286 Small Cap).

Required columns (case-insensitive on load):

| Column | Example | Notes |
|--------|---------|-------|
| `symbol` | `RELIANCE` | NSE symbol WITHOUT `.NS` (the engine appends it) |
| `company` | `Reliance Industries` | Free-text |
| `sector` | `Energy` | Free-text; used by Sector Rotation |
| `market_cap_category` | `Large Cap` | Must be `Large Cap`, `Mid Cap`, or `Small Cap` |

`source_type` is added at runtime (`Universe`, `Holding`, or `Universe + Holding`).

### NSE constituent uploads

Sidebar lets the user drop in `ind_nifty100list.csv`,
`ind_niftymidcap150list.csv`, `ind_niftysmallcap250list.csv` from
niftyindices.com. They are parsed (`parse_nse_constituent`) into the
4-column schema, filtered to `Series == 'EQ'`, and `DUMMY*` symbols are
removed. Each upload is persisted under `data/nse_<cap>.csv` and re-used
automatically. When ANY NSE file is present, it **overrides** `universe.csv`.

### Holdings inclusion

`holdings.combine_universe_holdings(uni, holdings)` always appends portfolio
symbols not in the chosen universe, tagged with `market_cap_category = Holding`.
This is what guarantees every owned stock is analysed.

Duplicates are removed by `df.drop_duplicates(subset="symbol", keep="first")`.

---

## 4. Core Indicators

All math lives in `indicators.py` and is computed by `scanner.compute_metrics`
per stock. No external technical-analysis library is required.

| Metric | Formula | File |
|--------|---------|------|
| `CMP` | `close.iloc[-1]` | `scanner.py` |
| `20 DMA` / `50 DMA` / `100 DMA` / `200 DMA` | `close.rolling(N).mean()` | `indicators.sma` |
| `200 DMA Slope %` | linear fit of last 30 DMA values, expressed as % of mean | `indicators.slope_pct` |
| `50 DMA Slope %` | same, on the 50 DMA | `indicators.slope_pct` |
| `52W High` / `Prev 52W High` | `close.tail(252).max()` / `.iloc[:-1].max()` | inline |
| `Distance from 52W High %` | `(cmp / 52WH - 1) * 100` | inline |
| `Distance from 20 / 50 / 100 / 200 DMA %` | `(cmp / ma_k - 1) * 100` | inline |
| `Gap Up %` | `(open_last / prev_close - 1) * 100` | inline |
| `RSI 14` | Wilder smoothing via EWM (alpha = 1/14) | `indicators.rsi` |
| `RSI Change 2W` | `rsi.iloc[-1] - rsi.iloc[-11]` | inline |
| `ADX 14` | Wilder +DI / -DI / DX / ADX (manual, no library) | `indicators.adx` |
| `ATR 14` / `ATR 50` | EWM smoothing of True Range | `indicators.atr` |
| `ATR Contraction` | `ATR14 / ATR50` (< 0.85 = tight) | inline |
| `Close Position` | `(close - low) / (high - low)` of last candle | `indicators.close_position` |
| `Avg Vol 20` | `volume.tail(20).mean()` | inline |
| `Volume Ratio` | `latest_vol / avg_vol_20` | inline |
| `Volume Dryup 10D` | `volume.tail(10).mean() / volume.tail(50).mean()` | inline |
| `Higher Lows 10D` | count of `low[i] > low[i-1]` over last 10 sessions | inline |
| `Lower Highs 10D` | count of `high[i] < high[i-1]` over last 10 sessions | inline |
| `Range 5D / 10D / 20D / 30D / 60D / 90D %` | `(window_high - window_low) / cmp * 100` | inline |
| `Return 5D / 20D / 60D / 120D / 252D %` | `(close[-1] / close[-1-N] - 1) * 100` | `indicators.pct_change_over` |
| `Nifty 5/20/60/120/252-day Return %` | same on `^NSEI` | `get_nifty_context` |
| `RS 5D / 20D / 60D / 120D / 252D %` | stock return - Nifty return per window | inline |
| `Relative Strength %` | RS 20D (kept for backward compat) | inline |
| `RSI / Volume / Composite scores` | see Sections 5-15 | `scanner.py` |
| `MACD bullish flag` | `EMA12 > EMA9_signal AND macd_line > 0`, manual EMA | inline |
| `Up/Down Vol Ratio` | avg up-day volume / avg down-day volume over last 30 days | inline |
| `Max Drawdown 6M / 1Y %` | min of `close / rolling_max - 1` over 126 / 252 sessions | inline |
| `Fresh 3M Low` | `close.iloc[-1] <= close.tail(63).iloc[:-1].min() * 1.005` | inline |
| `Days Below 200 DMA` | count over `retest_window` (sidebar, default 60) | inline |
| `Retested 200 DMA` | any low within `[ -2%, retest_tol% ]` band of 200 DMA in window | inline |
| `Retest Date` | timestamp of nearest retest | inline |
| `_breakout_sustain` | last 5 closes, count >= prev 52W high * 0.98 ; sustain = count >= 3 | inline |
| `Pullback Type` | nearest MA whose `(low_60/ma - 1)` lies in `[-0.03, +0.05]`; else "Broken 200 DMA Recovery" or "No Valid Pullback" | inline |
| `Risk Reward` | `(target1 - cmp) / (cmp - stop_used)`, where `stop_used = max(cmp - 1.5*ATR14, swing_low)` and `target1 = cmp * 1.08` | inline |

Tunable thresholds (top of `scanner.py`):

```python
RSI_STRONG          = 60.0
ADX_TREND           = 20.0
ADX_STRONG          = 25.0
CLOSE_POS_STRONG    = 0.75
MAX_EXT_FROM_20DMA  = 10.0
MAX_EXT_FROM_200DMA = 40.0
MIN_RR              = 1.5
SCORE_STRONG        = 80
SCORE_WAIT          = 65
SCORE_WATCH_FLOOR   = 55     # also the Rejected floor unless sidebar overrides
```

---

## 5. Momentum Scanner Base Logic

`scanner.classify(m, score, min_rsi, min_vol_ratio, regime, min_score)`
applies the hard gates in this order. Failing any gate returns `Rejected`
with a reason; the order is the order of reason precedence.

### Hard rejections (apply BEFORE looking at score)
| Order | Condition | Reason |
|-------|-----------|--------|
| 1 | `cmp <= 200 DMA` | "Below 200 DMA" |
| 2 | `200 DMA Slope % <= 0` | "200 DMA falling" |
| 3 | `not _retested` | "No recent 200 DMA retest" |
| 4 | `Relative Strength % < 0` | "Relative strength negative" |
| 5 | `Volume Ratio < 1.0` | "Liquidity/volume too weak" |
| 6 | `score < min_score` (sidebar) | `Score N below minimum M` |

### Strong Breakout / Actionable gates (after passing rejections)
ALL of:
- `cmp > 20 DMA`, `cmp > 50 DMA`, `cmp > 200 DMA`
- `50 DMA > 200 DMA`
- `200 DMA Slope % > 0`
- `RSI 14 >= max(RSI_STRONG=60, min_rsi)`
- `Relative Strength % > 0`
- `cmp > prev_52w_high` OR `Distance from 52W High % >= -2`
- `Volume Ratio >= min_vol_ratio` (sidebar, default 1.5)
- `Days Below 200 DMA <= 5`
- `score >= SCORE_STRONG (80)`

### Tier fall-through
- `score >= SCORE_WAIT (65)` and not Strong -> `Wait for Confirmation`
- `score >= SCORE_WATCH_FLOOR (55)` -> `Early Watchlist`
- Else -> `Rejected`

---

## 6. Composite Scoring (out of 100)

`scanner.score_components(m, sector_is_top, regime_supportive)` returns the
five sub-scores. The composite blend is then computed in `_build_row`.

### Bucket A - Trend Quality (max 25)
| Points | Condition |
|--------|-----------|
| 7 | `cmp > 200 DMA` |
| 6 | `50 DMA > 200 DMA` |
| 6 | `200 DMA Slope % > 0` |
| 6 | `cmp > 20 DMA AND cmp > 50 DMA` |

### Bucket B - Pullback Quality (max 20)
| Points | Condition |
|--------|-----------|
| 8 | `_retested == True` |
| 5 | `Days Below 200 DMA <= 5` |
| 4 | `_volume_dryup == True` (pullback days had vol < 20-day avg) |
| 3 | `cmp > 20 DMA AND cmp > 50 DMA AND Days Below 200 DMA <= 5` (clean recovery) |

### Bucket C - Momentum Quality (max 20)
| Points | Condition |
|--------|-----------|
| 5 | `RSI 14 > RSI_STRONG (60)` |
| 5 | `ADX 14 > ADX_TREND (20)` |
| 5 | `Relative Strength % > 0` |
| 5 | `20-Day Return % > 0` AND beats `Nifty 20-Day Return %` |

### Bucket D - Breakout Quality (max 20)
| Points | Condition |
|--------|-----------|
| 5 | `Distance from 52W High % >= -5` |
| 6 | `cmp > Prev 52W High` |
| 5 | `Volume Ratio > 1.5` |
| 4 | `Close Position > CLOSE_POS_STRONG (0.75)` |

### Bucket E - Risk Quality (max 15)
| Points | Condition |
|--------|-----------|
| 4 | `Distance from 20 DMA % <= MAX_EXT_FROM_20DMA (10)` |
| 3 | `Distance from 200 DMA % <= MAX_EXT_FROM_200DMA (40)` |
| 4 | `Risk Reward >= MIN_RR (1.5)` |
| 4 | regime supportive (regime != "Weak") |

### Sector top-3 bonus
+2 if the stock's sector is in the top-3 by avg 20-day return (informational
only, capped so total <= 100).

### Risk-level label
`scanner.risk_level(score, days_below_200)`:
- `Low Risk` if `score >= 80 AND days_below_200 <= 3`
- `High Risk` if `score < 65 OR days_below_200 > 10`
- `Medium Risk` otherwise

### Composite Momentum Score (out of 100)
Computed in `_build_row` with normalised sub-scores:

```
composite = 0.25 * (TrendScore  * 4.0)        # 0-25  -> 0-100
          + 0.25 * RS_Score                   # 0-100
          + 0.20 * BreakoutQualityScore       # 0-100 (Section 13)
          + 0.15 * SectorStrengthScore        # 0-100
          + 0.15 * (RiskScore * 100 / 15)     # 0-15  -> 0-100
```

### Momentum Class
| Range | Label |
|-------|-------|
| `>= 85` | **Elite Momentum** |
| `75 - 85` | **Actionable Breakout** |
| `65 - 75` | **Wait for Confirmation** |
| `55 - 65` | **Early Watchlist** |
| `< 55` | **Ignore** |

The Momentum Class lives alongside the older `Classification` column - both
are exposed (the table/UI use Momentum Class as the headline; existing
exports continue to use `Classification` for backward compatibility).

---

## 7. Wait For Confirmation Logic

Stocks tagged `Wait for Confirmation` carry these extra columns:

| Column | Source |
|--------|--------|
| `Confirmation Needed` | `scanner.confirmation_needed(m, min_vol_ratio)` |
| `Trigger Price` | `scanner.trigger_levels(m, risk)` (see below) |
| `Suggested Alert Price` | `Trigger Price * 0.99` |
| `Invalidation Level` | swing low / 50 DMA / 200 DMA depending on Risk Level |
| `Distance to Trigger %` | `(Trigger / CMP - 1) * 100` (computed in app.py table) |

### Trigger Price selection
```python
if   cmp < ma50:                     trigger = ma50
elif cmp < high_52w:                 trigger = high_52w
else:                                trigger = latest_high
```

### Invalidation by risk
```
Low Risk    -> swing_low (60-day low)
Medium Risk -> 50 DMA
High Risk   -> 200 DMA
```

### Confirmation reasons (joined, top 2)
- "close above 52W high (trigger) with volume > 1.5x" - if not breaking out
- "RSI to cross 60" - if RSI 14 < 60
- "volume expansion above 1.5x average" - if Volume Ratio < min_vol_ratio
- "price to sustain above 50 DMA" - if `cmp < 50 DMA`
- "2 consecutive closes above breakout level" - if not `_breakout_sustain`
- "relative strength vs Nifty to turn positive" - if `RS 20D % <= 0`

If none apply: "Avoid fresh entry until stock closes above trigger price".

---

## 8. Relative Strength Engine

### Per-window returns
Computed via `indicators.pct_change_over` for both the stock and `^NSEI`:
5, 20, 60, 120, 252 trading days.

### RS per window
```
RS_W = stock_return_W - nifty_return_W   (for W in 5, 20, 60, 120, 252)
```

### RS Score (0-100) - percentile rank within the scanned universe
For each window, NaN values are filled with the column minimum (so missing
history ranks at the bottom), then `pandas.Series.rank(pct=True) * 100`:

```
rs_score = round( 0.30 * pct_rank(RS_20)
                + 0.30 * pct_rank(RS_60)
                + 0.25 * pct_rank(RS_120)
                + 0.15 * pct_rank(RS_252) )
```

`RS Rank` = descending rank of `RS Score` (1 = best).

### RS Leader flag
ALL of:
- `RS Score >= 80`
- `RS 20D % > 0` AND `RS 60D % > 0`
- `cmp > 50 DMA` AND `cmp > 200 DMA`

---

## 9. Sector Rotation Engine

### Per-sector aggregates (built on all stocks with valid metrics)
- avg Return 20D %, avg Return 60D %
- avg RS Score
- % above 50 DMA, % above 200 DMA
- count of Strong Breakouts (classification)
- count of Wait for Confirmation
- count of RS Leaders
- avg Volume Ratio

### Sector Strength Score (0-100) - percentile rank across sectors
```
sss = 25 * rank(avg_ret_20)
    + 25 * rank(avg_ret_60)
    + 25 * rank(avg_rs_score)
    + 15 * rank(pct_above_50)
    + 10 * rank(n_strong + n_wait)
```
(Ranks are in `[0, 1]` so weights sum to 100.)

`Sector Rank` = descending rank of Sector Strength Score (1 = best).

### Sector Status
```
>= 75  -> Leading
>= 60  -> Improving
>= 40  -> Neutral
else   -> Weak
```

---

## 10. Coiled / Ready Engine

Goal: identify stocks that are tightening up while staying near the 52W high -
the "spring-loaded" setups.

### Inputs
- `Range 10D %`, `Range 60D %` (the tightness ratio is `Range 10D / Range 60D`)
- `ATR Contraction = ATR 14 / ATR 50`
- `Volume Dryup 10D = avg vol 10 / avg vol 50`
- `Higher Lows 10D`
- `Distance from 52W High %`
- `RS Score`

### Coiled Score (out of 100)
| Points (max) | Condition |
|--------------|-----------|
| 25 (tightness) | ratio <= 0.4 -> 25 ; <= 0.6 -> 18 ; <= 0.8 -> 10 |
| 20 (ATR contraction) | < 0.70 -> 20 ; < 0.85 -> 12 ; < 1.0 -> 5 |
| 20 (volume dry-up) | < 0.60 -> 20 ; < 0.80 -> 12 ; < 1.0 -> 5 |
| 20 (RS score) | `RS Score / 100 * 20` |
| 15 (near 52W high) | `dist52 >= -3` -> 15 ; `>= -7` -> 10 ; `>= -10` -> 5 |

### Coiled Ready (boolean flag) - ALL of:
- `cmp > 50 DMA AND cmp > 200 DMA`
- `Distance from 52W High % >= -10`
- `ATR Contraction < 0.85`
- `Volume Dryup 10D < 0.80`
- `RS Score >= 65`
- `Distance from 20 DMA % <= 10` (not overextended)
- `Range 10D / Range 60D <= 0.7`

**Decision label**: "Preparing. Do not enter until breakout with volume."

---

## 11. Fresh Momentum Engine

Goal: stocks that are **just starting** a new up-leg, even if they never did
the classic 200-DMA retest.

### Inputs
- MA alignment, MA-rising flags, Volume Ratio, RSI 14, ADX 14
- `_at_20d_high`, `_near_20d_high`
- `RS 20D %`, `RS Score`

### Fresh Momentum Score (out of 100)
| Points (max) | Condition |
|--------------|-----------|
| 25 | `cmp > 20 DMA > 50 DMA > 200 DMA` -> 25 ; OR `cmp > 50 > 200` -> 12 |
| 20 | `Volume Ratio >= 1.5` -> 20 ; `>= 1.2` -> 10 |
| 15 | `55 <= RSI <= 72` -> 15 ; just outside (50-55 or 72-78) -> 7 |
| 15 | `ADX > 25` -> 15 ; `> 20` -> 10 ; `> 15` -> 5 |
| 15 | `cmp >= 20D high * 0.999` -> 15 ; `_near_20d_high` -> 8 |
| 10 | `RS Score / 100 * 10` |

### Fresh Momentum (boolean flag) - ALL of:
- `cmp > 20 DMA > 50 DMA > 200 DMA` (`_ma_aligned`)
- `_ma20_rising AND _ma50_rising`
- `Volume Ratio >= 1.5`
- `55 <= RSI <= 72`
- `ADX > 20 OR _ma20_rising`
- `_near_20d_high`
- `RS 20D % > 0`
- `RS Score >= 70`

**Decision label**: "Fresh momentum. Prefer entry on small pullback or breakout sustain."

---

## 12. Do Not Chase / Overextension Engine

ANY of the following flips `Overextended = "Yes"`:
- `Distance from 20 DMA % > 10`
- `Distance from 50 DMA % > 20`
- `Distance from 200 DMA % > 40`
- `RSI 14 > 75`
- `Gap Up % > 5`
- `Risk Reward < 1.2`

`No Chase Reason` joins the active conditions in plain English.

### Wait Condition (suggested action)
- "Wait for pullback to 20 DMA" (if `dist_20 > 10`)
- "Wait for consolidation / breakout retest" (if overextended from 50 or 200)
- "Wait for RSI to cool" (if `RSI > 75`)
- "Wait for gap fill / consolidation" (if `gap_up > 5`)
- "Avoid until risk-reward improves" (if `RR < 1.2`)

**Decision label**: "Good stock may be overextended. Avoid fresh entry now."

---

## 13. Breakout Quality Score

Used as the 20% slice of the Composite Momentum Score and as a column in
Strong / Wait tables.

| Points | Condition |
|--------|-----------|
| 25 | `cmp > Prev 52W High` |
| 20 | `Volume Ratio >= 1.5` |
| 20 | `Close Position >= CLOSE_POS_STRONG (0.75)` |
| 20 | `_breakout_sustain` (3 of last 5 closes >= prev 52W high * 0.98) |
| 15 | `Distance from 20 DMA % <= MAX_EXT_FROM_20DMA (10)` |

### Status
| Score | Label |
|-------|-------|
| `>= 80` | Excellent |
| `>= 60` | Good |
| `>= 40` | Weak |
| `else` | Failed |

---

## 14. Pullback Quality Score

`Pullback Type` is chosen by which MA the 60-day low touched - lowest absolute
`gap = (low_60 / ma - 1)` within `[-0.03, +0.05]`:

- `20 DMA Bounce`
- `50 DMA Bounce`
- `100 DMA Bounce`
- `200 DMA Retest`
- `Broken 200 DMA Recovery` (was below 200 but now above)
- `No Valid Pullback`

### Score (out of 100)
| Points (max) | Condition |
|--------------|-----------|
| 25 | respected a moving average (20/50/100/200) -> 25 ; "Broken 200 DMA Recovery" -> 12 |
| 25 | fall volume < recovery volume -> 25 ; within 10% -> 12 |
| 20 | recovery speed <= 15 days -> 20 ; <= 30 -> 12 ; <= 45 -> 6 |
| 15 | drawdown depth <= 15% -> 15 ; <= 25% -> 8 |
| 15 | reclaimed 20 AND 50 DMA -> 15 ; reclaimed 50 -> 8 |

`Pullback Remark` is a short auto-built sentence summarising type, volume
behaviour, recovery speed, and depth.

---

## 15. Composite Momentum Score (recap from Section 6)

See Section 6 for the full formula and class bands. Recap:

```
Composite = 25% Trend + 25% RS + 20% Breakout Quality
          + 15% Sector Strength + 15% Risk Quality
```

Classification:
- `>=85` Elite Momentum  ·  `75-85` Actionable Breakout  ·
  `65-75` Wait for Confirmation  ·  `55-65` Early Watchlist  ·
  `<55` Ignore

---

## 16. Technical Value Scanner

`value.score_value(m, sector_status)` is called per stock from `_build_row`.
Pure-technical (no fundamentals).

### Inputs (additional to indicator pack)
- `Distance from 52W High %` -> `drawdown = abs(...)`
- `Range 10D %`, `Range 60D %` -> tightness ratio
- `ATR Contraction`, `Volume Dryup 10D`, `Higher Lows 10D`
- `RSI 14`, `RSI Change 2W`, `_macd_bullish`, `Up/Down Vol Ratio`
- `RS 20D %`, `RS 60D %`
- `_fresh_3m_low`, `Max Drawdown 6M %`, `Max Drawdown 1Y %`
- `200 DMA Slope %`, `50 DMA Slope %`, distance from 20/50/100/200 DMA
- `Risk Reward`, `_swing_low`
- sector_status (from sector rotation)

---

## 17. Value Score (out of 100)

### A. Correction Opportunity (max 20)
| Points | Condition |
|--------|-----------|
| 10 | `15 <= drawdown <= 40` |
| 5 | `drawdown <= 50` |
| 5 | `10 <= drawdown <= 45` |

### B. Stabilisation / Base (max 25)
| Points | Condition |
|--------|-----------|
| 8 / 5 / 2 | tightness ratio (`Range 10D / 60D`) <= 0.5 / 0.7 / 0.85 |
| 6 / 3 | `ATR Contraction < 0.85 / 1.0` |
| 5 / 2 | `Volume Dryup 10D < 0.8 / 1.0` |
| 6 / 3 | `Higher Lows 10D >= 6 / 4` |

### C. Reversal Confirmation (max 25)
| Points | Condition |
|--------|-----------|
| 5 | `cmp > 20 DMA` |
| 7 / 3 | `cmp > 50 DMA` / `cmp >= 50 DMA * 0.97` |
| 5 / 3 | `RSI >= 50` / `RSI Change 2W >= 10` |
| 4 | `_macd_bullish` |
| 4 / 2 | `Up/Down Vol Ratio >= 1.3 / 1.0` |

### D. Relative Strength Improvement (max 15)
| Points | Condition |
|--------|-----------|
| 5 | `RS 20D > 0` |
| 5 | `RS 60D > 0` |
| 5 | `sector_status != "Weak"` |

### E. Risk Control (max 15)
| Points | Condition |
|--------|-----------|
| 5 | NOT (`200 DMA Slope < 0` AND `cmp < 200 DMA`) |
| 5 | NOT `_fresh_3m_low` |
| 5 | `Risk Reward >= 1.5` |

Total is capped at 100. Sub-scores are exposed as `Value Correction Score`,
`Value Stabilisation Score`, `Value Reversal Score`, `Value RS Score`,
`Value Risk Score` (for the Value Deep Dive breakdown chart).

Tunable thresholds (top of `value.py`):
```python
CORR_BAND_MIN          = 15.0
CORR_BAND_MAX          = 40.0
CORR_BASE_MAX          = 45.0
DEEP_VALUE_MIN         = 35.0
RSI_REVERSAL_MIN       = 50.0
SCORE_REVERSAL_READY   = 75
SCORE_BASE_FORMING     = 60
```

---

## 18. Value Classifications

Evaluation order (first match wins, except Trap which has priority).

### Trap precedence (overrides everything else)
`Value Trap Avoid` if ANY of:
- `200 DMA Slope < 0` AND `cmp < 200 DMA`
- `_fresh_3m_low`
- `RS 60D % < -5`
- `RSI < 40`
- `sector_status == "Weak"` AND `cmp < 50 DMA`

### Value Reversal Ready - ALL of:
- `Value Score >= SCORE_REVERSAL_READY (75)`
- `CORR_BAND_MIN (15) <= drawdown <= CORR_BAND_MAX (40)`
- `cmp > 20 DMA`
- `cmp > 50 DMA OR cmp >= 50 DMA * 0.98`
- `RSI > RSI_REVERSAL_MIN (50)`
- `RS 20D > 0 OR RS 60D > 0`
- NOT `_fresh_3m_low`

**Decision**: "Recovery confirmed. Consider only after chart/news review."

### Value Base Forming - ALL of:
- `SCORE_BASE_FORMING (60) <= Value Score < SCORE_REVERSAL_READY (75)`
- `15 <= drawdown <= CORR_BASE_MAX (45)`
- tightness ratio <= 0.7
- `Volume Dryup 10D < 0.85`
- `Higher Lows 10D >= 3`

**Decision**: "Base forming. Set alert above base resistance."

### Deep Value High Risk - ALL of:
- `drawdown > DEEP_VALUE_MIN (35)`
- `sector_status != "Weak"`
- ANY of: `cmp > 200 DMA` OR `ATR Contraction < 0.85` OR `Higher Lows 10D >= 3`

**Decision**: "High-risk recovery candidate. Small watchlist only."

### Fallback
`Value Base Forming` if score >= 50 ; else `Value Trap Avoid`.

---

## 19. Value Entry Logic

### Entry style choice (per stock)
- If `cls == Value Reversal Ready`:
  - `cmp < 50 DMA` -> **"Reclaiming 50 DMA"** - enter only after 2 closes
    above the 50 DMA.
  - `cmp > 20 DMA AND RSI >= 50` -> **"Reversal from oversold"** - enter only
    after RSI > 50 and price > 20 DMA.
  - else -> **"Base breakout"** - enter only above base resistance with
    volume > 1.5x.
- If `cls == Value Base Forming` -> **"Base breakout"**.
- If `cls == Deep Value High Risk` -> **"200 DMA support"** - enter only after
  a bullish reversal candle near the 200 DMA; stop below swing low.
- If `cls == Value Trap Avoid` -> **"Deep value (wait)"** - no entry until
  higher lows form AND price reclaims the 50 DMA.

### Trigger / invalidation / target
```
trigger = (50 DMA      if entry == "Reclaiming 50 DMA"
        else 200 DMA * 1.02 if entry == "200 DMA support"
        else cmp * 1.05     if entry == "Deep value (wait)"
        else base resistance proxy from 52W high and current drawdown)
invalidation = swing_low (if > 0) else cmp * 0.92
target_zone  = f"{cmp*1.10} - {cmp*1.20}"
```

---

## 20. Momentum + Value Matrix

`value.matrix_class(composite, value)` computes one label per stock:

| Label | Rule | Meaning |
|-------|------|---------|
| **Best Crossover** | composite >= 65 AND value >= 65 | "Corrected stock now regaining momentum. Highest interest." |
| **Momentum Leader** | composite >= 70 AND value < 60 | "Good for a momentum trade; not necessarily cheap." |
| **Value Recovery** | value >= 70 AND composite < 60 | "Recovery setup. Wait for confirmation." |
| **Avoid** | composite < 50 AND value < 50 | "Weak on both momentum and value. Avoid." |
| **Mixed** | anything else | (HIDDEN from the dashboard - shown only in exports) |

Visualisation: `px.scatter(x=Value Score, y=Composite Score, size=Volume Ratio, color=Matrix Class)`
with quadrant guides at 65/65 and the "Mixed" rows filtered out.

---

## 21. Holdings Overlay Technical Logic

### Zerodha column aliases (case- and dot-insensitive, partial-match fallback)
| Internal | Accepted broker headers |
|----------|-------------------------|
| `symbol` | Instrument, Symbol, Tradingsymbol, Scrip |
| `quantity` | Qty., Qty, Quantity, Qty available |
| `avg_cost` | Avg. cost, Avg cost, Avg. price, Average cost, Average price |
| `ltp` | LTP, Last price, CMP, Current price |
| `invested` | Invested, Invested amount, Cost value, Cost |
| `current_value` | Cur. val, Cur val, Current value, Current val, Market value, Mkt value |
| `pnl` | P&L, PnL, P&L (R), Profit & Loss, P & L |
| `net_change_pct` | Net chg., Net chg, Net chg.%, Net change %, Net %, P&L % |
| `day_change_pct` | Day chg., Day chg, Day chg.%, Day change %, Day % |

Indian comma thousands and trailing `%` are stripped before numeric coercion.
GRAND TOTAL rows are dropped.

### Derived calculations
- `invested = quantity * avg_cost` (if missing)
- `current_value = quantity * ltp` (if missing)
- `pnl = current_value - invested` **(recomputed - more reliable than broker column)**
- `pnl_pct = pnl / invested * 100`
- `portfolio_weight_pct = current_value / sum(current_value) * 100`
- `avg_vs_cmp_pct = (CMP - avg_cost) / avg_cost * 100`
- `avg_vs_20dma_pct`, `avg_vs_50dma_pct`, `avg_vs_200dma_pct` similarly
- `cmp_vs_200dma_pct = (CMP - 200 DMA) / 200 DMA * 100`

CMP is taken from the scanner output (`all_stocks['CMP']`) when present; the
broker's `ltp` is the fallback.

### Holding Action labels (`holdings._action`)
Evaluated in this order; first match wins:

| Order | Condition | Label | Remark |
|-------|-----------|-------|--------|
| 1 | scanner data missing for symbol | **No Scanner Data** | "Scanner data unavailable for this symbol - see Failed Tickers." |
| 2 | `cmp < 200 DMA` AND 200 DMA falling AND (RS < 0 OR Composite < 55) | **Exit Review** | "Exit / reduce review. Avoid averaging down until structure improves." |
| 3 | Classification == "Rejected" OR Composite < 55 OR RS < 0 | **Review / Reduce** | "Review for reduction. Weak technical structure." |
| 4 | `Overextended == "Yes" AND pnl > 0` | **Do Not Add / Trail Only** | "Continue holding if already owned. Do NOT add fresh. Trail SL." |
| 5 | strong class AND `Composite >= 75` AND above 200 DMA AND Sector Status == "Leading" AND `RR >= 1.5` AND not overextended | **Add on Pullback** | "Can consider adding only on controlled pullback or breakout retest with volume." |
| 6 | strong class AND `Composite >= 75` AND above 200 DMA | **Hold / Trail** | "Hold existing position. Trail stop-loss. Add only on pullback or breakout sustain." |
| 7 | Wait for Confirmation OR Coiled Ready OR Fresh Momentum | **Hold, Set Alert** | "Hold. Set alert near trigger price. Do not add until confirmation." |
| 8 | Early Watchlist | **Watch Only** | "Watch only. Wait for reclaim of 50 DMA or base breakout." |
| 9 | fallback | **Hold, Set Alert** | (same as row 7) |

("strong class" = Classification in `Strong Breakout / Actionable` OR Momentum
Class in `Elite Momentum / Actionable Breakout`.)

---

## 22. Risk Management Logic

- **Stop-loss suggestions** (Section 5 trade plan):
  - Conservative: below 20 DMA.
  - ATR-based: `cmp - 1.5 * ATR 14`.
  - Safer: below `swing_low` (60-day low).
- **Holding Stop**: `max(cmp - 1.5*ATR, swing_low)` (the higher of the two,
  i.e. the closer stop) is used in the Risk Reward calculation.
- **Targets**: T1 = +8%, T2 = +12%, with "trail if momentum continues".
- **Risk Reward** is computed as `(target1 - cmp) / (cmp - stop)`. Anything
  below 1.2 trips Overextension.
- **Do NOT average down** weak stocks (Holding Action enforces this: weak
  rows route to Review / Reduce or Exit Review, never to Add on Pullback).
- **Weak Market Regime** (see Section 23) demotes a score component AND
  appends "Trade with caution" to Final Remark for every row.

---

## 23. Market Regime Filter

`scanner.get_nifty_context(period)` returns the Nifty 50 ^NSEI context and a
regime label.

### Tests
- `Nifty Close > Nifty 50 DMA`
- `Nifty Close > Nifty 200 DMA`
- `Nifty 20-day return > 0`

### Regime
- `Bullish` if all 3 pass
- `Weak` if 0 or 1 passes
- `Neutral` otherwise

### Side effects
- In `score_components`, the Risk-bucket point for "regime supportive" is
  withheld when regime == "Weak".
- In `_build_row`, when regime == "Weak", the Final Remark gets
  "| Trade with caution (weak market)" appended.
- The dashboard shows a yellow warning banner on the main page when Weak.

---

## 24. Exports

See `WEBSITE_HANDOFF.md` -> Section 11 for the complete list of Excel sheets
and CSV files produced. The export builder is `app.export_outputs(result,
holdings_df)`. Empty buckets still get a (possibly empty) sheet; for empty
holding sheets, the holdings group is skipped entirely.

Sheet content equals the in-memory DataFrame for that bucket; no extra
formatting beyond default openpyxl. Column names are stable; any addition
should APPEND, not rename.

---

## 25. Limitations

- **Yahoo data**: occasional missing days, occasional split mis-adjust,
  occasional symbol changes (handled by curating the universe; the parser
  drops `DUMMY*` placeholders).
- **No fundamentals in scoring**: Screener.in fetch is on-demand only in the
  Stock Deep Dive tab (Section 9 of `WEBSITE_HANDOFF.md`). The Value scanner
  is technical-first.
- **No earnings/result-date filter**: a stock can qualify the day before a
  results announcement; manual check required.
- **No news/catalyst filter**.
- **No volume-delivery data**: only total volume from yfinance.
- **No backtesting module yet** (planned, Section 26).
- **NSE bhavcopy on Streamlit Cloud will fail** - cloud IPs are blocked by
  NSE. Use Local mode on a home PC for bhavcopy refresh.
- **Liquidity check is informal**: `Volume Ratio < 1.0` rejects the most
  illiquid names but does not enforce a turnover floor.
- **Educational screening, not financial advice.** Every shortlist needs
  chart, news, liquidity and risk confirmation before any trade.

---

## 26. Future Technical Enhancements

- **Backtesting module** with rolling windows + bucket-specific entry/exit
  rules + a P&L summary per bucket.
- **Fundamentals import** from a Screener.in CSV export per stock; gate
  Composite Score with a tiny fundamentals slice.
- **Earnings / result calendar filter** (e.g. block fresh entries -2..+2 days).
- **News catalyst filter** via a free news API or scrape.
- **Volume delivery** when a free source exposes it.
- **NSE bhavcopy daily refresh** as the *default* once a local cache exists
  (currently optional behind the `Local mode` toggle).
- **Alerts** - email / Telegram when a Wait-list stock crosses its trigger.
- **Position-sizing calculator** (risk-per-trade % -> position size at the
  proposed stop).
- **Portfolio risk dashboard** - VAR-style, concentration, beta.
- **True multi-user auth** via `streamlit-authenticator` once hosted on a
  paid plan.

---

## 27. Development Rules For Future AI Agents

These rules complement the UI rules in `WEBSITE_HANDOFF.md` Section 15.

1. **Do NOT change scoring constants silently.** If you touch any of
   `RSI_STRONG`, `ADX_TREND`, `MAX_EXT_*`, `MIN_RR`, `SCORE_*`,
   `CORR_*`, `DEEP_VALUE_MIN`, `RSI_REVERSAL_MIN`, `SCORE_REVERSAL_READY`,
   `SCORE_BASE_FORMING`: update this file in the same commit.
2. **Keep formulas transparent.** Inline magic numbers must have a comment;
   prefer a named constant at the top of the file.
3. **Backward-compatible columns.** New columns are fine; renaming existing
   columns breaks Excel users, the holdings overlay, and the Claude prompts.
4. **Do not delete a Classification value.** `Classification`
   (Strong/Wait/Watchlist/Rejected) and `Momentum Class` are both consumed
   by `holdings._action` and the export sheets.
5. **`_build_row` is the single source of truth** for what columns each
   classified stock carries. Add new columns there, not in app.py.
6. **`compute_metrics` must return all raw inputs that downstream engines
   need.** If you add a metric used by Value/Coiled/Fresh, put it in the
   return dict prefixed with `_` for raw values, or as a named column for
   display values.
7. **Sector-aware engines (Value, sector bonus) require `sector_status_map`**
   to be ready before `_build_row` runs. The phase ordering inside
   `run_scan` is critical: sector aggregates are computed AFTER per-stock
   classification but BEFORE row building.
8. **Holdings overlay reads scanner columns by name** (`merge_with_scan`
   has the canonical list `SCAN_COLS`). Add to it when you add display
   columns the holdings UI should surface.
9. **Speed budget**: 751 stocks must finish in ~5-12 minutes. Anything new
   that adds a network call per stock needs (a) a batched alternative or
   (b) a sidebar opt-out toggle.
10. **Document new constants** by adding them to Sections 4 / 6 / 10-14 /
    16-19 here, so the next agent can find them.
11. **Keep `run_scan` return shape stable.** Existing keys: `strong`, `wait`,
    `watchlist`, `rejected`, `failed`, `sector_strength`, `top_sectors`,
    `regime`, `nifty_context`, `universe_count`, `scanned_at`, `all_stocks`,
    `sector_rotation`, `coiled`, `fresh`, `price_data`. Add new keys; do not
    remove.
12. **After every change**: run `python -m py_compile *.py` and a synthetic
    smoke test before committing. Streamlit Cloud hot-reload caches modules,
    so always recommend the owner do a full Reboot after pushing.
