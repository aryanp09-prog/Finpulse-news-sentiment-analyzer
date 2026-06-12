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


# --------------------------------------------------------------------------- fundamentals
def load_fundamentals(ticker):
    """Raw fundamentals from yfinance .info (fields may be missing -> None)."""
    yf.set_tz_cache_location("D:/yf_cache")
    info = yf.Ticker(yf_symbol(ticker)).info
    return {
        "pe": info.get("trailingPE"),
        "pb": info.get("priceToBook"),
        "roe": info.get("returnOnEquity"),     # fraction, e.g. 0.18
        "debt": info.get("debtToEquity"),      # yfinance gives a %-style number, e.g. 120 == 1.2x
        "eps": info.get("trailingEps"),
    }


def fundamental_score(ticker, peers):
    """1-100 fundamental score, graceful with missing data.

    Relative metrics (PE, PB) are scored vs the sector-peer average; absolute (ROE, Debt).
    Only available metrics are used and their weights are re-normalised to sum to 100%.
    Returns (score|None, breakdown{name: (0-100, weight)}, n_used, n_total).
    """
    f = load_fundamentals(ticker)
    peer_funds = [load_fundamentals(p) for p in peers]

    def industry_avg(metric):
        vals = [pf[metric] for pf in peer_funds + [f] if pf.get(metric)]
        return sum(vals) / len(vals) if vals else None

    ind_pe, ind_pb = industry_avg("pe"), industry_avg("pb")
    comps = {}                                              # name -> (score 0-100, weight)
    if f["pe"] and ind_pe:                                  # cheaper than peers = better
        comps["PE vs industry"] = (max(0.0, min(100.0, 50 - (f["pe"] / ind_pe - 1) * 100)), 30)
    if f["pb"] and ind_pb:                                  # cheaper than peers = better
        comps["PB vs industry"] = (max(0.0, min(100.0, 50 - (f["pb"] / ind_pb - 1) * 100)), 20)
    if f["roe"] is not None:                                # higher = better (0.25 ROE -> 100)
        comps["ROE"] = (max(0.0, min(100.0, f["roe"] * 400)), 30)
    if f["debt"] is not None:                               # lower = better (D/E 200% -> 0)
        comps["Debt"] = (max(0.0, min(100.0, 100 - f["debt"] / 2)), 20)

    if len(comps) < 2:                                      # too little data to be meaningful
        return None, comps, len(comps), 4, f
    total_w = sum(w for _, w in comps.values())
    score = sum(s * w for s, w in comps.values()) / total_w
    return score, comps, len(comps), 4, f


def verdict(fund_score, avg_sentiment):
    """Combine fundamentals (0-100) and news sentiment (-1..+1) into a verdict.

    Educational signal, NOT financial advice. Returns (verdict, action, explanation).
    """
    if fund_score is None:                                  # sentiment-only fallback
        if avg_sentiment > 0.15:
            return "Sentiment-led", "Lean Buy", "Fundamentals unavailable - signal from news sentiment only."
        if avg_sentiment < -0.15:
            return "Sentiment-led", "Lean Sell", "Fundamentals unavailable - signal from news sentiment only."
        return "Sentiment-led", "Hold", "Fundamentals unavailable and news sentiment is neutral."

    strong, weak = fund_score >= 60, fund_score <= 40
    pos, neg, very_pos = avg_sentiment > 0.15, avg_sentiment < -0.15, avg_sentiment > 0.35

    if strong and neg:
        return "Overreaction", "Buy", ("Strong fundamentals but negative news - the market may be "
                                       "overreacting to bad news (possible value opportunity).")
    if weak and very_pos:
        return "Hype Trap", "Sell / Caution", ("Weak fundamentals but very positive news - the price "
                                                "may be driven by emotion, not the numbers.")
    if strong and pos:
        return "Momentum", "Strong Buy", "Strong fundamentals and positive news - the numbers and the mood agree."
    if weak and neg:
        return "Weak", "Sell", "Weak fundamentals and negative news - little support from either side."
    return "Mixed", "Hold", "Fundamentals and sentiment don't point the same way - no clear edge."