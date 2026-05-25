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
   - Market cap category: Large Cap only / Mid Cap only / Both
   - Data period: 2y / 3y / 5y
   - Filter settings (retest window, RSI, volume ratio, minimum score)
2. (Optional) Upload your own `universe.csv` from the sidebar.
   If you don't upload one, the default `universe.csv` in this folder is used.
3. Click **Run Scan**. A progress bar shows scanning status.
4. Review results in the tabs:
   - **Ranked Results** – scored & colour-coded table
   - **Stock Chart** – candlestick + 20/50/200 DMA + volume + RSI
   - **Rejected** – stocks that failed, with the reason
   - **Claude Review** – an auto-generated prompt to paste into Claude/ChatGPT
   - **Export** – save Excel + CSV into the `outputs/` folder

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

## 6. Output files

After clicking **Save Excel + CSV** in the Export tab, you get:

- `outputs/scanner_output.xlsx` with sheets:
  `Scanner_Output`, `Raw_Summary`, `Rejected`, `Failed_Tickers`, `Claude_Review`
- `outputs/scanner_output.csv`
- `outputs/rejected_stocks.csv`

---

## 7. The strategy in plain words

A stock qualifies when **most** of these are true:

- **Trend:** Close > 200 DMA, 50 DMA > 200 DMA, 200 DMA rising over 30 days.
- **Pullback:** in the last ~60 days the low came within ~3-7% of the 200 DMA,
  and the stock did **not** spend too long (>10 days) below the 200 DMA.
- **Recovery:** Close > 20 DMA and > 50 DMA, RSI(14) > 55, volume picking up.
- **Breakout:** within 5% of the 52-week high (or above the previous high),
  and stronger than the Nifty over the last 20 days.

Each stock is scored out of 100 and tagged Low / Medium / High risk.

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
