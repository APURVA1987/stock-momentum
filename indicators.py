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
