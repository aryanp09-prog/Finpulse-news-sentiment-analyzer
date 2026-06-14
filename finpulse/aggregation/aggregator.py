import sqlite3
from datetime import datetime, timezone, timedelta

import pandas as pd
import yfinance as yf
from finpulse.storage.db import DB_PATH
from config import yf_symbol, STOCKS

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
BASE_FUNDAMENTAL_WEIGHTS = {
    "pe_vs_industry": 30,
    "pb_vs_industry": 20,
    "roe": 30,
    "debt_to_equity": 20,
}

# Banks earn THROUGH debt (deposits/borrowings), so debt-to-equity is meaningless for them,
# and ROE is leverage-distorted. Use ROA (true efficiency) instead, and tilt toward quality
# (ROE + ROA) over cheapness (PE + PB) — a "cheap" bank is often cheap because of bad assets.
BANK_FUNDAMENTAL_WEIGHTS = {
    "pe_vs_industry": 20,
    "pb_vs_industry": 20,
    "roe": 30,
    "roa": 30,
}
FINANCIAL_SECTORS = {"Banking"}            # sectors that use the bank weight profile

FUNDAMENTAL_LABELS = {
    "pe_vs_industry": "PE vs industry",
    "pb_vs_industry": "PB vs industry",
    "roe": "ROE",
    "debt_to_equity": "Debt",
    "roa": "ROA",
}


def _to_float(value):
    """Best-effort numeric parser for provider fields that may arrive as strings or NA."""
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("%", "").replace("₹", "").replace("$", "")
        if cleaned.upper() in {"", "NA", "N/A", "NONE", "NULL", "--", "-"}:
            return None
        value = cleaned
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if pd.notna(num) else None


def _is_valid_number(value):
    """Return True when a field is a real numeric value, including zero."""
    return _to_float(value) is not None


def _clamp(value, low=0.0, high=100.0):
    """Clamp a score into the supported 0-100 range."""
    return max(low, min(high, value))


def _first_valid(*values):
    """Return the first parseable numeric value from a provider fallback list."""
    for value in values:
        parsed = _to_float(value)
        if parsed is not None:
            return parsed
    return None


def _parse_dividend_yield(raw_dividend, face_value, current_price, annual_dividend=None):
    """Return dividend yield as (decimal_fraction, display_string).

    yfinance's `dividendYield` is ALREADY a percentage (e.g. 0.93 == 0.93%, 1.75 == 1.75%),
    so use it directly. Only fall back to annual_dividend / current_price when it's missing.
    (`face_value` is accepted for backward compatibility but no longer needed.)
    """
    raw = _to_float(raw_dividend)
    price = _to_float(current_price)
    annual = _to_float(annual_dividend)

    if raw is not None:
        yield_pct = raw                                  # already a percent
    elif price and price > 0 and annual is not None and annual >= 0:
        yield_pct = annual / price * 100.0               # fallback: annual dividend / price
    else:
        yield_pct = None

    if yield_pct is None:
        return None, "NA"
    return yield_pct / 100.0, f"{yield_pct:.2f}%"


def load_fundamentals(ticker):
    """Load and normalize raw fundamentals from yfinance.

    Provider fields may be missing or arrive in different units. Dividend yield is
    normalized to actual market-price yield and exposed as both a decimal fraction
    and a ready-to-display string.
    """
    yf.set_tz_cache_location("D:/yf_cache")
    try:
        info = yf.Ticker(yf_symbol(ticker)).info
    except Exception:
        info = {}

    current_price = _first_valid(info.get("currentPrice"), info.get("regularMarketPrice"),
                                 info.get("previousClose"), info.get("regularMarketPreviousClose"))
    face_value = _to_float(info.get("faceValue"))
    dividend_rate = _first_valid(info.get("dividendYield"), info.get("trailingAnnualDividendYield"))
    annual_dividend = _first_valid(info.get("dividendRate"), info.get("trailingAnnualDividendRate"))
    dividend_yield, dividend_yield_display = _parse_dividend_yield(
        dividend_rate, face_value, current_price, annual_dividend)

    return {
        "market_cap": info.get("marketCap"),
        "current_price": current_price,
        "pe": info.get("trailingPE"),
        "pb": info.get("priceToBook"),
        "roe": info.get("returnOnEquity"),     # fraction, e.g. 0.18
        "roa": info.get("returnOnAssets"),     # fraction; the key efficiency metric for banks
        "debt": info.get("debtToEquity"),      # yfinance gives a %-style number, e.g. 120 == 1.2x
        "eps": info.get("trailingEps"),
        "dividend_yield": dividend_yield,
        "dividend_yield_display": dividend_yield_display,
        "annual_dividend": annual_dividend,
        "book_value": info.get("bookValue"),
        "face_value": face_value,
    }


def fundamental_score(ticker, peers):
    """Calculate a 1-100 fundamental score with dynamic weight redistribution.

    Relative metrics (PE, PB) are scored vs the sector-peer average; absolute (ROE, Debt).
    Only valid metrics are used. Their base weights are scaled proportionally so the
    available metrics always sum to exactly 100%; an NA debt metric for a bank therefore
    does not cap the best possible score at 80.

    Returns:
        (score|None, breakdown{name: (score_0_100, active_weight_pct)}, n_used, n_total, raw)
    """
    f = load_fundamentals(ticker)
    peer_funds = [load_fundamentals(p) for p in peers]

    def industry_avg(metric):
        vals = [_to_float(pf.get(metric)) for pf in peer_funds + [f] if _is_valid_number(pf.get(metric))]
        return sum(vals) / len(vals) if vals else None

    ind_pe, ind_pb = industry_avg("pe"), industry_avg("pb")
    f["industry_pe"] = ind_pe
    f["industry_pb"] = ind_pb

    # Banks use a different metric set + weights (ROA instead of debt; quality-tilted).
    is_financial = STOCKS.get(ticker, {}).get("sector") in FINANCIAL_SECTORS
    weights = BANK_FUNDAMENTAL_WEIGHTS if is_financial else BASE_FUNDAMENTAL_WEIGHTS

    raw_scores = {}
    pe = _to_float(f.get("pe"))
    pb = _to_float(f.get("pb"))
    roe = _to_float(f.get("roe"))

    if pe is not None and pe > 0 and ind_pe is not None and ind_pe > 0:
        raw_scores["pe_vs_industry"] = _clamp(50 - (pe / ind_pe - 1) * 100)
    if pb is not None and pb > 0 and ind_pb is not None and ind_pb > 0:
        raw_scores["pb_vs_industry"] = _clamp(50 - (pb / ind_pb - 1) * 100)
    if roe is not None:
        raw_scores["roe"] = _clamp(roe * 400)                # higher = better (0.25 ROE -> 100)
    if is_financial:
        roa = _to_float(f.get("roa"))
        if roa is not None:
            raw_scores["roa"] = _clamp(roa * 5000)           # banks: 2% ROA -> 100 (no leverage distortion)
    else:
        debt = _to_float(f.get("debt"))
        if debt is not None:
            raw_scores["debt_to_equity"] = _clamp(100 - debt / 2)  # lower = better (D/E 200% -> 0)

    total_valid_weight = sum(weights[key] for key in raw_scores)
    if len(raw_scores) < 2 or total_valid_weight <= 0:        # too little data to be meaningful
        comps = {FUNDAMENTAL_LABELS[key]: (score, 0.0) for key, score in raw_scores.items()}
        return None, comps, len(raw_scores), len(weights), f

    comps = {}
    weighted_score = 0.0
    for key, raw_score in raw_scores.items():
        active_weight = weights[key] / (total_valid_weight / 100.0)
        comps[FUNDAMENTAL_LABELS[key]] = (raw_score, active_weight)
        weighted_score += raw_score * (active_weight / 100.0)

    return _clamp(weighted_score), comps, len(raw_scores), len(weights), f


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

    strong, weak = fund_score >= 65, fund_score <= 40
    very_pos, pos = avg_sentiment > 0.35, avg_sentiment > 0.10
    neg = avg_sentiment < -0.10

    if strong:                                             # strong fundamentals -> fundamentals lead
        if neg:
            return "Overreaction", "Buy", ("Strong fundamentals but negative news - the market may be "
                                           "overreacting to bad news (possible value opportunity).")
        if pos:
            return "Momentum", "Strong Buy", "Strong fundamentals and positive news - the numbers and the mood agree."
        return "Quality", "Buy", ("Strong fundamentals with neutral news - a solid business with no "
                                  "negative catalyst.")
    if weak:                                               # weak fundamentals -> caution
        if very_pos:
            return "Hype Trap", "Sell / Caution", ("Weak fundamentals but very positive news - the price "
                                                   "may be driven by emotion, not the numbers.")
        if pos:
            return "Caution", "Reduce", ("Weak fundamentals propped up by positive news - limited support "
                                         "from the numbers.")
        return "Weak", "Sell", "Weak fundamentals and no positive catalyst - little support from either side."
    # mid-range fundamentals -> sentiment is the deciding edge
    if pos:
        return "Sentiment-led", "Lean Buy", "Average fundamentals; the edge here is positive news flow."
    if neg:
        return "Sentiment-led", "Lean Sell", "Average fundamentals; negative news flow is the main signal."
    return "Mixed", "Hold", "Average fundamentals and neutral news - no clear edge."
