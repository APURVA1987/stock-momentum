# NSE Momentum Breakout Scanner - 200 DMA Retest Strategy

A local Streamlit dashboard that scans NSE large-cap and mid-cap stocks for a
specific momentum setup: stocks that were near their 52-week / all-time high,
pulled back toward the **200-day moving average (200 DMA)**, respected it,
recovered, and are now approaching or crossing their previous high again.

Trading horizon: **15 to 30 days** (swing trading).
Data source: **Yahoo Finance** via the `yfinance` library. Prices are downloaded in
**batches** (~50 tickers per request, threaded), so even a 600+ stock universe makes
only ~13 requests instead of one-per-stock - this avoids Yahoo rate-limits and keeps
the scan fast.

**Local mode (optional, your PC only):** tick **"Local mode (NSE bhavcopy + price
cache)"** in the sidebar to (a) reuse a local price cache so repeat daily runs barely
touch Yahoo, and (b) overlay the latest **official NSE bhavcopy** day on top of Yahoo's
history. NSE blocks data-centre IPs, so this works only when you run the app on your own
computer - leave it **OFF on Streamlit Cloud**. Yahoo still supplies the multi-year
(split-adjusted) history; bhavcopy only refreshes the most recent trading day.

---

## 1. One-time setup (install Python packages)

You only do this once.

1. Install **Python 3.10 or newer** from https://www.python.org/downloads/
   (During install on Windows, tick **"Add Python to PATH"**.)
2. Open this folder (`nse_momentum_dashboard`) in **VS Code**.
3. Open a terminal in VS Code: menu **Terminal -> New Terminal**.
4. (Recommended) Create a clean virtual environment so packages stay tidy:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks the activate script, run this once and try again:

   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

5. Install the required packages:

   ```powershell
   pip install -r requirements.txt
   ```

---

## 2. How to run the dashboard

In the same terminal (inside this folder), run:

```powershell
streamlit run app.py
```

A browser tab will open automatically (usually at http://localhost:8501).
To stop it, go back to the terminal and press **Ctrl + C**.

---

## 3. How to use it

1. In the **left sidebar**, choose:
   - Market cap category: All / Large Cap only / Mid Cap only / Small Cap only /
     Large + Mid / Mid + Small  (the universe now includes ~70 small caps too)
   - Data period: 2y / 3y / 5y
   - Filter settings (retest window, RSI, volume ratio, minimum score)
2. (Optional) Upload your own `universe.csv` from the sidebar.
   If you don't upload one, the default `universe.csv` in this folder is used.
   - **Easier alternative:** open the **"Or: upload NSE index CSVs (one per cap tier)"**
     expander and drop in the official niftyindices.com constituent files
     (`ind_nifty100list.csv` → Large Cap, `ind_niftymidcap150list.csv` → Mid Cap,
     `ind_niftysmallcap250list.csv` → Small Cap). The app auto-maps `Symbol`,
     `Company Name`, `Industry`, filters `Series == EQ`, dedups by symbol, and
     uses the slot label as the cap tier — no editing required.
3. Click **Run Scan**. A progress bar shows scanning status.
4. Read the **summary cards** at the top: Total Scanned, Strong Breakout,
   Wait for Confirmation, Early Watchlist, Rejected, Market Regime,
   Top 3 Sectors, Failed Tickers.
5. Review results in the visual tabs (explained in section 7 below):
   **Market Overview · Sector Rotation · RS Leaders · Strong Breakout ·
   Wait for Confirmation · Coiled / Ready · Fresh Momentum · Early Watchlist ·
   Do Not Chase · Momentum Map · Stock Deep Dive · Rejected / Failed ·
   Claude Review · Export**.

---

## 4. How to edit `universe.csv`

Open `universe.csv` in VS Code or Excel. Keep these exact columns:

```
symbol,company,sector,market_cap_category
RELIANCE,Reliance Industries,Energy,Large Cap
DIXON,Dixon Technologies,EMS,Mid Cap
```

- `symbol` = NSE symbol **without** the `.NS` suffix (the app adds `.NS` for you).
- `market_cap_category` must be exactly `Large Cap` or `Mid Cap`.

Save the file. Re-run the scan to pick up your changes.

---

## 5. How to refresh a scan

Just click **Run Scan** again. To force fresh data downloads (clear the cache),
press **C** in the dashboard, or restart with `streamlit run app.py`.

---

## 6. Output files (Export tab)

Click **Save Excel + CSVs to outputs/ folder** in the Export tab to create:

- `outputs/scanner_output.xlsx` with 7 sheets:
  `Strong_Breakout`, `Wait_For_Confirmation`, `Early_Watchlist`, `Rejected`,
  `Sector_Strength`, `Market_Regime`, `Claude_Review`
- `outputs/strong_breakout.csv`
- `outputs/wait_for_confirmation.csv`
- `outputs/early_watchlist.csv`
- `outputs/rejected_stocks.csv`

> On Streamlit Cloud the `outputs/` folder is temporary (wiped on restart).
> Use the **Download** buttons in the Export tab to save files to your computer.

---

## 7. The visual dashboard - what each tab means

The app is a graphical dashboard. At the very top you always see a **header**
(scan time, universe size, period, market-regime badge) and **six coloured
summary cards** (Total Scanned, Strong Breakout, Wait for Confirmation, Early
Watchlist, Rejected, Failed). Below that are the tabs:

| Tab | What it shows |
|-----|---------------|
| **Market Overview** | Quick snapshot: classification donut, score-distribution bars, Nifty market-regime panel, and Top-10 charts by score and by relative strength. |
| **Sector Rotation** | Which sectors are leading *now*. Top-sector cards, a sector-strength-score (0-100) bar, a colour heatmap (returns / RS / breadth), full table, and a sector drill-down. Each stock also gets a `Sector Status` of Leading / Improving / Neutral / Weak. |
| **RS Leaders** | Multi-timeframe **relative strength** leaders. `RS Score` (0-100) is the percentile rank of a stock's relative strength vs Nifty across 5D/20D/60D/120D/252D. An **RS Leader** has RS Score >= 80, positive RS on 20D & 60D, and price above its 50 & 200 DMA. |
| **Strong Breakout** | Score >= 80, all entry conditions met. Top-5 green cards, a ranking bar chart, a risk-vs-reward bubble chart, and a detailed table at the bottom. |
| **Wait for Confirmation** | Score 65-79, breakout **not confirmed yet**. Orange cards, a "closest to trigger" chart, a "what are they waiting for" breakdown, and an alert watchlist table. |
| **Coiled / Ready** | Stocks **coiling** before a breakout: tight recent range + ATR contraction + volume dry-up while holding above 50/200 DMA near the 52W high. `Coiled Score` ranks them; "closest to trigger" shows which may pop first. *Preparing - do not enter until breakout with volume.* |
| **Fresh Momentum** | Stocks **igniting a new move** (even if they never did a 200-DMA retest): Close > 20 > 50 > 200 DMA (rising), volume expansion, RSI 55-72, ADX confirming, at/near a 20-day high, RS Score >= 70. *Prefer entry on a small pullback or breakout sustain.* |
| **Early Watchlist** | Score 55-64. Momentum building but not ready. Blue cards + ranking chart. Observe only. |
| **Do Not Chase** | Stocks that may be strong but are **overextended** right now (too far above 20/50/200 DMA, RSI > 75, big gap up, or poor risk-reward). Each shows a `No Chase Reason` and a `Wait Condition` (e.g. "wait for pullback to 20 DMA"). Good stocks - just not a good *fresh entry* today. |
| **Momentum Map** | Scatter maps: Momentum-vs-Strength and Breakout-readiness (bubble = volume/score), plus an "overextended - avoid chasing" list. |
| **Stock Deep Dive** | Pick any stock: summary card, **Composite-Score gauge**, a score-breakdown bar (Trend / RS / Sector / Breakout / Pullback / Risk), full candlestick (20/50/100/200 DMA + 52W-high + trigger + stop lines + Volume/RSI/ADX), indicator cards, and a plain-English decision box. |
| **Rejected / Failed** | A bar chart of *why* stocks were rejected, the rejected table, and the failed-tickers list. |
| **Claude Review** | Five ready-to-paste prompts (Elite/Actionable, Wait, Coiled, Fresh, Do Not Chase), each with the full context (composite, RS, sector, breakout, pullback, trigger, invalidation, risk) and a one-click copy icon. |
| **Export** | Save the full Excel workbook (Elite_Momentum, Actionable_Breakout, Strong_Breakout, Wait_For_Confirmation, Coiled_Ready, Fresh_Momentum, Early_Watchlist, RS_Leaders, Sector_Rotation, Do_Not_Chase, Rejected, Failed_Tickers, Claude_Review sheets), the `dashboard_summary.xlsx`, and per-category CSV files. |

**Screener.in integration:** every shortlisted stock's symbol is a **clickable link**
(cards show a link icon; tables have a "Screener" column) that opens its Screener.in
page in a new tab. In **Stock Deep Dive**, click **Fetch fundamentals** to pull key
ratios (Market Cap, P/E, Book Value, ROCE, ROE, Dividend Yield) on demand for that one
stock. Fundamentals are fetched only for stocks you look at - never for the whole
universe - and fail gracefully (showing "unavailable") if Screener blocks the request.

**Pullback Quality** (also a Composite input): for any dip-and-recover, the app
labels the **Pullback Type** (20/50/100 DMA Bounce, 200 DMA Retest, Broken 200 DMA
Recovery, or No Valid Pullback) and scores it 0-100 on whether it respected a moving
average, fell on lower volume than it recovered on, recovered quickly, had a
controlled drawdown, and reclaimed the 20/50 DMA.

### Composite Momentum Score (the main score)
Each stock now also gets a **Composite Momentum Score (0-100)** that blends five
engines: Trend 25% + RS Score 25% + Breakout Quality 20% + Sector Strength 15% +
Risk Quality 15%. Its label (`Momentum Class`) is:
**Elite Momentum (85+) · Actionable Breakout (75-85) · Wait for Confirmation
(65-75) · Early Watchlist (55-65) · Ignore (<55)**. The original rule-based
`Score` / classification is kept for reference and still drives the Strong /
Wait / Early tabs.

> Note: a stock can have a high Composite Score but still sit in **Rejected**,
> because the rule classification requires the specific 200-DMA-retest setup
> (e.g. a stock that never pulled back). Use **RS Leaders** and **Do Not Chase**
> to find those strong-but-different names.

### How to read RS, Sector and Do-Not-Chase together
- **RS Leaders** = strongest stocks vs the market, any setup.
- **Sector Rotation** = which *groups* money is flowing into.
- A great candidate is an RS Leader, in a *Leading* sector, that is **not** in
  Do Not Chase. If it is in Do Not Chase, wait for the stated condition.

### Daily workflow
1. **Run Scan** (~5 min).
2. Check the **Market Regime** badge - if Weak, trade smaller / be selective.
3. Open **Sector Rotation** - note the top 2-3 leading sectors.
4. Open **RS Leaders** - the market's strongest names.
5. Work the **Strong Breakout** -> **Wait for Confirmation** -> **Early Watchlist** tabs.
6. Skip anything sitting in **Do Not Chase** until its wait condition is met.
7. **Stock Deep Dive** the few names you like; then **Export** or use **Claude Review**.

### How to interpret the charts
- **Donut / summary cards** - how your universe split across the four buckets.
- **Bar charts** (score, relative strength, distance-to-trigger) - longer/closer
  to the top = stronger or nearer to action.
- **Risk-vs-Reward bubble** - prefer points that are *high* (better reward per
  unit risk) with a *green* colour (Low Risk); big bubbles = heavier volume.
- **Momentum Map scatter** - top-right = strong momentum *and* beating the Nifty.
- **Score gauge** (Deep Dive) - green zone (80-100) is the strongest, red (<55) weakest.

### What is "Wait for Confirmation"?
These are good-but-not-yet-ready stocks. They have recovered above the 200 DMA
and are climbing, but haven't *confirmed* a breakout (e.g. RSI still under 60,
volume not yet 1.5x, or price still below the 52-week high). The
**Confirmation Needed** column states the missing condition in plain English.

### How to use the Trigger Price
- **Trigger Price** = the level the stock must close above for the setup to confirm
  (the 52-week high, the latest high, or the 50 DMA depending on where price is).
- **Suggested Alert Price** = 1% below the trigger — set your price alert here so
  you get warned *before* the breakout.
- **Invalidation Level** = if price falls below this, the setup is broken (it is the
  swing low / 50 DMA / 200 DMA depending on risk). Do **not** hold below it.

### How to read the Score (out of 100)
Five transparent buckets (shown component-wise in the Stock Chart detailed view):
- **Trend Quality – 25** (above 200 DMA, 50>200, 200 rising, above 20 & 50 DMA)
- **Pullback Quality – 20** (retested 200 DMA, few days below it, dry-up volume, clean recovery)
- **Momentum Quality – 20** (RSI>60, ADX>20, relative strength positive, beating Nifty)
- **Breakout Quality – 20** (near/above 52W high, volume>1.5x, strong candle close)
- **Risk Quality – 15** (not overextended from 20/200 DMA, risk-reward >=1.5, market supportive)

A small +2 bonus is added for stocks in a top-3 sector (capped at 100).

### Market Regime
Based on the Nifty 50 (close vs 50/200 DMA and 20-day return) the app shows
**Bullish / Neutral / Weak**. In a **Weak** regime, rows are marked
"Trade with caution" and the market-supportive score point is withheld.

---

## 8. The strategy in plain words

A stock scores highly when **most** of these are true:

- **Trend:** Close > 200 DMA, 50 DMA > 200 DMA, 200 DMA rising.
- **Pullback:** the low recently came near the 200 DMA on *lower* volume, and
  the stock did not spend long below the 200 DMA.
- **Recovery:** Close back above 20 & 50 DMA, RSI strengthening, ADX confirming trend.
- **Breakout:** near/above the 52-week high on *expanding* volume, with a strong
  candle close and positive relative strength vs the Nifty.

The classification then sorts these into Strong / Wait / Watchlist / Rejected.

---

## Privacy & access control

The momentum / value scans are public to anyone with the app URL.
The **My Holdings overlay is gated by a password** so your portfolio is
not exposed when you share the link with friends:

1. On Streamlit Cloud, open **Manage app -> Settings -> Secrets** and add:
   ```
   APP_PASSWORD = "your-private-password"
   ```
2. Reboot the app. The **My Holdings** tab disappears for un-authenticated
   visitors and the holdings file is not loaded.
3. The owner enters the password in the sidebar (**My Holdings (Zerodha)**)
   to unlock - holdings then load, combine into the scan, render in the tab,
   appear in the export, and show in the Claude prompt.

If `APP_PASSWORD` is not set in secrets, the gate is OFF (zero-friction
single-user / local use). For full app-wide privacy, switch the Streamlit
Cloud app to a private app under **Settings -> Sharing** (requires a paid
plan).

## NSE constituent files - now persistent

Once you upload an `ind_nifty100list` / `ind_niftymidcap150list` /
`ind_niftysmallcap250list` CSV in the sidebar, it is saved as the default
under `data/nse_<cap>.csv` and re-used automatically on every future
session. When ANY NSE file is present (uploaded or saved default), it
**overrides** the in-repo `universe.csv`, so a smaller curated NSE-only
universe is used instead of the larger fallback list.

## Scan focus (reduce on-screen clutter)

The sidebar has a **Scan focus** selector:

- *All (Momentum + Value)* - shows every tab (default).
- *Momentum only* - hides the Technical Value Scanner tab.
- *Value only* - hides Strong Breakout, Wait, Coiled, Fresh, Do Not Chase,
  Momentum Map and RS Leaders.

Scan time and exports are unchanged - this is a UI filter only.

In the **Momentum + Value Matrix** tab, the *Mixed* quadrant (stocks that
are average on both axes) is filtered out. Only the four meaningful
quadrants are shown - **Best Crossover**, **Momentum Leader**, **Value
Recovery**, **Avoid**.

## Technical Value Scanner & Momentum + Value Matrix (Phase 2)

A second engine on the same scan that finds **corrected / stabilising / reclaiming**
stocks rather than momentum leaders. Pure-technical (no fundamentals).

For every stock we compute:
- Multi-window range tightness (10/30/60/90 day), ATR contraction, volume dry-up.
- Drawdowns: 6-month and 1-year max drawdown, fresh-3-month-low flag.
- Recovery signals: RSI 2-week change, MACD bullish flag (manual 12/26/9),
  up-day vs down-day volume ratio, lower-highs count.
- Distance from 20/50/100/200 DMA + the 50 DMA slope.

**Value Score (0-100)** = Correction Opportunity (20) + Stabilisation/Base (25)
+ Reversal Confirmation (25) + Relative Strength Improvement (15) + Risk Control (15).

**Value Classification**:
| Class | Meaning |
|-------|---------|
| **Value Reversal Ready** | Score >=75, 15-40% below 52W high, above 20 DMA, reclaiming 50 DMA, RSI>50, RS improving, no fresh 3-month low. *Recovery confirmed - chart/news review before entry.* |
| **Value Base Forming** | Score 60-75, range contracting, volume drying up, higher lows, near 50 / 200 DMA. *Set alert above base resistance.* |
| **Deep Value High Risk** | >35% off 52W high with some stabilisation but sector OK. *Small watchlist only.* |
| **Value Trap Avoid** | Below falling 200 DMA, fresh lows, RSI weak, or weak sector. *Avoid until structure improves.* |

Each row also carries an **entry style** (Reclaiming 50 DMA / Base breakout / 200 DMA support / Reversal from oversold / Deep value wait), a **Value Trigger**, **Value Invalidation**, and a **Value Target Zone**.

The **Momentum + Value Matrix** tab is a scatter plot (X = value, Y = momentum, bubble = volume) with four named quadrants tagged on each stock:
- **Best Crossover** (high momentum AND high value) - the strongest interest list.
- **Momentum Leader** (high momentum, lower value).
- **Value Recovery** (high value, lower momentum).
- **Mixed** / **Avoid** (low on both).

Three new Claude prompts are added (*Value Reversal Ready*, *Value Base Forming*, *Best Crossover*). Holdings that surface as `Value Reversal Ready` or `Value Base Forming` appear in a new **Holdings -> Value Recovery** sub-tab.

Exports added: `Value_Reversal_Ready`, `Value_Base_Forming`, `Deep_Value_High_Risk`, `Value_Trap_Avoid`, `Momentum_Value_Matrix`, `Holdings_Value_Recovery` (sheets) + CSVs.

---

## My Holdings overlay (Zerodha)

Drop your Zerodha holdings export (`.xlsx` / `.xls` / `.csv`) into the sidebar
under **My Holdings (Zerodha)**. The file is saved to `data/holdings_latest.*`
and used as the default on every future scan until you upload a new one.

What happens:
- Your holding symbols are **always scanned** (even if they are not in
  `universe.csv` / your uploaded NSE files) - they get a `source_type` of
  `Holding` or `Universe + Holding`.
- Each holding is merged with the scanner output (composite score, RS score,
  sector status, breakout/pullback, trigger, invalidation, risk level) plus
  cost-vs-MA metrics (`avg_vs_cmp_pct`, `avg_vs_200dma_pct`, `cmp_vs_200dma_pct`).
- A rule-based **holding_action** is assigned: *Hold / Trail*, *Add on Pullback*,
  *Hold, Set Alert*, *Do Not Add / Trail Only*, *Review / Reduce*, *Exit Review*,
  *Watch Only*, or *No Scanner Data*.

A new **"My Holdings"** tab appears at the top of the dashboard with sub-tabs:
*Portfolio Summary · In Momentum · Waiting for Confirmation · Weak / Exit Review
· Do Not Chase · Holding Deep Dive*. The export workbook now also includes
`My_Holdings_All`, `Holdings_In_Momentum`, `Holdings_Wait_For_Confirmation`,
`Holdings_Weak_Exit_Review`, `Holdings_Do_Not_Chase`, and `Portfolio_Summary`
sheets, plus matching CSVs. A 6th Claude prompt ("My Holdings Review") is added
to the Claude Review tab.

---

## WARNING

This tool is for **educational screening only. It is NOT financial advice.**
You must independently confirm the chart, liquidity, news, results and risk
before making any trade. Trading involves risk of loss.

---

## Coming later (not in this MVP)

- NSE bhavcopy as an alternate data source
- Fundamentals from Screener
- Telegram alerts
- Scheduled daily scans
- Hosted web version
