# fundamentals.py
# -----------------------------------------------------------------------------
# Light, OPTIONAL fundamentals helper that reads the "top ratios" block from a
# stock's Screener.in page (P/E, ROE, ROCE, Market Cap, etc.).
#
# IMPORTANT DESIGN NOTES (for non-coders):
# - We ONLY fetch fundamentals for the SHORTLISTED stocks you actually look at,
#   never for the whole 600+ universe. Screener.in is stricter than Yahoo and
#   would block a mass scrape.
# - Every function fails GRACEFULLY: if Screener is unreachable or blocks the
#   request, it returns None and the dashboard simply shows "unavailable".
# - This needs the `requests` and `beautifulsoup4` packages (see requirements.txt).
# -----------------------------------------------------------------------------

import os
import math

try:
    import requests
    from bs4 import BeautifulSoup
    _DEPS_OK = True
except Exception:                       # packages missing -> feature disabled, app still runs
    _DEPS_OK = False

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


def screener_url(symbol: str) -> str:
    """Public Screener.in page for an NSE symbol (used for the clickable links)."""
    return f"https://www.screener.in/company/{str(symbol).strip().upper()}/"


def get_fundamentals(symbol: str, timeout: int = 12) -> dict | None:
    """Scrape the top-ratios block from Screener.in for one symbol.

    Returns a dict like {"Market Cap": "1,23,456 Cr.", "Stock P/E": "28.4",
    "ROCE": "18.2 %", ..., "_url": "https://..."} or None if anything fails.
    """
    if not _DEPS_OK:
        return None
    symbol = str(symbol).strip().upper()
    # Try the consolidated page first, then the standalone page.
    for suffix in ("consolidated/", ""):
        url = f"https://www.screener.in/company/{symbol}/{suffix}"
        try:
            r = requests.get(url, headers=_HEADERS, timeout=timeout)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            top = soup.find("ul", id="top-ratios")
            if not top:
                continue
            data = {}
            for li in top.find_all("li"):
                name_el = li.find("span", class_="name")
                value_el = li.find("span", class_="value")
                if not name_el or not value_el:
                    continue
                name = name_el.get_text(strip=True)
                value = " ".join(value_el.get_text(" ", strip=True).split())
                data[name] = value
            if data:
                data["_url"] = screener_url(symbol)
                return data
        except Exception:
            continue
    return None


# =============================================================================
# v2 PHASE 2 - FUNDAMENTALS LAYER (Sections 30-32)
# =============================================================================
# Loads a maintained bulk CSV (default data/fundamentals.csv) keyed by symbol,
# computes four transparent sub-scores (Quality / Growth / Balance-Sheet /
# Promoter) and a hard Compounder quality gate. Pure data + math: this module
# imports NOTHING from scanner.py or value.py (rule Section 46).
# -----------------------------------------------------------------------------
try:
    import pandas as pd
    _PD_OK = True
except Exception:
    _PD_OK = False

FINANCIAL_SECTORS = {"banking", "nbfc", "finance", "insurance",
                     "capital markets", "amc"}

# Canonical field -> accepted CSV header variants (case/space/punctuation-insensitive).
_FUND_ALIASES = {
    "rev_cagr_3y":        ["sales growth 3years", "sales growth 3y", "rev cagr 3y",
                           "revenue cagr 3y", "sales cagr 3y"],
    "rev_cagr_5y":        ["sales growth 5years", "sales growth 5y", "rev cagr 5y",
                           "revenue cagr 5y", "sales cagr 5y"],
    "pat_cagr_3y":        ["profit growth 3years", "profit growth 3y", "pat cagr 3y",
                           "profit cagr 3y", "net profit growth 3y"],
    "pat_cagr_5y":        ["profit growth 5years", "profit growth 5y", "pat cagr 5y",
                           "profit cagr 5y"],
    "roce_ttm":           ["roce", "roce %", "return on capital employed"],
    "roce_5y_avg":        ["roce 5y avg", "roce 5years", "average roce 5y", "roce 5yr"],
    "roe_ttm":            ["roe", "roe %", "return on equity"],
    "roe_5y_avg":         ["roe 5y avg", "roe 5years", "average roe 5y", "roe 5yr"],
    "opm_ttm":            ["opm", "opm %", "operating margin", "operating profit margin"],
    "opm_trend":          ["opm trend", "margin trend"],
    "debt_to_equity":     ["debt to equity", "debt / equity", "d/e", "de ratio"],
    "interest_coverage":  ["interest coverage", "interest coverage ratio"],
    "ocf_3y":             ["cash from operations 3y", "ocf 3y", "operating cash flow 3y",
                           "cfo 3y"],
    "ocf_to_pat":         ["ocf to pat", "ocf/pat", "cfo to pat", "cash conversion"],
    "promoter_holding":   ["promoter holding", "promoters holding", "promoter %"],
    "promoter_change_3y": ["promoter change 3y", "change in promoter holding 3y",
                           "promoter holding change 3y"],
    "pledge":             ["pledge", "pledged", "promoter pledge", "pledged %"],
    "pe_ttm":             ["pe", "p/e", "stock p/e", "price to earning"],
    "pb":                 ["pb", "p/b", "price to book", "price to book value"],
    "peg":                ["peg", "peg ratio"],
    "sales_5y":           ["sales", "revenue", "sales ttm"],
    "mcap":               ["market cap", "market capitalization", "mcap"],
    "div_yield":          ["dividend yield", "div yield", "yield"],
    "pe_5y_median":       ["pe 5y median", "median pe 5y", "5y median pe"],
    "isin":               ["isin", "isin code"],
    "sector":             ["sector", "industry"],
}


def _norm_key(s) -> str:
    out = []
    for ch in str(s).strip().lower():
        out.append(ch if ch.isalnum() or ch == " " else " ")
    return " ".join("".join(out).split())


def _to_num(v):
    """Coerce '18.2 %', '1,234', '₹45 Cr' -> float; blank/dash -> NaN."""
    if v is None:
        return float("nan")
    s = str(v).strip().replace(",", "").replace("%", "").replace("₹", "")
    s = s.replace("Cr", "").replace("cr", "").strip()
    if s in ("", "-", "--", "na", "n/a", "nan"):
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def load_fundamentals(path: str) -> dict:
    """Read a bulk fundamentals CSV keyed by symbol. Returns {SYMBOL: {field: val}}.
    Tolerant of header naming (uses the alias table). Returns {} on any failure."""
    if not _PD_OK or not path or not os.path.exists(path):
        return {}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}
    if df.empty:
        return {}
    # Build header -> canonical map.
    norm_cols = {_norm_key(c): c for c in df.columns}
    sym_col = None
    for cand in ("symbol", "nse symbol", "nse code", "ticker", "tradingsymbol"):
        if cand in norm_cols:
            sym_col = norm_cols[cand]
            break
    if sym_col is None:
        return {}
    field_col = {}
    for canon, aliases in _FUND_ALIASES.items():
        # Accept the canonical key itself as a header (so CSVs we WRITE round-trip),
        # then any of the human-friendly aliases.
        if _norm_key(canon) in norm_cols:
            field_col[canon] = norm_cols[_norm_key(canon)]
            continue
        for a in aliases:
            if _norm_key(a) in norm_cols:
                field_col[canon] = norm_cols[_norm_key(a)]
                break
    out = {}
    for _, row in df.iterrows():
        sym = str(row[sym_col]).strip().upper()
        if not sym or sym in ("NAN", ""):
            continue
        rec = {}
        for canon, col in field_col.items():
            if canon in ("opm_trend", "isin", "sector"):
                rec[canon] = str(row[col]).strip()
            else:
                rec[canon] = _to_num(row[col])
        out[sym] = rec
    return out


def _g(f, k, default=float("nan")):
    v = f.get(k, default)
    try:
        return default if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)
    except (TypeError, ValueError):
        return default


def _opm_trend_label(f) -> str:
    t = str(f.get("opm_trend", "")).strip().lower()
    if t in ("expanding", "up", "rising", "improving"):
        return "expanding"
    if t in ("contracting", "down", "falling", "declining"):
        return "contracting"
    return "stable"


def score_fundamentals(f: dict, sector: str = "") -> dict:
    """Return the four sub-scores (0-100) + bookkeeping flags. Missing fields
    award the neutral midpoint of their bucket and increment `partial`."""
    if not f:
        return {"Quality Score": float("nan"), "Growth Score": float("nan"),
                "Balance-Sheet Score": float("nan"), "Promoter Score": float("nan"),
                "Fundamentals Partial": 99, "BS Proxy": "No"}
    partial = 0
    is_fin = _norm_key(sector) in FINANCIAL_SECTORS

    def have(*keys):
        nonlocal partial
        ok = all(not math.isnan(_g(f, k)) for k in keys)
        if not ok:
            partial += 1
        return ok

    # ---- Quality Score (Section 31) ----
    q = 0
    roce = _g(f, "roce_ttm")
    if have("roce_ttm"):
        q += 25 if roce >= 20 else 18 if roce >= 15 else 10 if roce >= 12 else 0
    else:
        q += 12
    r5 = _g(f, "roce_5y_avg")
    if have("roce_5y_avg"):
        q += 15 if r5 >= 15 else 9 if r5 >= 12 else 0
    else:
        q += 7
    roe = _g(f, "roe_ttm")
    if have("roe_ttm"):
        q += 15 if roe >= 18 else 10 if roe >= 14 else 5 if roe >= 10 else 0
    else:
        q += 7
    ocf_pat = _g(f, "ocf_to_pat")
    if have("ocf_to_pat"):
        q += 15 if ocf_pat >= 0.8 else 9 if ocf_pat >= 0.6 else 4 if ocf_pat >= 0.4 else 0
    else:
        q += 7
    trend = _opm_trend_label(f)
    q += 15 if trend == "expanding" else 9 if trend == "stable" else 0
    ic = _g(f, "interest_coverage")
    if have("interest_coverage"):
        q += 15 if ic >= 5 else 9 if ic >= 3 else 4 if ic >= 1.5 else 0
    else:
        q += 7
    quality = min(100, q)

    # ---- Growth Score ----
    g = 0
    p3 = _g(f, "pat_cagr_3y")
    if have("pat_cagr_3y"):
        g += 30 if p3 >= 20 else 22 if p3 >= 15 else 12 if p3 >= 10 else 5 if p3 >= 5 else 0
    else:
        g += 12
    p5 = _g(f, "pat_cagr_5y")
    if have("pat_cagr_5y"):
        g += 20 if p5 >= 18 else 12 if p5 >= 12 else 6 if p5 >= 8 else 0
    else:
        g += 8
    rv3 = _g(f, "rev_cagr_3y")
    if have("rev_cagr_3y"):
        g += 25 if rv3 >= 18 else 17 if rv3 >= 12 else 9 if rv3 >= 8 else 4 if rv3 >= 5 else 0
    else:
        g += 10
    rv5 = _g(f, "rev_cagr_5y")
    if have("rev_cagr_5y"):
        g += 15 if rv5 >= 15 else 9 if rv5 >= 10 else 4 if rv5 >= 6 else 0
    else:
        g += 6
    if not math.isnan(p3) and not math.isnan(rv3) and p3 >= rv3:
        g += 10           # operating leverage / margin expansion
    growth = min(100, g)

    # ---- Balance-Sheet Score (financials exemption) ----
    b = 0
    bs_proxy = "No"
    if is_fin:
        bs_proxy = "Yes"
        b += 20           # neutral midpoint for D/E bucket (structural)
        partial += 0
    else:
        de = _g(f, "debt_to_equity")
        if have("debt_to_equity"):
            b += 40 if de <= 0.3 else 28 if de <= 0.6 else 15 if de <= 1.0 else 5 if de <= 1.5 else 0
        else:
            b += 20
    ic2 = _g(f, "interest_coverage")
    if not math.isnan(ic2):
        b += 30 if ic2 >= 6 else 18 if ic2 >= 3 else 6 if ic2 >= 1.5 else 0
    else:
        b += 15
    ocf = _g(f, "ocf_3y"); ocf_pat2 = _g(f, "ocf_to_pat")
    if not math.isnan(ocf):
        if ocf > 0 and (not math.isnan(ocf_pat2) and ocf_pat2 >= 0.6):
            b += 30
        elif ocf > 0:
            b += 15
    else:
        b += 15
    balance = min(100, b)

    # ---- Promoter / Governance Score ----
    p = 0
    ph = _g(f, "promoter_holding")
    if have("promoter_holding"):
        p += 40 if ph >= 50 else 28 if ph >= 40 else 15 if ph >= 30 else 5
    else:
        p += 20
    pc = _g(f, "promoter_change_3y")
    if have("promoter_change_3y"):
        p += 30 if pc >= 0 else 18 if pc >= -2 else 8 if pc >= -5 else 0
    else:
        p += 15
    pl = _g(f, "pledge")
    if have("pledge"):
        p += 30 if pl == 0 else 18 if pl <= 10 else 8 if pl <= 25 else 0
    else:
        p += 15
    promoter = min(100, p)

    return {
        "Quality Score": int(round(quality)),
        "Growth Score": int(round(growth)),
        "Balance-Sheet Score": int(round(balance)),
        "Promoter Score": int(round(promoter)),
        "Fundamentals Partial": int(partial),
        "BS Proxy": bs_proxy,
    }


# =============================================================================
# AUTO-FUNDAMENTALS from yfinance (free, cloud-safe, cached)
# =============================================================================
# Pulls the ratio fields yfinance carries into our canonical schema. yfinance
# does NOT have India-specific governance fields (promoter holding, pledge,
# ROCE 5Y, OPM trend), so those stay missing and the scorer marks them partial.
# This is enough to drive the Section 5A momentum quality gate and partial
# Quality/Growth/Valuation scores, but full "Compounder" classification still
# benefits from a Screener-enriched CSV.
# -----------------------------------------------------------------------------
import time
import pickle

try:
    import yfinance as yf
    _YF_OK = True
except Exception:
    _YF_OK = False


def _pct(v, scale=100.0):
    try:
        return float(v) * scale if v is not None else float("nan")
    except (TypeError, ValueError):
        return float("nan")


def _cagr_from_row(series_vals):
    """3Y CAGR from a list of annual values (newest first). Needs >=4 points."""
    try:
        vals = [float(x) for x in series_vals if x is not None and not pd.isna(x)]
    except Exception:
        return float("nan")
    if len(vals) < 4 or vals[3] <= 0:
        return float("nan")
    return (((vals[0] / vals[3]) ** (1.0 / 3)) - 1.0) * 100.0


def _row(df, *labels):
    """Pull a statement row by trying several label variants; newest-first list."""
    if df is None or getattr(df, "empty", True):
        return None
    for lab in labels:
        if lab in df.index:
            return list(df.loc[lab].values)
    return None


def fetch_one_yf(symbol: str, deep: bool = True) -> dict:
    """Fundamentals for ONE symbol from yfinance. Returns {} on failure."""
    if not _YF_OK:
        return {}
    sym = str(symbol).strip().upper()
    try:
        tk = yf.Ticker(f"{sym}.NS")
        info = tk.info or {}
    except Exception:
        return {}
    rec = {}
    m = {
        "roe_ttm": ("returnOnEquity", 100), "opm_ttm": ("operatingMargins", 100),
        "pe_ttm": ("trailingPE", 1), "pb": ("priceToBook", 1),
        "div_yield": ("dividendYield", 100), "mcap": ("marketCap", 1),
        "rev_cagr_3y": ("revenueGrowth", 100),   # YoY proxy (flagged)
        "pat_cagr_3y": ("earningsGrowth", 100),  # YoY proxy (flagged)
    }
    for canon, (key, scale) in m.items():
        v = _pct(info.get(key), scale) if scale == 100 else info.get(key)
        if v is not None and not (isinstance(v, float) and math.isnan(v)):
            rec[canon] = float(v)
    de = info.get("debtToEquity")          # yfinance gives this as a percent
    if de is not None:
        rec["debt_to_equity"] = float(de) / 100.0
    peg = info.get("trailingPegRatio") or info.get("pegRatio")
    if peg is not None:
        rec["peg"] = float(peg)
    # Deep: real multi-year CAGR + OCF/PAT + interest coverage from statements.
    if deep:
        try:
            inc = tk.income_stmt
            rev = _row(inc, "Total Revenue", "Operating Revenue")
            pat = _row(inc, "Net Income", "Net Income Common Stockholders")
            ebit = _row(inc, "EBIT", "Operating Income")
            intexp = _row(inc, "Interest Expense", "Interest Expense Non Operating")
            if rev:
                c = _cagr_from_row(rev)
                if not math.isnan(c):
                    rec["rev_cagr_3y"] = round(c, 1)
            if pat:
                c = _cagr_from_row(pat)
                if not math.isnan(c):
                    rec["pat_cagr_3y"] = round(c, 1)
            if ebit and intexp and intexp[0] not in (None, 0):
                rec["interest_coverage"] = round(abs(float(ebit[0]) / float(intexp[0])), 2)
            cf = tk.cashflow
            ocf = _row(cf, "Operating Cash Flow", "Total Cash From Operating Activities")
            if ocf and pat and pat[0] not in (None, 0):
                rec["ocf_to_pat"] = round(float(ocf[0]) / float(pat[0]), 2)
                rec["ocf_3y"] = round(sum(float(x) for x in ocf[:3] if x is not None), 0)
        except Exception:
            pass
    return rec


_CSV_FIELD_ORDER = [
    "rev_cagr_3y", "rev_cagr_5y", "pat_cagr_3y", "pat_cagr_5y", "roce_ttm",
    "roce_5y_avg", "roe_ttm", "roe_5y_avg", "opm_ttm", "opm_trend",
    "debt_to_equity", "interest_coverage", "ocf_3y", "ocf_to_pat",
    "promoter_holding", "promoter_change_3y", "pledge", "pe_ttm", "pb", "peg",
    "pe_5y_median", "div_yield", "sales_5y", "mcap", "isin", "sector",
]


def dict_to_df(fund: dict):
    """Convert {SYMBOL: {field: value}} into a tidy DataFrame keyed by `symbol`,
    using the canonical column names (which load_fundamentals now reads back)."""
    if not _PD_OK or not fund:
        return None
    rows = []
    for sym, rec in sorted(fund.items()):
        row = {"symbol": sym}
        for f in _CSV_FIELD_ORDER:
            if f in rec:
                row[f] = rec[f]
        rows.append(row)
    return pd.DataFrame(rows)


def write_fundamentals_csv(fund: dict, csv_path: str) -> int:
    """Write/merge the fundamentals dict to a CSV. Returns the row count."""
    df = dict_to_df(fund)
    if df is None or df.empty:
        return 0
    try:
        df.to_csv(csv_path, index=False)
    except Exception:
        return 0
    return len(df)


def load_yf_cache(cache_path: str) -> dict:
    """Return the whole on-disk yfinance cache as {SYMBOL: {field: value}}."""
    if not cache_path or not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "rb") as fh:
            cache = pickle.load(fh)
        return {s: {k: v for k, v in rec.items() if k != "_ts"}
                for s, rec in cache.items()}
    except Exception:
        return {}


def fetch_fundamentals_yf(symbols, cache_path: str = None, max_age_days: int = 7,
                          deep: bool = True, throttle: float = 0.25,
                          progress=None) -> dict:
    """Build {SYMBOL: {field: value}} from yfinance for many symbols, with an
    on-disk cache (only refreshes entries older than `max_age_days`)."""
    if not _YF_OK:
        return {}
    cache = {}
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as fh:
                cache = pickle.load(fh)
        except Exception:
            cache = {}
    now = time.time()
    fresh_cut = max_age_days * 86400
    out, total = {}, len(symbols)
    for i, sym in enumerate(symbols, start=1):
        s = str(sym).strip().upper()
        c = cache.get(s)
        if c and (now - c.get("_ts", 0)) < fresh_cut:
            out[s] = {k: v for k, v in c.items() if k != "_ts"}
        else:
            rec = fetch_one_yf(s, deep=deep)
            if rec:
                cache[s] = {**rec, "_ts": now}
                out[s] = rec
            if throttle:
                time.sleep(throttle)
        if progress:
            progress(i, total, s)
    if cache_path:
        try:
            with open(cache_path, "wb") as fh:
                pickle.dump(cache, fh)
        except Exception:
            pass
    return out


def fundamentals_quality_gate(scores: dict, f: dict) -> bool:
    """Section 32: hard gate a stock must pass to be eligible for 'Compounder'."""
    if not scores or scores.get("Fundamentals Partial", 99) > 2:
        return False
    pledge = _g(f, "pledge", 0)
    pc = _g(f, "promoter_change_3y", 0)
    return bool(
        _g(scores, "Quality Score") >= 60 and _g(scores, "Growth Score") >= 55
        and _g(scores, "Balance-Sheet Score") >= 55
        and _g(scores, "Promoter Score") >= 50
        and pledge <= 25 and pc >= -5)
