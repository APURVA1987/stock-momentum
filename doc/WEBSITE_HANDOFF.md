# WEBSITE_HANDOFF.md

> Handoff document for the NSE Momentum Breakout Dashboard - Streamlit app.
> This file describes **how the dashboard is constructed**: file layout, UI, run
> flow, design conventions, tabs, exports, and the rules future AI agents must
> follow to extend the app without breaking it.
>
> Companion file: [`SCANNER_TECHNICAL_SPEC.md`](SCANNER_TECHNICAL_SPEC.md) -
> describes the scoring math, indicators, classifications and engines.

---

## 1. Project Overview

This is a **local Python + Streamlit dashboard** for NSE (Indian) stock
screening. It runs three engines on the same scan and overlays the user's
broker portfolio on top:

- **Momentum scanner** - finds stocks that recovered from a 200-DMA retest and
  are now breaking out (15-30 day swing horizon).
- **Technical Value scanner** - finds corrected / stabilising / reclaiming
  stocks (mean-reversion complement, technical-first, no fundamentals yet).
- **Holdings overlay** - merges a Zerodha holdings export with scanner output
  and assigns plain-English action labels (Hold, Add on Pullback, Exit Review, etc.).

Design intent:
- **Non-coder friendly**: cards + colour-coded badges + plain decision boxes.
- **Runs locally** with `streamlit run app.py`; the hosted instance lives on
  Streamlit Community Cloud at the repo's `*.streamlit.app` URL.
- **Data source: Yahoo Finance** via `yfinance` (batched download). Optional
  local-only fallback uses NSE bhavcopy + an on-disk price cache.
- **Outputs**: visual dashboard, multi-sheet Excel, and per-bucket CSVs.
- **Educational screening only - not financial advice**. Every action label
  carries a "confirm chart, liquidity, news" disclaimer.

---

## 2. Current Project Structure

```
nse_momentum_dashboard/
|-- app.py                     # Streamlit UI: sidebar, tabs, cards, charts
|-- scanner.py                 # Momentum engine: download, indicators per stock,
|                              #   scoring, classification, sector strength,
|                              #   coiled / fresh / RS leaders / market regime,
|                              #   Claude prompt builders, run_scan() orchestrator
|-- value.py                   # Technical Value engine: value score, value
|                              #   classification, Momentum + Value matrix label
|-- indicators.py              # Math primitives: SMA, RSI, ADX, ATR, slope,
|                              #   true_range, pct_change_over, close_position
|-- holdings.py                # Zerodha CSV/XLSX normaliser, holding action
|                              #   labels, merge_with_scan(), portfolio summary
|-- bhavcopy.py                # OPTIONAL local-only: fetch NSE EOD bhavcopy
|                              #   (UDiFF + legacy fallback) for daily refresh
|-- fundamentals.py            # Lightweight Screener.in URL helper + cached
|                              #   key-ratio scrape for the Stock Deep Dive tab
|-- universe.csv               # Default 751-stock universe (97 large / 368 mid
|                              #   / 286 small) across 43 sectors; columns:
|                              #   symbol, company, sector, market_cap_category
|-- requirements.txt           # streamlit, pandas, numpy, yfinance, plotly,
|                              #   openpyxl, tqdm, requests, beautifulsoup4
|-- README.md                  # End-user setup + non-coder run instructions
|-- doc/                       # <-- THIS FOLDER (handoff documentation)
|   |-- WEBSITE_HANDOFF.md
|   |-- SCANNER_TECHNICAL_SPEC.md
|-- data/                      # Persistent runtime data (created on first use)
|   |-- holdings_latest.xlsx   # Last uploaded Zerodha holdings file
|   |-- nse_large.csv          # Last uploaded NSE Large-Cap constituent list
|   |-- nse_mid.csv            # Last uploaded NSE Mid-Cap constituent list
|   |-- nse_small.csv          # Last uploaded NSE Small-Cap constituent list
|   |-- price_cache_<period>.pkl  # Local-mode OHLCV cache (pickle dict)
|-- outputs/                   # Excel + CSV exports written by the Export tab
    |-- scanner_output.xlsx
    |-- dashboard_summary.xlsx
    |-- <bucket>.csv (see Section 11)
```

### File responsibility map

| File | Layer | Purpose |
|------|-------|---------|
| `app.py` | UI | Streamlit page config, sidebar widgets, tab orchestration, cards/charts/tables, fragment-isolated deep dives, exports trigger, Claude prompt rendering |
| `scanner.py` | Engine | Yahoo batched download, intraday-bar stripping, per-stock indicators, component scoring, classification, sector rotation, RS leaders, coiled/fresh/do-not-chase tagging, Claude prompts |
| `value.py` | Engine | Value Score (0-100) + Value Classification + entry style + Matrix class |
| `indicators.py` | Math | Pure-pandas SMA / RSI / ADX / ATR / slope helpers (no `ta`/`pandas-ta` dependency) |
| `holdings.py` | Overlay | Robust Zerodha column normaliser, cost-vs-MA math, holding_action rule engine, portfolio_summary, combine_universe_holdings |
| `bhavcopy.py` | Optional data | NSE EOD bhavcopy fetcher (local-only; NSE blocks cloud IPs) |
| `fundamentals.py` | Optional data | Screener.in scrape used only in Stock Deep Dive |
| `universe.csv` | Data | Default scan universe (overridable by sidebar uploads) |
| `data/` | Runtime | Persistent user data; auto-loaded on next session |
| `outputs/` | Runtime | All Excel + CSV exports land here |

---

## 3. How to Run

### Local
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```
A browser tab opens at `http://localhost:8501`.

### Streamlit Community Cloud
- Public app: anyone with the URL can run scans.
- Privacy: set `APP_PASSWORD` in **Manage app -> Settings -> Secrets** to gate
  the **My Holdings** tab (see Section 13).

---

## 4. High-Level App Flow

```
1. Streamlit script runs top to bottom.
2. Sidebar widgets read user input:
   - universe.csv override (drag-drop)
   - NSE Large / Mid / Small constituent CSV uploads (persisted under data/)
   - Holdings file upload (persisted under data/holdings_latest.*)
   - Market-cap filter, period (5y/3y/2y), retest window/tolerance,
     RSI / volume thresholds, minimum score, local-mode, EOD-only,
     scan focus (All / Momentum only / Value only).
3. Holdings are loaded only if the visitor has unlocked APP_PASSWORD.
4. On "Run Scan":
   a. Universe is built (CSV / NSE files / default 751-list) then
      combined with the user's holdings so portfolio symbols are ALWAYS
      scanned, even if outside the cap filter.
   b. scanner.run_scan(universe, ..., eod_only=True) is invoked.
5. Inside run_scan():
   a. Nifty 50 ^NSEI downloaded once -> market regime + multi-window returns.
   b. download_universe() does ONE batched yfinance call (or reads the local
      cache + appends bhavcopy in local mode); intraday partial bar is
      stripped during market hours.
   c. For each symbol: compute_metrics() -> full indicator dict.
   d. Phase A: score_components() + classify() per stock.
   e. Phase B: RS Score via percentile rank across the universe.
   f. Phase C: sector aggregates -> sector_strength_score + sector_status.
   g. Phase D: _build_row() per stock -> composite, momentum class, value
      score, matrix class; route to strong / wait / watchlist / rejected.
6. Result dict is stored in st.session_state['result'] and ['price_data']
   for the Stock Deep Dive chart.
7. holdings_norm is merged with all_stocks -> holdings_df with action labels.
8. Tabs render (visibility filtered by Scan focus + holdings auth).
9. Export tab writes scanner_output.xlsx + per-bucket CSVs into outputs/.
10. Claude Review tab generates copy-ready prompts (st.code -> one-click copy).
```

Important: **The whole compute is deterministic for a given universe + period
+ thresholds.** The randomness people see during market hours is real partial
intraday data - solved by the EOD-only toggle (default ON).

---

## 5. Dashboard Design Philosophy

The dashboard is built for someone who does NOT want to read Excel sheets.
Principles, in priority order:

1. **Cards first** - top 5-20 coloured cards per category, immediate read.
2. **Charts second** - one ranking bar + one diagnostic scatter per category.
3. **Tables last** - full table at the bottom (no expander), used for the
   one-time scan and for export. `use_container_width=False` so column widths
   are natural and the Symbol column never shrinks to "AL"/"EY".
4. **Action labels are the headline** - "Hold / Trail", "Add on Pullback",
   "Exit Review", "Wait for trigger" - never just raw scores.
5. **Decision boxes** - every Deep Dive shows a green/yellow/red boxed
   sentence explaining what to do.
6. **Colour-coded** (see Section 7) - the same colour means the same risk
   level everywhere.
7. **Fragment-isolated deep dives** - changing the dropdown re-runs only that
   section, not the page, so scroll position and tab stay put.
8. **No clutter** - the Matrix tab hides the "Mixed" quadrant (noise); each
   tab limits cards to ~15-20.
9. **Transparency** - every classification carries the reason in a "Final
   Remark" / "Confirmation Needed" column.

---

## 6. Main Dashboard Tabs

The full tab list (visible by default; *Scan focus* hides irrelevant ones):

| # | Tab | Purpose | Key visuals | Decision use |
|---|-----|---------|-------------|--------------|
| 1 | **My Holdings** | Portfolio overlay (gated by APP_PASSWORD) | 8 portfolio cards, sector pie, weight bar, P&L bar, action donut + 7 sub-tabs (Summary / In Momentum / Waiting / Weak-Exit / Do Not Chase / Value Recovery / Holding Deep Dive) | What to hold, add, trail, reduce or exit in YOUR portfolio |
| 2 | **Market Overview** | Quick scan snapshot | Classification donut, score-distribution bar, Nifty regime panel, top-10 momentum & RS bars | One-glance health check |
| 3 | **Sector Rotation** | Where to fish | Sector strength bar, top-3 sector cards, sector heatmap (per-column normalised), sector drill-down dropdown | Pick sectors to focus on |
| 4 | **RS Leaders** | Universe-wide RS percentile leaders | RS bar chart, multi-window RS table | Find absolute leaders independent of setup |
| 5 | **Strong Breakout** | Score >= 80 + ALL strict gates passed | All-cards (no cap), ranking bar, risk-reward bubble, full detail table | Most actionable trade candidates |
| 6 | **Wait for Confirmation** | Score 65-79, setup developing | Top-20 cards, distance-to-trigger bar, "what they're waiting for" breakdown, alert watchlist | Set alerts at trigger price; do not enter yet |
| 7 | **Coiled / Ready** | Range contraction + volume dry-up before breakout | Top-20 cards (purple), tightness bar, closest-to-trigger bar | Spring-loaded names; wait for breakout with volume |
| 8 | **Fresh Momentum** | New momentum ignition (may not have done retest) | Top-20 cards (teal), score bar | Prefer entry on small pullback or breakout sustain |
| 9 | **Early Watchlist** | Score 55-64 | Top-15 cards, ranking bar | Observe only |
| 10 | **Do Not Chase** | Strong-but-overextended | Cards + reason + wait-condition column | Trail SL on what you hold; do NOT add fresh |
| 11 | **Momentum Map** | Quadrant visualisation | Score-vs-RelStr scatter, breakout-readiness scatter | Find best risk/reward intersections |
| 12 | **Technical Value Scanner** | Mean-reversion engine | Counts cards + 6 sub-tabs (Summary, Reversal Ready, Base Forming, Deep Value High Risk, Value Trap Avoid, Value Deep Dive) | Find recovery setups |
| 13 | **Momentum + Value Matrix** | High-momentum AND high-value crossover | Quadrant scatter (Mixed hidden), Best Crossover table | The "Best Crossover" list is the highest interest |
| 14 | **Stock Deep Dive** | Per-stock detail | Composite gauge, 5-component breakdown bar, indicator cards, candlestick (MAs + 52W high + trigger + invalidation), Screener fundamentals on-demand | Per-stock decision support |
| 15 | **Rejected / Failed** | Why stocks failed | Reason bar chart, table, failed-tickers list | Debug + universe hygiene |
| 16 | **Claude Review** | 6-9 copy-ready prompts | `st.code()` blocks with one-click copy | Hand off to Claude / ChatGPT for deeper review |
| 17 | **Export** | Save outputs | Buttons + per-bucket download_buttons | Persist scan to disk |

### Nested sub-tabs

- **My Holdings**: Portfolio Summary / In Momentum / Waiting for Confirmation /
  Weak - Exit Review / Do Not Chase / Value Recovery / Holding Deep Dive.
- **Technical Value Scanner**: Summary / Reversal Ready / Base Forming /
  Deep Value High Risk / Value Trap Avoid / Value Deep Dive.

---

## 7. Colour Coding / Visual Language

Colours are consistent across every tab so the user learns them once:

| Theme | Hex | Used for |
|-------|-----|----------|
| Strong green | `#1e7d32` / `#0b6e2e` | Strong Breakout / Actionable, Elite Momentum, Best Crossover, Hold / Trail, Add on Pullback, **Low Risk** |
| Orange / amber | `#e08e0b` | Wait for Confirmation, Hold-Set-Alert, **Medium Risk**, "Improving" sector |
| Blue | `#1f77b4` / `#1f4e79` | Early Watchlist, Value Base Forming, "Neutral" sector |
| Purple | `#6a1b9a` | Coiled / Ready (distinct from momentum/value) |
| Teal | `#00897b` | Fresh Momentum (distinct ignition signal) |
| Red | `#8b1e1e` / `#6e0b0b` / `#b71c1c` | Rejected, Value Trap Avoid, **High Risk**, Exit Review, Review / Reduce |
| Grey | `#37474f` / `#555` | Neutral metric cards, "Mixed" matrix, no-data |

Matrix class colours: Best Crossover = green, Momentum Leader = green-bright,
Value Recovery = blue, Mixed = grey (HIDDEN from view), Avoid = red.

Holding-action colours map to the same logic (action -> colour).

---

## 8. Cards and Metrics

### Top page cards (always visible after a scan)

- Total Scanned
- Strong Breakout
- Wait for Confirmation
- Early Watchlist
- Rejected
- Failed Tickers

### Portfolio cards (My Holdings tab, when authenticated)

- Total Current Value
- Total Invested
- Total P&L (green if positive, red if negative)
- Total P&L %
- Holdings in Momentum
- Holdings Waiting / Set Alert
- Holdings Weak / Exit Review
- Top Holding Weight % (+ holdings count subtitle)

### Sector Rotation cards
- Top 3 sectors -> sector name, avg 20-day return, "{strong} strong / {wait} wait" subtitle.

### Market Regime panel (inside Market Overview tab)
- Nifty Close, vs 50 DMA (Above/Below), vs 200 DMA, Nifty 20-day return %.

### Per-stock cards (in each engine tab)
Used inside `stock_cards(df, n, accent, fields)`. Top 5-20 with the engine's
key metrics (Score, CMP, RSI, Vol Ratio, Trigger, Distance to Trigger, Risk,
Entry, Stop, Targets). Cards wrap 5 per row.

---

## 9. Charts Used in Dashboard

All charts are **Plotly** (`plotly.express` for quick frames, `plotly.graph_objects`
for the gauge, candlestick, and the heatmap). Reasons for Plotly: pan/zoom,
hover, no extra dependency, dark/light agnostic.

| Chart | Tab | Type |
|-------|-----|------|
| Classification donut | Market Overview | `px.pie(hole=0.5)` |
| Score distribution | Market Overview | bar (band counts) |
| Top 10 by Composite Score | Market Overview | bar, colour by Classification |
| Top 10 by Relative Strength % | Market Overview | bar, colour by Classification |
| Sector Strength bar | Sector Rotation | h-bar, colour by avg 20D return (RdYlGn) |
| Sector heatmap | Sector Rotation | `go.Heatmap` with per-column normalisation and value annotations (no matplotlib dependency) |
| Strong Breakout ranking | Strong Breakout | h-bar, colour=Score, Greens scale |
| Risk-vs-Reward bubble | Strong Breakout | `px.scatter`, x=Risk%, y=RR ratio, size=Volume Ratio, colour=Risk Level |
| Distance-to-Trigger bar | Wait for Confirmation | h-bar, Oranges_r |
| Confirmation breakdown | Wait for Confirmation | h-bar of needed-condition counts |
| Tightest coiled setups | Coiled / Ready | h-bar, Purples |
| Closest to breakout trigger | Coiled / Ready | h-bar, Purples_r |
| Top fresh momentum | Fresh Momentum | h-bar, Teal |
| Momentum vs Strength scatter | Momentum Map | bubble, x=RelStr, y=Composite Score, size=Volume |
| Breakout readiness scatter | Momentum Map | bubble, x=Dist 52W High, y=Volume Ratio, size=Score |
| Value score distribution | Tech Value | bar |
| Best Crossover quadrant | Momentum + Value Matrix | bubble scatter, Mixed quadrant filtered out |
| Composite gauge | Stock Deep Dive | `go.Indicator(mode='gauge+number')` with zoned ranges (0-55 red, 55-65 blue, 65-80 orange, 80-100 green) |
| Score breakdown bar | Stock Deep Dive | h-bar of normalised sub-scores |
| Candlestick + 20/50/200 DMA + 52W high + trigger + invalidation + Volume + RSI + ADX | Stock Deep Dive, Value Deep Dive, Holding Deep Dive | `make_subplots(rows=4)` with `go.Candlestick`, `go.Scatter`, `go.Bar`, hlines |
| Portfolio allocation pie | My Holdings | `px.pie` by Sector, weighted by current_value |
| Top weight bar | My Holdings | h-bar of portfolio_weight_pct |
| P&L per holding | My Holdings | h-bar of pnl, RdYlGn diverging colour |
| Holdings classification donut | My Holdings | `px.pie(hole=0.5)` by action label |
| Rejection-reason bar | Rejected / Failed | h-bar count by Reason |

The `_NullTab` wrapper plus `@_fragment` decorator are the two architectural
tricks that keep this many charts manageable: hidden tabs render to an empty
container that's cleared on exit; Deep Dives re-run only the fragment.

---

## 10. My Holdings UI Flow

1. **Upload** under sidebar -> `My Holdings (Zerodha)` -> drop `.xlsx`/`.xls`/`.csv`.
2. **Persistence**: file is saved as `data/holdings_latest.<ext>` and becomes
   the default for every subsequent session.
3. **Auth gate**: if `APP_PASSWORD` is set in `st.secrets`, the upload widget
   and tab are hidden until the password is entered. Without the password,
   `holdings_norm` is empty and NOTHING about the portfolio appears anywhere
   (tab, exports, Claude prompts).
4. **Normalisation** (`holdings.normalise_holdings`):
   - Maps Zerodha headers (`Instrument`, `Qty.`, `Avg. cost`, `LTP`, `Invested`,
     `Cur. val`, `P&L`, `Net chg.`, `Day chg.`) into our schema (symbol,
     quantity, avg_cost, ltp, invested, current_value, pnl, net_change_pct,
     day_change_pct).
   - Strips Indian-comma thousand separators and trailing `%` signs.
   - Recomputes `pnl` & `pnl_pct` from `invested`/`current_value` (more reliable
     than the broker column).
   - Drops `GRAND TOTAL` rows and blanks.
5. **Universe inclusion**: `combine_universe_holdings()` adds every holding
   symbol to the scan even if it's outside `universe.csv`, tagged with
   `source_type` = `Holding` or `Universe + Holding`.
6. **Merge with scan**: `merge_with_scan(holdings_df, result['all_stocks'])`
   left-joins scanner columns + computes:
   - `avg_vs_cmp_pct`, `avg_vs_20dma_pct`, `avg_vs_50dma_pct`, `avg_vs_200dma_pct`,
     `cmp_vs_200dma_pct`
   - `holding_action` (rule-based, see SCANNER_TECHNICAL_SPEC) +
     `holding_remark` (plain-English).
7. **Display**: portfolio cards -> 7 sub-tabs filtered by action label ->
   Holding Deep Dive (fragment-isolated) with candlestick + technical levels.

---

## 11. Export System

### Excel workbook `outputs/scanner_output.xlsx`
Sheets present (some may be empty if no rows in that bucket):

- `Elite_Momentum`
- `Actionable_Breakout`
- `Strong_Breakout`
- `Wait_For_Confirmation`
- `Coiled_Ready`
- `Fresh_Momentum`
- `Early_Watchlist`
- `RS_Leaders`
- `Sector_Rotation`
- `Do_Not_Chase`
- `Value_Reversal_Ready`
- `Value_Base_Forming`
- `Deep_Value_High_Risk`
- `Value_Trap_Avoid`
- `Momentum_Value_Matrix`
- `Rejected`
- `Failed_Tickers`
- `Sector_Strength`
- `Market_Regime`
- `Claude_Review` (one row per prompt)
- `My_Holdings_All` (if authenticated)
- `Holdings_In_Momentum` (if authenticated)
- `Holdings_Wait_For_Confirmation` (if authenticated)
- `Holdings_Weak_Exit_Review` (if authenticated)
- `Holdings_Do_Not_Chase` (if authenticated)
- `Holdings_Value_Recovery` (if authenticated)
- `Portfolio_Summary` (if authenticated)

### Optional secondary workbook `outputs/dashboard_summary.xlsx`
- `Dashboard_Summary`
- `Sector_Strength`
- `Top_10_Strong`
- `Top_10_Wait_For_Confirmation`
- `Overextended_Stocks`

### Per-bucket CSVs (also in `outputs/`)
- `strong_breakout.csv`
- `wait_for_confirmation.csv`
- `coiled_ready.csv`
- `fresh_momentum.csv`
- `early_watchlist.csv`
- `rs_leaders.csv`
- `sector_rotation.csv`
- `do_not_chase.csv`
- `rejected_stocks.csv`
- `value_reversal_ready.csv`
- `value_base_forming.csv`
- `momentum_value_matrix.csv`
- `my_holdings_all.csv` (auth-gated)
- `holdings_in_momentum.csv` (auth-gated)
- `holdings_weak_exit_review.csv` (auth-gated)

Note: on Streamlit Cloud `outputs/` is ephemeral; use the per-bucket
`st.download_button()` in the Export tab to save to your machine.

---

## 12. Claude Review Tab

The tab presents 6-9 prompts via `st.code()` blocks (one-click copy icon at
the top-right). Each prompt is built by a function in `scanner.py`
(`build_strong_prompt`, `build_wait_prompt`, `build_coiled_prompt`,
`build_fresh_prompt`, `build_donotchase_prompt`) plus three inline value
prompts and one holdings prompt assembled in `app.py`.

Common ending in every prompt:
> "Check latest news, results, sector strength, technical structure,
> support/resistance, and whether this is suitable for a 15-30 day swing trade.
> Do not recommend entry if the confirmation condition is not met.
> Rank them best to weakest."

Prompts shown:
1. Elite / Actionable Breakout
2. Wait for Confirmation
3. Coiled / Ready
4. Fresh Momentum
5. Do Not Chase
6. Value Reversal Ready
7. Value Base Forming
8. Best Crossover (Momentum + Value)
9. My Holdings Review (only if authenticated and `holdings_df` is non-empty;
   explicit "do not recommend blind averaging down" instruction)

---

## 13. Non-Coder Safeguards

- Sidebar `help=` tooltips on every parameter ("?" hover).
- Defaults chosen so that "click Run Scan" works without any tuning.
- The **End-of-day data only** toggle (default ON) prevents the
  "fewer-stocks-during-market-hours" surprise.
- The **Scan focus** dropdown lets users hide whole engines they don't want.
- Action labels and decision boxes always carry a plain-English sentence;
  raw scores are secondary.
- Warning banner when Market Regime = Weak.
- Warning banner when Local mode = ON during market hours and EOD-only is OFF.
- Failed tickers go to a dedicated sub-table, not the main view.
- Holdings tab is locked by default if `APP_PASSWORD` is set so an inadvertent
  share of the URL does not leak the portfolio.

---

## 14. Future UI Improvements

- Persist user preferences (period, focus, thresholds) in session/local file.
- Dark/light mode tied to OS preference (Streamlit currently auto-switches).
- Browser push / email / Telegram alert when a "Wait for Confirmation" stock
  crosses its trigger price (would need a scheduled background job).
- One-click PDF report (use `kaleido` to render Plotly to PNG + write via
  `reportlab` or `weasyprint`).
- Daily scheduled scan -> email summary (cron + a tiny mailer module).
- True multi-user login (email allow-list via `streamlit-authenticator`) when
  the app is hosted properly.
- Watchlist persistence (a tiny SQLite file in `data/`).
- "What changed since the last scan" diff view.

---

## 15. Development Rules for Future AI Agents

These rules are not optional. Read them before editing.

1. **Do not rebuild the app from scratch.** It is incremental and already
   works for the owner. Add modules; do not rewrite.
2. **Inspect the actual columns** of `all_stocks` / `strong` / `wait` /
   `holdings_df` before referencing them. Many were added incrementally and
   may not exist on the first row.
3. **Preserve the existing scoring formulas.** If you change a constant in
   `scanner.py` or `value.py`, update `SCANNER_TECHNICAL_SPEC.md` in the
   same commit.
4. **Add columns; do not rename them.** External Excel/CSV users and the
   holdings overlay depend on stable column names.
5. **Do not slow down the scan.** Current time on 751 stocks is ~5-12 min;
   anything that increases this needs a sidebar toggle so the user can opt
   out. Use the in-memory `result['price_data']` dict before any new
   per-stock Yahoo call.
6. **Use `st.cache_data`** for any new per-symbol HTTP fetch.
7. **Wrap deep-dive-style dropdowns in `@_fragment`** (the helper defined
   at the top of `app.py`). This is non-negotiable: full-page reruns kill
   UX badly.
8. **Keep `_NullTab` semantics intact** if you add tabs - check that the
   `_hidden` set in the Scan-focus filter still produces sensible groupings.
9. **Backward-compatible exports** - new sheets are fine, renaming is not.
10. **Never commit secrets**. `APP_PASSWORD` lives in `st.secrets`, not in
    the repo.
11. **Update this file and `SCANNER_TECHNICAL_SPEC.md`** in the same commit
    as significant feature additions.
12. **Reboot vs refresh**: any change that touches `scanner.py` or a new
    Python module needs a full Streamlit Cloud Reboot, not just a browser
    refresh (hot-reload may cache the old module).
