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
