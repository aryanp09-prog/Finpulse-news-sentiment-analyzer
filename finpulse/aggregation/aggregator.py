import sqlite3
from datetime import datetime, timezone, timedelta

import pandas as pd
import yfinance as yf
from finpulse.storage.db import DB_PATH
from config import yf_symbol

def load_sentiment(ticker):
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "Select timestamp, score FROM headlines where ticker = ?",
        conn,
        params = (ticker,),
    )
    conn.close()

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc = True,format="ISO8601")
    df = df.set_index("timestamp")
    return df 

def aggregate_sentiment(ticker, window = "1h"):
    df = load_sentiment(ticker)
    agg = df["score"].resample(window).agg(["mean", "count"])
    return agg

def load_price(ticker, period = "1mo"):
    yf.set_tz_cache_location("D:/yf_cache")
    sym = yf_symbol(ticker)
    df = yf.download(sym, period= period, interval = "1d")
    close = df["Close"][sym]
    close.index = close.index.tz_localize("UTC")
    close.name = "price"
    return close

def align(ticker):
    sentiment = aggregate_sentiment(ticker, "1D")["mean"].rename("sentiment")
    price = load_price(ticker)
    return pd.concat([sentiment, price], axis=1, join="inner")


def detect_divergence(sentiment, price_change_pct, sent_threshold=0.1, price_threshold=0.5):
    """Flag when news sentiment and price point in OPPOSITE directions.

    Returns a short description string if divergent, else None.
    Pure logic (no I/O) so it's easy to test and reuse.
    """
    if sentiment > sent_threshold and price_change_pct < -price_threshold:
        return "News positive, price falling"
    if sentiment < -sent_threshold and price_change_pct > price_threshold:
        return "News negative, price rising"
    return None


def recommendation(avg_sentiment, price_change_pct):
    """Rule-based EDUCATIONAL signal (not financial advice).

    Methodology (transparent + documented):
      sentiment_component = clamp(avg_sentiment / 0.5, -1..+1)   # +/-0.5 sentiment = full
      momentum_component  = clamp(price_change_pct / 10, -1..+1) # +/-10% move    = full
      score = 0.6 * sentiment_component + 0.4 * momentum_component   # sentiment-led
    Score is then mapped to five categories.

    Returns (label, score, components_dict).
    """
    s = max(-1.0, min(1.0, avg_sentiment / 0.5))
    m = max(-1.0, min(1.0, price_change_pct / 10.0))
    score = 0.6 * s + 0.4 * m
    if score >= 0.45:
        label = "Strong Buy"
    elif score >= 0.15:
        label = "Buy"
    elif score > -0.15:
        label = "Hold"
    elif score > -0.45:
        label = "Sell"
    else:
        label = "Strong Sell"
    return label, score, {"sentiment": s, "momentum": m}


def load_ohlc(ticker, days=30):
    """Daily Open/High/Low/Close for roughly the last `days` days (candlestick charts).

    Always daily candles — the timeframe only changes how far back we look.
    """
    yf.set_tz_cache_location("D:/yf_cache")
    sym = yf_symbol(ticker)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    df = yf.download(sym, start=start.strftime("%Y-%m-%d"),
                     end=(end + timedelta(days=1)).strftime("%Y-%m-%d"), interval="1d")
    if df.empty:                                   # yfinance throttled / no data
        return df
    ohlc = df.xs(sym, axis=1, level=1)             # drop the ticker level -> Open/High/Low/Close/Volume
    ohlc.index = ohlc.index.tz_localize("UTC")     # daily bars come back tz-naive
    return ohlc