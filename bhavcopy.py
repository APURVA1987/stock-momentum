# bhavcopy.py
# -----------------------------------------------------------------------------
# OPTIONAL, LOCAL-ONLY data helper: download NSE's official end-of-day "bhavcopy"
# (one file containing OHLCV for EVERY listed equity) and return the latest day.
#
# IMPORTANT (for non-coders):
# - NSE blocks data-centre IPs, so this only works when you run the app on your
#   OWN PC (`streamlit run app.py`), NOT on Streamlit Cloud.
# - It is used in HYBRID mode: Yahoo provides the multi-year history; bhavcopy
#   just supplies the most recent official trading day on top of it.
# - Everything fails GRACEFULLY (returns None) so the app never breaks.
# -----------------------------------------------------------------------------

import io
import zipfile
import datetime as dt

try:
    import requests
    import pandas as pd
    _OK = True
except Exception:
    _OK = False

# New UDiFF bhavcopy (NSE format since July 2024).
_UDIFF = ("https://nsearchives.nseindia.com/content/cm/"
          "BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip")
# Old format (pre-July 2024) as a fallback.
_OLD = ("https://archives.nseindia.com/content/historical/EQUITIES/"
        "{yyyy}/{mon}/cm{dd}{mon}{yyyy}bhav.csv.zip")

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _session():
    """A requests session that first visits nseindia.com to pick up cookies
    (NSE refuses direct file requests without them)."""
    s = requests.Session()
    s.headers.update(_HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=10)
    except Exception:
        pass
    return s


def _parse(df, the_date):
    """Normalise either the new (UDiFF) or old bhavcopy layout into a frame
    indexed by symbol with Open/High/Low/Close/Volume + Date."""
    cols = set(df.columns)
    if {"TckrSymb", "ClsPric"} <= cols:                 # new UDiFF format
        s = df["SctySrs"].astype(str).str.strip() if "SctySrs" in cols else "EQ"
        df = df[s == "EQ"]
        out = pd.DataFrame({
            "Symbol": df["TckrSymb"].astype(str).str.strip(),
            "Open": df["OpnPric"], "High": df["HghPric"], "Low": df["LwPric"],
            "Close": df["ClsPric"], "Volume": df["TtlTradgVol"]})
    elif {"SYMBOL", "CLOSE"} <= cols:                   # old format
        df.columns = [c.strip() for c in df.columns]
        df = df[df["SERIES"].astype(str).str.strip() == "EQ"]
        out = pd.DataFrame({
            "Symbol": df["SYMBOL"].astype(str).str.strip(),
            "Open": df["OPEN"], "High": df["HIGH"], "Low": df["LOW"],
            "Close": df["CLOSE"], "Volume": df["TOTTRDQTY"]})
    else:
        return None
    out = out.dropna(subset=["Close"]).set_index("Symbol")
    out["Date"] = pd.Timestamp(the_date)
    return out


def fetch_bhavcopy(date=None, max_back: int = 7):
    """Return the most recent available bhavcopy (today or up to `max_back` days
    earlier, to skip weekends/holidays) as a DataFrame indexed by symbol, or None."""
    if not _OK:
        return None
    s = _session()
    d = date or dt.date.today()
    for _ in range(max_back + 1):
        ymd = d.strftime("%Y%m%d")
        urls = [
            _UDIFF.format(ymd=ymd),
            _OLD.format(yyyy=d.strftime("%Y"), mon=d.strftime("%b").upper(), dd=d.strftime("%d")),
        ]
        for url in urls:
            try:
                r = s.get(url, timeout=20)
                if r.status_code == 200 and r.content[:2] == b"PK":   # a real zip
                    z = zipfile.ZipFile(io.BytesIO(r.content))
                    df = pd.read_csv(z.open(z.namelist()[0]))
                    parsed = _parse(df, d)
                    if parsed is not None and not parsed.empty:
                        return parsed
            except Exception:
                pass
        d -= dt.timedelta(days=1)
    return None
