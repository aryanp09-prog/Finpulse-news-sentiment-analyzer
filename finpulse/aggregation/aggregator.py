import sqlite3
import pandas as pd
import yfinance as yf
from finpulse.storage.db import DB_PATH

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
    df = yf.download(ticker, period= period, interval = "1d")
    close = df["Close"][ticker]
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


def load_ohlc(ticker, period="1mo", interval="1d"):
    """Open/High/Low/Close/Volume for a ticker (for candlestick charts)."""
    yf.set_tz_cache_location("D:/yf_cache")
    df = yf.download(ticker, period=period, interval=interval)
    ohlc = df.xs(ticker, axis=1, level=1)          # drop the ticker level -> Open/High/Low/Close/Volume
    if ohlc.index.tz is None:
        ohlc.index = ohlc.index.tz_localize("UTC")   # daily bars come back tz-naive
    else:
        ohlc.index = ohlc.index.tz_convert("UTC")    # intraday bars come back tz-aware
    return ohlc