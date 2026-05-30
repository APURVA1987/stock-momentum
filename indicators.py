# indicators.py
# -----------------------------------------------------------------------------
# This file contains small, reusable functions that calculate technical
# indicators (moving averages, RSI, slopes, etc.) from a price DataFrame.
#
# NOTE FOR NON-CODERS:
# - A "DataFrame" is just a table of data (like an Excel sheet) from the
#   pandas library.
# - Each function below takes a price series (a column of numbers) and returns
#   a calculated result.
# - You normally do NOT need to edit this file. It is the "math engine".
# -----------------------------------------------------------------------------

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple Moving Average (e.g. 20 DMA, 50 DMA, 200 DMA).

    window = number of days to average over.
    """
    return series.rolling(window=window, min_periods=window).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (RSI), calculated manually with pandas.

    We calculate RSI by hand so we do NOT depend on the 'ta' or 'pandas-ta'
    libraries (those sometimes fail to install). RSI ranges from 0 to 100.
    Above 55 usually means strong momentum.
    """
    delta = series.diff()

    # Separate gains (up moves) and losses (down moves).
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    # Wilder's smoothing (the standard way to average RSI).
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    # Avoid divide-by-zero: where avg_loss is 0, RSI is 100.
    rs = avg_gain / avg_loss
    rsi_values = 100 - (100 / (1 + rs))
    rsi_values = rsi_values.where(avg_loss != 0, 100.0)
    return rsi_values


def slope_pct(series: pd.Series, lookback: int = 30) -> float:
    """Percentage slope of a line over the last `lookback` days.

    Used to check if the 200 DMA is rising or falling.
    We fit a straight line to the last `lookback` points and express the
    slope as a percentage of the average value (so it is comparable across
    stocks of different prices). Positive = rising, Negative = falling.
    """
    data = series.dropna().tail(lookback)
    if len(data) < 2:
        return np.nan

    x = np.arange(len(data))
    y = data.values
    # np.polyfit with degree 1 gives [slope, intercept].
    slope = np.polyfit(x, y, 1)[0]
    avg = np.mean(y)
    if avg == 0:
        return np.nan
    # Convert "price units per day" into a % of the average price.
    return (slope / avg) * 100.0


def pct_change_over(series: pd.Series, lookback: int = 20) -> float:
    """Return % over the last `lookback` trading days.

    Example: 20-day return = (close today / close 20 days ago - 1) * 100.
    """
    data = series.dropna()
    if len(data) <= lookback:
        return np.nan
    latest = data.iloc[-1]
    past = data.iloc[-1 - lookback]
    if past == 0:
        return np.nan
    return (latest / past - 1.0) * 100.0


# -----------------------------------------------------------------------------
# The functions below are calculated MANUALLY (no 'ta'/'pandas-ta' library) so
# the app never has dependency/install problems. They use Wilder's smoothing,
# which is the industry-standard way to average ATR/ADX.
# -----------------------------------------------------------------------------
def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range = the biggest of:
      (today's high - today's low),
      |today's high - yesterday's close|,
      |today's low  - yesterday's close|.
    It measures how much a stock moved in a day, including gaps.
    """
    prev_close = close.shift(1)
    ranges = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range (ATR) = average volatility over `period` days.
    We use it to size a sensible, volatility-aware stop loss.
    """
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average Directional Index (ADX) = trend STRENGTH (not direction).
    ADX > 20 = a real trend is present; ADX > 25 = strong trend.
    Calculated manually using the standard +DI / -DI / DX method.
    """
    up_move = high.diff()
    down_move = -low.diff()

    # Positive directional movement when up_move dominates, else 0.
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move

    tr = true_range(high, low, close)
    atr_ = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean() / atr_)

    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    return dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def close_position(open_=None, high=None, low=None, close=None) -> float:
    """Candle close strength for the LATEST candle (single values, not series):
        (Close - Low) / (High - Low)
    Above 0.75 = closed strongly near the day's high (bullish).
    Below 0.50 = weak close. Returns 0.5 if the candle has no range.
    """
    rng = (high - low)
    if rng is None or rng == 0:
        return 0.5
    return float((close - low) / rng)


# -----------------------------------------------------------------------------
# v2: Volume / accumulation primitives (On-Balance Volume, Accumulation/Dist).
# These are calculated manually (no extra library) and feed the Spring and
# Volume-Accumulation engines in scanner.py.
# -----------------------------------------------------------------------------
def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume: running sum of signed volume.
    Up-day adds today's volume, down-day subtracts it. A rising OBV while price
    is flat = quiet accumulation (smart money buying the base)."""
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume).cumsum()


def ad_line(high: pd.Series, low: pd.Series, close: pd.Series,
            volume: pd.Series) -> pd.Series:
    """Accumulation/Distribution line: cumulative money-flow-volume.
    Multiplier = ((close-low) - (high-close)) / (high-low), in [-1, +1]."""
    rng = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / rng
    mfm = mfm.fillna(0.0)
    return (mfm * volume).cumsum()


def linslope(series: pd.Series, lookback: int) -> float:
    """Raw linear-fit slope (price units per day) of the last `lookback` points.
    Used for OBV / A-D slope where we care about sign and relative magnitude."""
    data = series.dropna().tail(lookback)
    if len(data) < 2:
        return np.nan
    x = np.arange(len(data))
    return float(np.polyfit(x, data.values, 1)[0])
