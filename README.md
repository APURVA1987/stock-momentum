# NSE Momentum Breakout Scanner - 200 DMA Retest Strategy

A local Streamlit dashboard that scans NSE large-cap and mid-cap stocks for a
specific momentum setup: stocks that were near their 52-week / all-time high,
pulled back toward the **200-day moving average (200 DMA)**, respected it,
recovered, and are now approaching or crossing their previous high again.

Trading horizon: **15 to 30 days** (swing trading).
Data source: **Yahoo Finance** via the `yfinance` library.

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
