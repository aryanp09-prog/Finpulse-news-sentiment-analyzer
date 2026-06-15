"""FinPulse dashboard — a 3-page Dash app.

Pages:
  /            Home      — market summary cards + top news
  /analytics   Analytics — sentiment line (left) + candlestick (right), time-aligned
  /news        News      — full table of processed headlines

Reads directly from the aggregator + storage layers (could equally hit the API).
Run from the repo root:  python -m finpulse.dashboard.app   ->  http://127.0.0.1:8050
"""

import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import Dash, dcc, html, dash_table, Input, Output, State, ctx, ALL, no_update
from dash.exceptions import PreventUpdate

from finpulse.storage.db import fetch_all
from finpulse.aggregation.aggregator import (aggregate_sentiment, load_ohlc, detect_divergence,
                                             recommendation, fundamental_score, verdict)
from fetch_news import ingest
from config import TICKERS, STOCKS, yf_symbol, currency, peers, logo_url, display_name

# One self-contained timeframe per option: candle size + a sensible lookback baked in.
# (Daily is the finest meaningful bucket — news isn't intraday.)
# Lookback in days. ALL timeframes use daily candles — only the window length changes.
TIMEFRAMES = {
    "Daily": 7,
    "Weekly": 21,
    "1 Month": 30,
    "3 Months": 90,
    "6 Months": 180,
    "1 Year": 365,
}
NEWS_TIMEFRAMES = {"All time": None, **TIMEFRAMES}

# Each ticker's peers (same sector), for the price-comparison chart.
PEERS = {t: STOCKS[t]["peers"] for t in TICKERS}

# Tickers grouped by sector (for the Sectors comparison page).
SECTORS = {}
for _t in TICKERS:
    SECTORS.setdefault(STOCKS[_t]["sector"], []).append(_t)

# ----------------------------------------------------------------------------- theme
BG = "#0e1117"
PANEL = "#161b22"
BORDER = "#2a3038"
TEXT = "#e6edf3"
MUTED = "#8b949e"
GREEN = "#3fb950"
RED = "#f85149"
ACCENT = "#58a6ff"
AMBER = "#d29922"

REC_COLORS = {
    "Strong Buy": "#2ea043", "Buy": "#3fb950", "Hold": "#d29922",
    "Sell": "#f0883e", "Strong Sell": "#f85149",
}

CARD_STYLE = {
    "background": PANEL, "border": f"1px solid {BORDER}", "borderRadius": "12px",
    "padding": "18px", "minWidth": "150px", "flex": "1",
}


# ----------------------------------------------------------------------------- logos
def logo_chip(ticker, size=34):
    """Company logo in a white rounded chip (white pad so dark logos stay visible)."""
    return html.Img(src=logo_url(ticker), alt=ticker, style={
        "width": f"{size}px", "height": f"{size}px", "borderRadius": "9px",
        "background": "#fff", "padding": "4px", "objectFit": "contain",
        "boxShadow": "0 1px 4px rgba(0,0,0,0.45)", "flexShrink": "0", "boxSizing": "border-box",
    })


def market_badge(ticker):
    return html.Span(STOCKS[ticker]["market"], style={
        "fontSize": "10px", "fontWeight": "700", "color": MUTED,
        "border": f"1px solid {BORDER}", "borderRadius": "6px", "padding": "1px 6px",
    })


def ticker_header(ticker):
    """Logo + company name + symbol + market badge — used on the analytics page (auto-updates)."""
    return html.Div([
        logo_chip(ticker, size=48),
        html.Div([
            html.Div(display_name(ticker), style={"fontSize": "20px", "fontWeight": "800"}),
            html.Div([
                html.Span(ticker, style={"color": ACCENT, "fontWeight": "700", "fontSize": "13px"}),
                html.Span(STOCKS[ticker]["sector"], style={"color": MUTED, "fontSize": "12px"}),
            ], style={"display": "flex", "gap": "10px", "alignItems": "center", "marginTop": "2px"}),
        ]),
        html.Div(market_badge(ticker), style={"marginLeft": "auto", "alignSelf": "flex-start"}),
    ], style={"display": "flex", "gap": "14px", "alignItems": "center", "marginBottom": "14px"})


# ---- Custom dropdowns built from our dark cards (native <details> toggle + click callbacks) ----
def _ticker_trigger_inner(ticker):
    """The selected-company card shown in the dropdown trigger (and updated on change)."""
    return html.Div([
        logo_chip(ticker, size=40),
        html.Div([
            html.Div(display_name(ticker), style={"fontSize": "18px", "fontWeight": "800", "color": TEXT}),
            html.Div([
                html.Span(ticker, style={"color": ACCENT, "fontWeight": "700", "fontSize": "12px"}),
                html.Span(STOCKS[ticker]["sector"], style={"color": MUTED, "fontSize": "12px"}),
            ], style={"display": "flex", "gap": "9px", "marginTop": "2px"}),
        ]),
        html.Div(market_badge(ticker), style={"marginLeft": "auto", "alignSelf": "center"}),
        html.Span("▾", className="fp-caret",
                  style={"color": MUTED, "fontSize": "15px", "marginLeft": "12px", "alignSelf": "center"}),
    ], style={"display": "flex", "gap": "12px", "alignItems": "center", "width": "100%"})


def _ticker_option_card(ticker):
    return html.Div([
        logo_chip(ticker, size=26),
        html.Div([
            html.Span(display_name(ticker), style={"fontWeight": "600", "color": TEXT, "fontSize": "13px"}),
            html.Span(ticker, style={"color": MUTED, "fontSize": "11px", "marginLeft": "7px"}),
        ]),
    ], id={"type": "tk-opt", "index": ticker}, n_clicks=0, className="fp-option",
       style={"display": "flex", "gap": "10px", "alignItems": "center"})


def ticker_selector(ticker):
    return html.Div([
        html.Div(_ticker_trigger_inner(ticker), id="ticker-trigger", n_clicks=0, className="fp-summary"),
        html.Div([_ticker_option_card(t) for t in TICKERS], id="ticker-options",
                 className="fp-options", style={"display": "none"}),
    ], className="fp-select")


def _tf_trigger_inner(tf):
    return html.Div([
        html.Div([
            html.Div("Timeframe", style={"fontSize": "10px", "color": MUTED, "fontWeight": "700",
                                         "letterSpacing": "0.5px", "textTransform": "uppercase"}),
            html.Div(tf, style={"fontSize": "17px", "fontWeight": "700", "color": TEXT, "marginTop": "3px"}),
        ]),
        html.Span("▾", className="fp-caret",
                  style={"color": MUTED, "fontSize": "15px", "marginLeft": "auto", "alignSelf": "center"}),
    ], style={"display": "flex", "alignItems": "center", "width": "100%"})


def _tf_option(tf):
    return html.Div(tf, id={"type": "tf-opt", "index": tf}, n_clicks=0, className="fp-option",
                    style={"color": TEXT, "fontSize": "13px", "fontWeight": "600"})


def timeframe_selector(tf):
    return html.Div([
        html.Div(_tf_trigger_inner(tf), id="tf-trigger", n_clicks=0, className="fp-summary"),
        html.Div([_tf_option(k) for k in TIMEFRAMES], id="tf-options",
                 className="fp-options", style={"display": "none"}),
    ], className="fp-select")


# ----------------------------------------------------------------------------- caching
# yfinance throttles if called too often. Cache results so the 60s auto-refresh and repeated
# page loads reuse data instead of hammering Yahoo. The cache is:
#   - PERSISTENT: dumped to disk so it survives restarts (run warmup.py to pre-fill it).
#   - STALE-TOLERANT: if a fetch fails (yfinance rate-limited -> None/empty), serve the last
#     known-good value instead of showing NA. Critical for live demos / presentations.
import os
import pickle

_CACHE_FILE = "D:/yf_cache/finpulse_cache.pkl"
# Multiply every TTL — bigger = fewer yfinance calls (less rate-limiting). Default 6x is
# presentation-safe; set CACHE_TTL_MULT=1 for freshest data, or higher for a long demo.
_TTL_MULT = float(os.environ.get("CACHE_TTL_MULT", "6"))
_CACHE = {}
try:
    if os.path.exists(_CACHE_FILE):
        with open(_CACHE_FILE, "rb") as _f:
            _CACHE = pickle.load(_f)
except Exception:
    _CACHE = {}


def _looks_empty(value):
    """True if a fetch result means 'no data' (so we should keep the previous cached value)."""
    if value is None:
        return True
    if isinstance(value, dict) and not value:
        return True
    if isinstance(value, tuple) and value and value[0] is None:   # fundamental_score(...) failed
        return True
    try:
        if hasattr(value, "empty") and value.empty:              # empty DataFrame / Series
            return True
    except Exception:
        pass
    return False


def _persist_cache():
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        tmp = _CACHE_FILE + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump(_CACHE, f)
        os.replace(tmp, _CACHE_FILE)        # atomic — never leave a half-written file
    except Exception:
        pass


def cached(key, ttl, fn):
    now = time.time()
    ttl = ttl * _TTL_MULT
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        value = fn()
    except Exception:
        value = None
    if _looks_empty(value) and hit is not None:
        return hit[1]                       # fetch failed -> serve last known-good (stale) value
    _CACHE[key] = (now, value)
    _persist_cache()
    return value


# ----------------------------------------------------------------------------- data helpers
def headlines_df():
    cols = ["id", "text", "ticker", "score", "label", "timestamp", "url"]
    df = pd.DataFrame(fetch_all(), columns=cols)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    return df.sort_values("timestamp", ascending=False)


def snapshot():
    out = []
    for t in TICKERS:
        agg = aggregate_sentiment(t, "1D")
        agg = agg[agg["count"] > 0]
        if agg.empty:
            continue
        last = agg.iloc[-1]
        out.append({"ticker": t, "mean": float(last["mean"]),
                    "count": int(last["count"]), "date": str(agg.index[-1].date())})
    return out


def latest_price_changes():
    """Latest close + day-over-day % change for every ticker (one batched download)."""
    yf.set_tz_cache_location("D:/yf_cache")
    syms = [yf_symbol(t) for t in TICKERS]
    data = yf.download(syms, period="5d", interval="1d", progress=False)["Close"]
    out = {}
    for t in TICKERS:
        s = data[yf_symbol(t)].dropna()
        if len(s) >= 2:
            last, prev = float(s.iloc[-1]), float(s.iloc[-2])
            out[t] = {"price": last, "pct": (last - prev) / prev * 100}
    return out


def market_mood():
    """Simplified fear/greed index (0-100). Blends 4 signals from the tracked tickers:
    breadth, momentum, stability (inverse volatility), and our own news sentiment.
    Heuristic + educational — NOT the real proprietary MMI."""
    yf.set_tz_cache_location("D:/yf_cache")
    syms = [yf_symbol(t) for t in TICKERS]
    data = yf.download(syms, period="3mo", interval="1d", progress=False)["Close"].dropna(how="all")
    if data.empty or len(data) < 2:                        # yfinance throttled -> neutral default
        return 50.0, {"Breadth": 50.0, "Momentum": 50.0, "Stability": 50.0, "Sentiment": 50.0}
    parts = {}

    last2 = data.tail(2)                                    # breadth: % of tickers up today
    parts["Breadth"] = float((last2.iloc[-1] > last2.iloc[-2]).mean()) * 100

    sma = data.rolling(50).mean().iloc[-1]                  # momentum: avg % above 50-day average
    pct_above = float(((data.iloc[-1] - sma) / sma).mean()) * 100
    parts["Momentum"] = min(100.0, max(0.0, 50 + pct_above * 5))

    vol = float(data.pct_change().tail(20).std().mean()) * 100   # stability: low recent vol = calm
    parts["Stability"] = max(0.0, 100 - min(100.0, vol * 25))

    snaps = snapshot()                                     # our news sentiment, [-1,1] -> [0,100]
    avg = sum(s["mean"] for s in snaps) / len(snaps) if snaps else 0.0
    parts["Sentiment"] = (avg + 1) / 2 * 100

    mmi = sum(parts.values()) / len(parts)
    return mmi, parts


def mood_label(value):
    if value < 25:
        return "Extreme Fear", RED, ("Markets may be oversold. Historically a contrarian window — "
                                     "sentiment this low has often preceded an upward turn.")
    if value < 45:
        return "Fear", AMBER, ("Investors are cautious. Whether fear deepens or reverses depends "
                               "on the trend, so watch the MMI's direction.")
    if value < 55:
        return "Neutral", MUTED, ("Sentiment is balanced — no strong fear or greed signal in the "
                                  "market right now.")
    if value < 75:
        return "Greed", GREEN, ("Investors are optimistic and momentum is positive, but watch for "
                                "overbought conditions as greed builds.")
    return "Extreme Greed", GREEN, ("Markets may be overbought. Extreme greed has often preceded a "
                                    "pullback — caution on opening fresh positions.")


# All zones, for the reference guide under the gauge.
MOOD_ZONES = [
    ("Extreme Fear", "0–25", RED, "Possibly oversold — historically a contrarian buying window."),
    ("Fear", "25–45", AMBER, "Cautious market; direction depends on the trend."),
    ("Neutral", "45–55", MUTED, "Balanced — no strong fear or greed signal."),
    ("Greed", "55–75", GREEN, "Optimistic momentum; watch for overbought conditions."),
    ("Extreme Greed", "75–100", GREEN, "Possibly overbought — often precedes a pullback."),
]


# ----------------------------------------------------------------------------- app
app = Dash(__name__, suppress_callback_exceptions=True)
app.title = "FinPulse"
app.index_string = """<!DOCTYPE html>
<html>
  <head>
    {%metas%}<title>{%title%}</title>{%favicon%}{%css%}
    <style>
      .news-row { transition: background 0.12s ease; }
      .news-row:hover { background: #1b212b; }
      ::-webkit-scrollbar { width: 10px; height: 10px; }
      ::-webkit-scrollbar-thumb { background: #2a3038; border-radius: 5px; }
      ::-webkit-scrollbar-track { background: transparent; }
    </style>
  </head>
  <body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body>
</html>"""


def navlink(label, href):
    return dcc.Link(label, href=href, style={
        "color": TEXT, "textDecoration": "none", "padding": "8px 16px",
        "borderRadius": "8px", "fontWeight": "600",
    })


navbar = html.Div([
    html.Div("📈 FinPulse", style={"fontSize": "20px", "fontWeight": "800", "color": ACCENT}),
    html.Div([navlink("Home", "/"), navlink("Analytics", "/analytics"),
              navlink("Sectors", "/sectors"), navlink("News", "/news")],
             style={"display": "flex", "gap": "8px"}),
], style={
    "display": "flex", "justifyContent": "space-between", "alignItems": "center",
    "padding": "14px 28px", "borderBottom": f"1px solid {BORDER}", "background": PANEL,
})

app.layout = html.Div([
    dcc.Location(id="url"),
    navbar,
    html.Div(id="page", style={"padding": "28px", "maxWidth": "1300px", "margin": "0 auto"}),
    html.Div("⚠️ Educational demonstration — not financial advice.",
             style={"textAlign": "center", "color": MUTED, "padding": "20px", "fontSize": "12px"}),
], style={"background": BG, "color": TEXT, "minHeight": "100vh",
          "fontFamily": "Segoe UI, system-ui, sans-serif"})


# ----------------------------------------------------------------------------- pages
def page_header(title, subtitle, sub_id=None):
    """Modern page header: gradient accent bar + gradient title + muted subtitle."""
    sub_kwargs = {"id": sub_id} if sub_id else {}
    return html.Div([
        html.Div(className="fp-accent-bar"),
        html.H1(title, className="fp-page-title"),
        html.P(subtitle, className="fp-page-sub", **sub_kwargs),
    ], style={"marginBottom": "22px"})


def build_home_content():
    snap = snapshot()
    prices = cached("prices", 300, latest_price_changes)
    cards = []
    for s in snap:
        t = s["ticker"]
        pc = prices.get(t)
        market = STOCKS[t]["market"]

        # sentiment label + colour
        if s["mean"] > 0.05:
            s_label, s_color = "Positive", GREEN
        elif s["mean"] < -0.05:
            s_label, s_color = "Negative", RED
        else:
            s_label, s_color = "Neutral", MUTED

        # price + day change
        if pc:
            pcolor = GREEN if pc["pct"] >= 0 else RED
            price_block = [
                html.Div(f"{currency(t)}{pc['price']:,.2f}",
                         style={"fontSize": "22px", "fontWeight": "800", "marginTop": "10px"}),
                html.Span(f"{pc['pct']:+.2f}% today",
                          style={"fontSize": "13px", "fontWeight": "700", "color": pcolor}),
            ]
            div = detect_divergence(s["mean"], pc["pct"])
        else:
            price_block = [html.Div("price n/a", style={"color": MUTED, "marginTop": "10px"})]
            div = None

        # disagreement (divergence) flag — clearly highlighted
        flag = []
        if div:
            flag = [html.Div(["⚠ Disagreement — ", html.Span(div, style={"fontWeight": "700"})],
                             style={"fontSize": "11px", "color": AMBER, "background": "#3a2d10",
                                    "border": f"1px solid {AMBER}", "borderRadius": "8px",
                                    "padding": "6px 8px", "marginTop": "12px", "lineHeight": "1.35"})]

        card = html.Div([
            html.Div([
                html.Div([
                    logo_chip(t, size=34),
                    html.Div([
                        html.Span(t, style={"fontSize": "16px", "fontWeight": "800", "display": "block"}),
                        html.Span(display_name(t), style={
                            "fontSize": "11px", "color": MUTED, "display": "block", "whiteSpace": "nowrap",
                            "overflow": "hidden", "textOverflow": "ellipsis", "maxWidth": "118px"}),
                    ]),
                ], style={"display": "flex", "gap": "10px", "alignItems": "center", "minWidth": 0}),
                market_badge(t),
            ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}),
            *price_block,
            html.Div([
                html.Span("Sentiment", style={"fontSize": "11px", "color": MUTED}),
                html.Span(f"{s_label}  {s['mean']:+.2f}",
                          style={"fontSize": "12px", "fontWeight": "700", "color": s_color}),
            ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center",
                      "marginTop": "12px", "paddingTop": "10px", "borderTop": f"1px solid {BORDER}"}),
            *flag,
        ], className="ticker-card", style={**CARD_STYLE, "minWidth": "unset", "width": "100%"})
        cards.append(dcc.Link(card, href=f"/analytics?ticker={t}",
                              style={"textDecoration": "none", "color": "inherit", "display": "flex"}))

    top = headlines_df().head(8)
    news_items = []
    for _, r in top.iterrows():
        color = GREEN if r["label"] == "positive" else RED if r["label"] == "negative" else MUTED
        row = html.Div([
            html.Span(r["ticker"], style={"color": ACCENT, "fontWeight": "700", "marginRight": "10px"}),
            html.Span(r["text"]),
            html.Span(r["label"].capitalize(), style={"color": color, "float": "right", "fontWeight": "700"}),
        ], style={"padding": "12px 0", "borderBottom": f"1px solid {BORDER}"})
        href = r["url"] if r["url"] else "#"
        news_items.append(html.A(row, href=href, target="_blank",
                                 style={"textDecoration": "none", "color": "inherit", "cursor": "pointer"}))

    mmi, parts = cached("mmi", 300, market_mood)
    mood_text, mood_color, mood_desc = mood_label(mmi)
    gauge = go.Figure(go.Indicator(
        mode="gauge+number", value=round(mmi, 1), number={"font": {"size": 38}},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": mood_color},
            "steps": [
                {"range": [0, 25], "color": "#5b1414"},
                {"range": [25, 45], "color": "#6b3b0a"},
                {"range": [45, 55], "color": "#2a3038"},
                {"range": [55, 75], "color": "#14532d"},
                {"range": [75, 100], "color": "#166534"},
            ],
        },
    ))
    gauge.update_layout(template="plotly_dark", paper_bgcolor=PANEL, height=240,
                        margin={"t": 20, "b": 10, "l": 30, "r": 30}, font={"color": TEXT})
    zone_guide = []
    for name, rng, col, desc in MOOD_ZONES:
        active = (name == mood_text)
        zone_guide.append(html.Div([
            html.Div(f"{name} ({rng})", style={"color": col, "fontWeight": "700", "fontSize": "12px"}),
            html.Div(desc, style={"color": MUTED, "fontSize": "11px", "lineHeight": "1.4"}),
        ], style={"flex": "1", "minWidth": "160px", "padding": "8px 10px", "borderRadius": "8px",
                  "background": "#1f2630" if active else "transparent",
                  "border": f"1px solid {col if active else 'transparent'}"}))

    mmi_panel = html.Div([
        html.Div([
            dcc.Graph(figure=gauge, config={"displayModeBar": False}, style={"flex": "2"}),
            html.Div([
                html.Div("Market Mood Index", style={"fontSize": "14px", "color": MUTED}),
                html.Div(mood_text, style={"fontSize": "28px", "fontWeight": "800", "color": mood_color}),
                html.Div(mood_desc, style={"fontSize": "12.5px", "color": TEXT, "marginTop": "6px",
                                           "lineHeight": "1.5", "maxWidth": "340px"}),
                html.Div([html.Div(f"{k}: {v:.0f}/100", style={"fontSize": "11px", "color": MUTED})
                          for k, v in parts.items()], style={"marginTop": "10px"}),
            ], style={"flex": "1", "display": "flex", "flexDirection": "column", "justifyContent": "center"}),
        ], style={"display": "flex", "gap": "20px", "alignItems": "center"}),
        html.Div(zone_guide, style={"display": "flex", "gap": "8px", "flexWrap": "wrap",
                                    "marginTop": "16px", "borderTop": f"1px solid {BORDER}", "paddingTop": "14px"}),
    ], style={**CARD_STYLE, "flex": "unset", "marginBottom": "28px"})

    return html.Div([
        mmi_panel,
        html.H2("Tracked Tickers", style={"marginBottom": "4px"}),
        html.P([html.Span("⚠ Disagreement", style={"color": AMBER, "fontWeight": "700"}),
                " = news sentiment and price are moving in opposite directions. Click any card to dig in."],
               style={"color": MUTED, "fontSize": "12px", "marginTop": 0, "marginBottom": "14px"}),
        html.Div(cards, style={"display": "grid",
                               "gridTemplateColumns": "repeat(auto-fill, minmax(215px, 1fr))",
                               "gap": "14px", "marginBottom": "44px"}),
        html.H2("Top Headlines", style={"marginTop": "12px", "marginBottom": "14px"}),
        html.Div(news_items, style={**CARD_STYLE, "flex": "unset"}),
    ])


def home_page():
    return html.Div([
        html.Div([
            page_header("Market Overview",
                        "Latest daily price move per ticker — sentiment shown underneath."),
            html.Button("🔄 Fetch latest news", id="fetch-btn", n_clicks=0, style={
                "background": ACCENT, "color": "#fff", "border": "none", "borderRadius": "8px",
                "padding": "10px 16px", "fontWeight": "700", "cursor": "pointer", "height": "fit-content",
            }),
        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}),
        html.Div(id="fetch-status", style={"color": MUTED, "fontSize": "13px",
                                            "minHeight": "18px", "marginBottom": "8px"}),
        dcc.Loading(html.Div(id="home-content", children=build_home_content())),
    ])


def analytics_page(default_ticker=None):
    ticker_value = default_ticker if default_ticker in TICKERS else TICKERS[0]
    return html.Div([
        page_header("Analytics", "Sentiment vs. price — aligned on the same time axis."),
        html.Div([
            html.Div(ticker_selector(ticker_value), style={"flex": "2", "minWidth": "320px"}),
            html.Div(timeframe_selector("Daily"), style={"flex": "1", "minWidth": "210px"}),
            # hidden value-holders — update_charts still reads these; the custom cards set them.
            dcc.Dropdown(id="ticker-dropdown", options=[{"label": t, "value": t} for t in TICKERS],
                         value=ticker_value, clearable=False, style={"display": "none"}),
            dcc.Dropdown(id="timeframe-dropdown", options=[{"label": k, "value": k} for k in TIMEFRAMES],
                         value="Daily", clearable=False, style={"display": "none"}),
        ], style={"display": "flex", "gap": "14px", "marginBottom": "12px",
                  "alignItems": "flex-start", "flexWrap": "wrap"}),
        html.P("Pick a company and timeframe. Auto-refreshes every 60s. "
               "Drag across either chart panel to pan/zoom; double-click to reset.",
               style={"color": MUTED, "fontSize": "12px", "marginBottom": "16px"}),
        dcc.Graph(id="combined-graph", style={"height": "720px"}),
        html.Div(_detail_hint(), id="sentiment-detail", style={"marginTop": "10px", "marginBottom": "8px"}),
        html.Div(id="price-comparison"),
        html.Div(id="news-summary"),
        dcc.Interval(id="tick", interval=60_000, n_intervals=0),   # redraw every 60 seconds
    ])


def _sentiment_pill(label):
    c = {"positive": GREEN, "negative": RED}.get(label, MUTED)
    return html.Span(label.capitalize(), style={
        "color": c, "border": f"1px solid {c}", "borderRadius": "20px",
        "padding": "3px 12px", "fontSize": "11px", "fontWeight": "700", "whiteSpace": "nowrap",
    })


# Stored timestamps are UTC; show each headline in ITS market's local time so it reads naturally.
MARKET_TZ = {"IN": ("Asia/Kolkata", "IST"), "US": ("America/New_York", "ET")}


def _local_time(ts, ticker):
    tz, label = MARKET_TZ.get(STOCKS.get(ticker, {}).get("market"), ("UTC", "UTC"))
    return ts.tz_convert(tz).strftime("%b %d, %Y · %H:%M") + f" {label}"


def _news_row(r):
    href = r["url"] if r["url"] else "#"
    when = _local_time(r["timestamp"], r["ticker"])
    return html.A([
        html.Span(r["ticker"], style={
            "background": "#1f2630", "color": ACCENT, "borderRadius": "6px", "padding": "4px 9px",
            "fontSize": "12px", "fontWeight": "700", "minWidth": "56px", "textAlign": "center",
            "whiteSpace": "nowrap",
        }),
        html.Div([
            html.Div(r["text"], style={"color": TEXT, "fontWeight": "500", "lineHeight": "1.4"}),
            html.Div(when, style={"color": MUTED, "fontSize": "11px", "marginTop": "4px"}),
        ], style={"flex": "1", "margin": "0 16px", "minWidth": 0}),
        _sentiment_pill(r["label"]),
    ], href=href, target="_blank", className="news-row", style={
        "display": "flex", "alignItems": "center", "padding": "14px 18px",
        "borderBottom": f"1px solid {BORDER}", "textDecoration": "none", "color": "inherit",
    })


# ---- Per-point transparency: which headlines produced a day's sentiment score ----
def _detail_hint(msg=None):
    return html.Div(
        msg or "💡 Click any point on the sentiment line above to see exactly which headlines were "
               "processed that day and how each one scored.",
        style={**CARD_STYLE, "flex": "unset", "color": MUTED, "fontSize": "13px"})


def _day_news_row(r):
    """A headline row showing its INDIVIDUAL score (so reviewers see what drove the day's average)."""
    href = r["url"] if r["url"] else "#"
    when = _local_time(r["timestamp"], r["ticker"])
    sc = float(r["score"])
    scolor = GREEN if sc > 0.05 else RED if sc < -0.05 else MUTED
    return html.A([
        html.Span(f"{sc:+.2f}", style={
            "background": "#1f2630", "color": scolor, "borderRadius": "6px", "padding": "4px 9px",
            "fontSize": "12px", "fontWeight": "800", "minWidth": "52px", "textAlign": "center",
            "whiteSpace": "nowrap",
        }),
        html.Div([
            html.Div(r["text"], style={"color": TEXT, "fontWeight": "500", "lineHeight": "1.4"}),
            html.Div(when, style={"color": MUTED, "fontSize": "11px", "marginTop": "4px"}),
        ], style={"flex": "1", "margin": "0 16px", "minWidth": 0}),
        _sentiment_pill(r["label"]),
    ], href=href, target="_blank", className="news-row", style={
        "display": "flex", "alignItems": "center", "padding": "14px 18px",
        "borderBottom": f"1px solid {BORDER}", "textDecoration": "none", "color": "inherit",
    })


def build_day_detail(ticker, day):
    """Panel listing every headline for `ticker` on UTC `day` (matches the chart's daily buckets)."""
    df = headlines_df()
    if df.empty:
        return _detail_hint()
    df = df[df["ticker"] == ticker]
    df = df[df["timestamp"].dt.date == day]      # timestamps are UTC -> same bucket as resample("1D")
    if df.empty:
        return _detail_hint(f"No headlines stored for {ticker} on {day:%b %d, %Y}.")
    df = df.sort_values("score", ascending=False)
    mean = float(df["score"].mean())
    mcolor = GREEN if mean > 0.05 else RED if mean < -0.05 else MUTED
    header = html.Div([
        html.Div([
            html.Span(f"{len(df)} headlines", style={"fontWeight": "800", "fontSize": "15px"}),
            html.Span(f"  processed on {day:%b %d, %Y}  (UTC)", style={"color": MUTED, "fontSize": "13px"}),
        ]),
        html.Div([
            html.Span("Day average  ", style={"color": MUTED, "fontSize": "12px"}),
            html.Span(f"{mean:+.2f}", style={"color": mcolor, "fontWeight": "800", "fontSize": "15px"}),
        ]),
    ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center",
              "padding": "14px 18px", "borderBottom": f"1px solid {BORDER}", "flexWrap": "wrap"})
    rows = [_day_news_row(r) for _, r in df.iterrows()]
    return html.Div([header, *rows], style={**CARD_STYLE, "flex": "unset", "padding": "0",
                                            "overflow": "hidden"})


def _filter_news_df(df, ticker="All", sentiment="All", timeframe="All time"):
    if ticker and ticker != "All":
        if ticker.startswith("sector:"):                       # whole sector -> all its stocks
            df = df[df["ticker"].isin(SECTORS.get(ticker.split(":", 1)[1], []))]
        else:
            df = df[df["ticker"] == ticker]
    if sentiment and sentiment != "All":
        df = df[df["label"] == sentiment]
    days = NEWS_TIMEFRAMES.get(timeframe)
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        df = df[df["timestamp"] >= cutoff]
    return df


def _news_count_text(ticker="All", sentiment="All", timeframe="All time"):
    df = _filter_news_df(headlines_df(), ticker, sentiment, timeframe)
    window = "all time" if timeframe == "All time" else f"the {timeframe} window"
    return f"{len(df)} processed headlines — {window}, newest first."


def build_news_feed(ticker="All", sentiment="All", timeframe="All time"):
    df = headlines_df()
    if df.empty:
        return html.Div("No news ingested yet — run fetch_news.py or click 'Fetch latest news'.",
                        style={"color": MUTED, "padding": "24px"})
    df = _filter_news_df(df, ticker, sentiment, timeframe)
    if df.empty:
        return html.Div("No headlines match this filter.", style={"color": MUTED, "padding": "24px"})
    rows = [_news_row(r) for _, r in df.head(150).iterrows()]
    return html.Div(rows, style={**CARD_STYLE, "flex": "unset", "padding": "0", "overflow": "hidden"})


_SENT_LABELS = {"All": "All sentiment", "positive": "Positive",
                "neutral": "Neutral", "negative": "Negative"}


def _label_for(kind, val):
    """Build the display label (component or text) for a filter value."""
    if kind == "sent":
        return _SENT_LABELS.get(val, val)
    if kind == "tf":
        return val
    # kind == "scope"
    if val == "All":
        return html.Span("All tickers", style={"fontWeight": "600"})
    if str(val).startswith("sector:"):
        s = val.split(":", 1)[1]
        return html.Span([
            html.Span(style={"width": "10px", "height": "10px", "borderRadius": "50%",
                             "background": SECTOR_COLOR.get(s, MUTED), "display": "inline-block",
                             "marginRight": "10px", "flexShrink": "0"}),
            html.Span(s, style={"fontWeight": "700"}),
            html.Span("sector", style={"opacity": "0.55", "marginLeft": "6px", "fontSize": "11px"}),
        ], style={"display": "flex", "alignItems": "center"})
    return html.Span([                                            # a ticker -> logo + name + symbol
        html.Img(src=logo_url(val), style={"width": "20px", "height": "20px", "borderRadius": "5px",
                 "background": "#fff", "padding": "2px", "objectFit": "contain", "marginRight": "10px",
                 "boxSizing": "border-box", "flexShrink": "0"}),
        html.Span(display_name(val), style={"fontWeight": "600"}),
        html.Span(val, style={"opacity": "0.55", "marginLeft": "7px", "fontSize": "12px"}),
    ], style={"display": "flex", "alignItems": "center"})


def custom_select(cid, kind, values, value, width=None):
    """A dark card dropdown (same look as Analytics) that drives a hidden dcc.Dropdown id=cid."""
    box = {"flex": "1", "minWidth": "250px"} if width is None else {"width": width}
    return html.Div([
        html.Div([
            html.Div(_label_for(kind, value), id=f"{cid}-label",
                     style={"display": "flex", "alignItems": "center", "flex": "1", "minWidth": 0}),
            html.Span("▾", className="fp-caret",
                      style={"marginLeft": "10px", "color": MUTED, "fontSize": "14px", "flexShrink": "0"}),
        ], id=f"{cid}-trigger", n_clicks=0, className="fp-summary"),
        html.Div([
            html.Div(_label_for(kind, v), id={"type": f"{cid}-opt", "val": v}, n_clicks=0,
                     className="fp-option")
            for v in values
        ], id=f"{cid}-opts", className="fp-options", style={"display": "none"}),
        dcc.Dropdown(id=cid, value=value, clearable=False, style={"display": "none"},
                     options=[{"label": str(v), "value": v} for v in values]),
    ], className="fp-select", style=box)


def news_page():
    scope_vals = ["All"] + [f"sector:{s}" for s in SECTORS] + list(TICKERS)
    return html.Div([
        page_header("All News", _news_count_text(), sub_id="news-count"),
        html.Div([
            custom_select("news-ticker", "scope", scope_vals, "All"),
            custom_select("news-sentiment", "sent", ["All", "positive", "neutral", "negative"],
                          "All", width="185px"),
            custom_select("news-timeframe", "tf", list(NEWS_TIMEFRAMES), "All time", width="170px"),
        ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "16px",
                  "alignItems": "flex-start"}),
        html.Div(id="news-list", children=build_news_feed()),
    ])


# ----------------------------------------------------------------------------- sectors
def sector_metrics():
    """Per-sector aggregates: avg news sentiment, avg fundamental score, avg day change, headlines."""
    snap = {s["ticker"]: s for s in snapshot()}
    prices = cached("prices", 300, latest_price_changes)
    df = headlines_df()
    counts = df["ticker"].value_counts().to_dict() if not df.empty else {}
    rows = []
    for sector, tickers in SECTORS.items():
        sents = [snap[t]["mean"] for t in tickers if t in snap]
        pcts = [prices[t]["pct"] for t in tickers if t in prices]
        funds = []
        for t in tickers:
            fs = cached(("fund", t), 600, lambda t=t: fundamental_score(t, peers(t)))[0]
            if fs is not None:
                funds.append(fs)
        rows.append({
            "sector": sector,
            "tickers": tickers,
            "sentiment": sum(sents) / len(sents) if sents else 0.0,
            "fundamentals": sum(funds) / len(funds) if funds else None,
            "pct": sum(pcts) / len(pcts) if pcts else None,
            "headlines": sum(counts.get(t, 0) for t in tickers),
        })
    return rows


def _sector_card(r):
    s_color = GREEN if r["sentiment"] > 0.05 else RED if r["sentiment"] < -0.05 else MUTED
    s_label = "Positive" if r["sentiment"] > 0.05 else "Negative" if r["sentiment"] < -0.05 else "Neutral"
    f_txt = f"{r['fundamentals']:.0f}/100" if r["fundamentals"] is not None else "NA"
    p_txt = f"{r['pct']:+.2f}%" if r["pct"] is not None else "NA"
    p_color = GREEN if (r["pct"] or 0) >= 0 else RED

    constituents = html.Div([
        dcc.Link([logo_chip(t, 22),
                  html.Span(t, style={"fontSize": "12px", "fontWeight": "700"})],
                 href=f"/analytics?ticker={t}",
                 style={"display": "flex", "alignItems": "center", "gap": "7px", "background": "#1f2630",
                        "borderRadius": "8px", "padding": "4px 9px 4px 5px", "textDecoration": "none",
                        "color": TEXT})
        for t in r["tickers"]
    ], style={"display": "flex", "gap": "8px", "flexWrap": "wrap", "margin": "12px 0 14px"})

    def metric(lbl, val, color=TEXT):
        return html.Div([
            html.Span(lbl, style={"color": MUTED, "fontSize": "12px"}),
            html.Span(val, style={"color": color, "fontWeight": "700", "fontSize": "13px"}),
        ], style={"display": "flex", "justifyContent": "space-between", "padding": "6px 0",
                  "borderTop": f"1px solid {BORDER}"})

    return html.Div([
        html.Div(r["sector"], style={"fontSize": "17px", "fontWeight": "800"}),
        constituents,
        metric("News sentiment", f"{s_label}  {r['sentiment']:+.2f}", s_color),
        metric("Avg fundamentals", f_txt),
        metric("Avg day change", p_txt, p_color),
        metric("Headlines", str(r["headlines"])),
    ], className="ticker-card", style={**CARD_STYLE, "minWidth": "unset"})


def sectors_page():
    metrics = sector_metrics()
    pts = [r for r in metrics if r["fundamentals"] is not None]
    fig = go.Figure()
    if pts:
        colors = [GREEN if r["sentiment"] > 0.05 else RED if r["sentiment"] < -0.05 else AMBER
                  for r in pts]
        fig.add_trace(go.Scatter(
            x=[r["fundamentals"] for r in pts], y=[r["sentiment"] for r in pts],
            mode="markers+text", text=[r["sector"] for r in pts], textposition="top center",
            textfont={"color": TEXT, "size": 12},
            marker={"size": 26, "color": colors, "line": {"color": "#fff", "width": 1}},
            customdata=[r["headlines"] for r in pts],
            hovertemplate="<b>%{text}</b><br>Avg fundamentals %{x:.0f}/100"
                          "<br>Avg sentiment %{y:+.2f}<br>%{customdata} headlines<extra></extra>",
        ))
    fig.add_vline(x=50, line_dash="dot", line_color=MUTED)
    fig.add_hline(y=0, line_dash="dot", line_color=MUTED)
    fig.update_layout(template="plotly_dark", paper_bgcolor=PANEL, plot_bgcolor=PANEL, height=440,
                      margin={"t": 30, "l": 60, "r": 30, "b": 50}, showlegend=False,
                      xaxis_title="Avg fundamental score (0-100)", yaxis_title="Avg news sentiment",
                      xaxis_range=[0, 100], yaxis_range=[-1, 1])

    cards = [_sector_card(r) for r in metrics]
    return html.Div([
        page_header("Sector Comparison",
                    "Each sector placed by its average fundamentals (x) and news sentiment (y). "
                    "Top-right = strong business + positive news; bottom-left = weak + disliked. "
                    "Click a stock chip to drill into its analytics."),
        dcc.Graph(figure=fig, config={"displayModeBar": False}, style={"marginBottom": "8px"}),
        html.Div(cards, style={"display": "grid",
                               "gridTemplateColumns": "repeat(auto-fill, minmax(265px, 1fr))",
                               "gap": "14px", "marginTop": "12px"}),
        # Sector performance comparison (% change over time) — pick any combination of sectors.
        html.Div([
            html.Div("Sector Performance — % change", style={"fontSize": "18px", "fontWeight": "800"}),
            html.P("Compare the average price performance of any sectors over a window — pick one, "
                   "two, or all of them. Each line is % change from the window's start.",
                   style={"color": MUTED, "fontSize": "12px", "marginTop": "4px", "marginBottom": "12px"}),
            html.Div([
                dcc.Dropdown(id="sector-cmp-select", multi=True, clearable=False,
                             options=[{"label": s, "value": s} for s in SECTORS],
                             value=list(SECTORS.keys()), placeholder="Select sectors to compare...",
                             style={"color": "#000", "flex": "1", "minWidth": "260px"}),
                dcc.Dropdown(id="sector-cmp-timeframe", clearable=False,
                             options=[{"label": k, "value": k} for k in TIMEFRAMES],
                             value="3 Months", style={"color": "#000", "width": "160px"}),
            ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap"}),
            html.Div(id="sector-cmp", style={"marginTop": "12px"}),
        ], style={**CARD_STYLE, "flex": "unset", "marginTop": "24px"}),
    ])


# ----------------------------------------------------------------------------- routing
def _ticker_from_search(search):
    if search:
        vals = parse_qs(search.lstrip("?")).get("ticker")
        if vals and vals[0] in TICKERS:
            return vals[0]
    return TICKERS[0]


@app.callback(Output("page", "children"), Input("url", "pathname"), Input("url", "search"))
def render(pathname, search):
    if pathname == "/analytics":
        return analytics_page(_ticker_from_search(search))
    if pathname == "/sectors":
        return sectors_page()
    if pathname == "/news":
        return news_page()
    return home_page()


@app.callback(
    Output("home-content", "children"),
    Output("fetch-status", "children"),
    Input("fetch-btn", "n_clicks"),
    prevent_initial_call=True,
)
def refresh_news(n_clicks):
    try:
        count = ingest()                                  # pull fresh headlines from NewsAPI
        msg = f"✓ Fetched {count} new headline(s)."
    except Exception as e:
        return build_home_content(), f"⚠ Fetch failed: {e}"
    return build_home_content(), msg


@app.callback(
    Output("news-count", "children"),
    Output("news-list", "children"),
    Input("news-ticker", "value"),
    Input("news-sentiment", "value"),
    Input("news-timeframe", "value"),
)
def filter_news(ticker, sentiment, timeframe):
    return _news_count_text(ticker, sentiment, timeframe), build_news_feed(ticker, sentiment, timeframe)


# ----------------------------------------------------------------------------- charts
def build_news_summary(ticker, ohlc, timeframe):
    """A plain-English directional read of timeframe-matched news for one ticker. Observational only."""
    df = headlines_df()
    df = df[df["ticker"] == ticker]
    if df.empty:
        return html.Div("No news stored for this ticker yet.",
                        style={**CARD_STYLE, "flex": "unset", "color": MUTED, "marginTop": "20px"})

    df = df[df["timestamp"] >= ohlc.index.min()]
    if df.empty:
        return html.Div(f"No headlines for {ticker} in the {timeframe} window.",
                        style={**CARD_STYLE, "flex": "unset", "color": MUTED, "marginTop": "20px"})

    recent = df
    total = len(recent)
    pos = int((recent["label"] == "positive").sum())
    neg = int((recent["label"] == "negative").sum())
    neu = int((recent["label"] == "neutral").sum())
    avg = float(recent["score"].mean())
    lean = "leaning positive" if avg > 0.05 else "leaning negative" if avg < -0.05 else "mixed"

    if len(ohlc) >= 2:
        first, last = float(ohlc["Close"].iloc[0]), float(ohlc["Close"].iloc[-1])
        price_move = (last - first) / first * 100
    else:
        price_move = 0.0

    news_up, news_down, price_up = avg > 0.05, avg < -0.05, price_move > 0
    if not (news_up or news_down):
        read = "News sentiment is mixed, so the news offers no clear directional signal right now."
    elif news_up and price_up:
        read = "News flow and price are both pointing up — sentiment is in line with the recent move."
    elif news_down and not price_up:
        read = "Negative news flow alongside a falling price — sentiment and price agree to the downside."
    elif news_up and not price_up:
        read = ("News has been mostly positive while price fell — a divergence. The news may not yet "
                "be reflected in the price, or it was already priced in.")
    else:
        read = "News has been mostly negative while price rose — a divergence worth watching."

    # --- fundamentals + verdict (fundamentals x sentiment) ---
    fscore, fcomps, fused, ftotal, fraw = cached(
        ("fund", ticker), 600, lambda: fundamental_score(ticker, peers(ticker)))
    v_label, v_action, v_expl = verdict(fscore, avg)
    v_color = GREEN if "Buy" in v_action else RED if "Sell" in v_action else AMBER

    fscore_txt = f"{fscore:.0f}/100" if fscore is not None else "Insufficient data"

    def _fmt_num(value, suffix="", decimals=2):
        if value is None:
            return "NA"
        return f"{value:,.{decimals}f}{suffix}"

    def _fmt_money(value):
        if value is None:
            return "NA"
        cur = currency(ticker)
        if cur == "₹":
            return f"₹{value / 10_000_000:,.0f}Cr"
        if abs(value) >= 1_000_000_000_000:
            return f"{cur}{value / 1_000_000_000_000:,.2f}T"
        if abs(value) >= 1_000_000_000:
            return f"{cur}{value / 1_000_000_000:,.2f}B"
        if abs(value) >= 1_000_000:
            return f"{cur}{value / 1_000_000:,.2f}M"
        return f"{cur}{value:,.0f}"

    def _fund_row(label, value, hint=None):
        label_bits = [html.Span(label, style={"color": MUTED})]
        if hint:
            label_bits.append(html.Span("i", title=hint, style={
                "display": "inline-flex", "alignItems": "center", "justifyContent": "center",
                "width": "14px", "height": "14px", "marginLeft": "6px", "borderRadius": "50%",
                "border": f"1px solid {MUTED}", "color": MUTED, "fontSize": "9px", "fontWeight": "800",
            }))
        return html.Div([
            html.Div(label_bits, style={"display": "flex", "alignItems": "center"}),
            html.Div(value, style={"fontWeight": "800", "color": TEXT, "textAlign": "right"}),
        ], style={"display": "grid", "gridTemplateColumns": "1fr auto", "gap": "16px",
                  "alignItems": "center", "padding": "11px 0", "borderBottom": f"1px solid {BORDER}"})

    def _score_chip(name, score_weight):
        score, weight = score_weight
        color = GREEN if score >= 65 else RED if score < 40 else AMBER
        return html.Div([
            html.Div(name, style={"fontSize": "11px", "fontWeight": "800", "color": TEXT}),
            html.Div([
                html.Div(style={"width": f"{score:.0f}%", "height": "100%", "background": color,
                                "borderRadius": "999px"}),
            ], style={"height": "5px", "background": BG, "borderRadius": "999px", "overflow": "hidden",
                      "margin": "7px 0"}),
            html.Div(f"{score:.0f}/100 · weight {weight}%",
                     style={"fontSize": "10px", "color": MUTED}),
        ], style={"background": BG, "border": f"1px solid {BORDER}", "borderRadius": "8px",
                  "padding": "10px 12px"})

    fund_metrics = [
        ("Market Cap", _fmt_money(fraw.get("market_cap")), None),
        ("ROE", _fmt_num(fraw.get("roe") * 100 if fraw.get("roe") is not None else None, "%", 2),
         "Return on equity; higher is generally better."),
        ("ROA", _fmt_num(fraw.get("roa") * 100 if fraw.get("roa") is not None else None, "%", 2),
         "Return on assets; the key efficiency metric for banks (undistorted by leverage)."),
        ("P/E Ratio (TTM)", _fmt_num(fraw.get("pe"), "", 2), "Trailing price-to-earnings ratio."),
        ("EPS (TTM)", _fmt_num(fraw.get("eps"), "", 2), "Trailing earnings per share."),
        ("P/B Ratio", _fmt_num(fraw.get("pb"), "", 2), "Price-to-book ratio."),
        ("Dividend Yield", fraw.get("dividend_yield_display", "NA"), None),
        ("Industry P/E", _fmt_num(fraw.get("industry_pe"), "", 2), "Average P/E across configured peers."),
        ("Book Value", _fmt_num(fraw.get("book_value"), "", 2), None),
        ("Debt to Equity", _fmt_num(fraw.get("debt") / 100 if fraw.get("debt") is not None else None, "", 2), None),
        ("Face Value", _fmt_num(fraw.get("face_value"), "", 2), None),
    ]

    fscore_disp = f"{fscore:.0f}/100" if fscore is not None else "N/A"
    verdict_panel = html.Div([
        html.Div([
            html.Div("VERDICT  —  Fundamentals + Sentiment",
                     style={"fontSize": "11px", "color": MUTED, "letterSpacing": "1px"}),
            html.Div(f"{v_label}  →  {v_action}",
                     style={"fontSize": "26px", "fontWeight": "800", "color": v_color}),
            html.Div(v_expl, style={"fontSize": "12.5px", "color": MUTED, "marginTop": "6px",
                                    "lineHeight": "1.5", "maxWidth": "560px"}),
        ], style={"flex": "1"}),
        html.Div([
            html.Div("BASED ON", style={"fontSize": "10px", "color": MUTED, "letterSpacing": "1px",
                                        "marginBottom": "6px"}),
            html.Div([html.Span("Fundamental score  ", style={"color": MUTED, "fontSize": "12px"}),
                      html.Span(fscore_disp, style={"fontWeight": "800", "fontSize": "15px"})],
                     style={"marginBottom": "3px"}),
            html.Div([html.Span("News sentiment  ", style={"color": MUTED, "fontSize": "12px"}),
                      html.Span(f"{avg:+.2f}", style={"fontWeight": "800", "fontSize": "15px"})]),
        ], style={"textAlign": "right", "minWidth": "175px"}),
    ], style={"background": "#1f2630", "border": f"1px solid {v_color}", "borderRadius": "10px",
              "padding": "14px 18px", "marginBottom": "12px", "display": "flex",
              "justifyContent": "space-between", "alignItems": "center", "gap": "20px"})

    score_pct = max(0, min(100, fscore or 0))
    score_color = GREEN if fscore is not None and fscore >= 65 else RED if fscore is not None and fscore < 40 else AMBER
    fund_panel = html.Div([
        html.Div([
            html.Div([
                html.Span("Fundamentals", style={"fontSize": "18px", "fontWeight": "800"}),
                html.Span("i", title="Fundamental data comes from yfinance; missing fields are shown as NA.",
                          style={"display": "inline-flex", "alignItems": "center", "justifyContent": "center",
                                 "width": "16px", "height": "16px", "marginLeft": "8px", "borderRadius": "50%",
                                 "border": f"1px solid {MUTED}", "color": MUTED,
                                 "fontSize": "10px", "fontWeight": "800"}),
            ], style={"display": "flex", "alignItems": "center"}),
            html.Div(f"Score {fscore_txt}",
                     style={"fontSize": "13px", "fontWeight": "800", "color": score_color,
                            "background": BG, "border": f"1px solid {score_color}",
                            "borderRadius": "999px", "padding": "5px 12px"}),
        ], style={"display": "flex", "justifyContent": "space-between", "gap": "12px",
                  "alignItems": "center", "marginBottom": "12px"}),
        html.Div([
            html.Div(style={"width": f"{score_pct:.0f}%", "height": "100%", "background": score_color,
                            "borderRadius": "999px"}),
        ], style={"height": "7px", "background": BG, "borderRadius": "999px",
                  "overflow": "hidden", "marginBottom": "18px"}),
        html.Div([_fund_row(label, value, hint) for label, value, hint in fund_metrics],
                 style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(320px, 1fr))",
                        "columnGap": "42px", "rowGap": "0", "marginBottom": "16px"}),
        html.Div([
            html.Div("Score breakdown", style={"fontSize": "12px", "fontWeight": "800",
                                               "color": MUTED, "letterSpacing": "0.4px",
                                               "textTransform": "uppercase", "marginBottom": "10px"}),
            html.Div([_score_chip(name, score_weight) for name, score_weight in fcomps.items()],
                     style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(170px, 1fr))",
                            "gap": "10px"}),
            html.Div(f"Based on {fused} of {ftotal} score metrics"
                     + (f": {', '.join(fcomps.keys())}" if fcomps else ""),
                     style={"fontSize": "11px", "color": MUTED, "marginTop": "10px"}),
        ], style={"borderTop": f"1px solid {BORDER}", "paddingTop": "14px"}),
    ], style={"background": "#1f2630", "border": f"1px solid {BORDER}", "borderRadius": "10px",
              "padding": "20px 24px", "marginBottom": "12px"})

    most_pos = recent.loc[recent["score"].idxmax()]
    most_neg = recent.loc[recent["score"].idxmin()]

    def link(row):
        return html.A(row["text"], href=row["url"] if row["url"] else "#", target="_blank",
                      style={"color": ACCENT, "textDecoration": "none"})

    return html.Div([
        html.H3(f"Analysis & Signal — {ticker}", style={"marginTop": 0}),
        html.Div(f"{total} headlines in the {timeframe} window · {pos} positive · {neg} negative · {neu} neutral · "
                 f"avg sentiment {avg:+.2f} ({lean})", style={"color": MUTED, "marginBottom": "4px"}),
        html.Div(f"Price over this window: {price_move:+.1f}%", style={"color": MUTED, "marginBottom": "12px"}),
        verdict_panel,
        fund_panel,
        html.Div(read, style={"color": MUTED, "fontSize": "12.5px", "lineHeight": "1.5", "marginBottom": "14px"}),
        html.Div([html.Span("Most positive: ", style={"color": GREEN, "fontWeight": "700"}), link(most_pos)],
                 style={"marginBottom": "6px"}),
        html.Div([html.Span("Most negative: ", style={"color": RED, "fontWeight": "700"}), link(most_neg)]),
        html.Div("Rule-based educational signal — combines the fundamental score with news sentiment "
                 "(see the verdict box). NOT buy/sell/hold financial advice.",
                 style={"color": MUTED, "fontSize": "11px", "marginTop": "14px", "fontStyle": "italic"}),
    ], style={**CARD_STYLE, "flex": "unset", "marginTop": "20px"})


def build_price_comparison(ticker, days):
    """Normalized %-change line chart of the ticker vs its peers (Tickertape-style)."""
    symbols = [ticker] + PEERS.get(ticker, [])      # internal tickers
    yfs = [yf_symbol(s) for s in symbols]           # their yfinance symbols
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(days, 30))     # at least a month so the comparison is meaningful

    def _dl():
        yf.set_tz_cache_location("D:/yf_cache")
        return yf.download(yfs, start=start.strftime("%Y-%m-%d"),
                           end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
                           interval="1d", progress=False)["Close"]

    data = cached(("cmp", tuple(yfs), days), 300, _dl)
    if data is None or len(data) == 0:
        return html.Div("Comparison data temporarily unavailable.",
                        style={**CARD_STYLE, "flex": "unset", "color": MUTED, "marginTop": "20px"})

    colors = [ACCENT, "#7ee787", "#f778ba", "#ffa657"]
    fig = go.Figure()
    for i, sym in enumerate(symbols):
        ysym = yf_symbol(sym)
        col = data[ysym] if ysym in getattr(data, "columns", []) else data
        s = col.dropna()
        if s.empty:
            continue
        norm = (s / s.iloc[0] - 1) * 100
        fig.add_trace(go.Scatter(x=norm.index, y=norm, mode="lines", name=sym,
                                 line={"color": colors[i % len(colors)], "width": 2}))
    fig.add_hline(y=0, line_dash="dot", line_color=MUTED)
    fig.update_layout(template="plotly_dark", paper_bgcolor=PANEL, plot_bgcolor=PANEL, height=320,
                      margin={"t": 44, "l": 50, "r": 20, "b": 36},
                      title=f"{ticker} vs peers — % change", yaxis_title="% change",
                      legend={"orientation": "h", "y": 1.12, "x": 0})
    return html.Div([
        html.Div("Each line is % change from the window's start, so differently-priced stocks compare fairly.",
                 style={"color": MUTED, "fontSize": "12px", "marginBottom": "6px"}),
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
    ], style={**CARD_STYLE, "flex": "unset", "marginTop": "20px"})


# Stable colour per sector so a sector keeps its colour across any selection.
SECTOR_PALETTE = [ACCENT, "#7ee787", "#f778ba", "#ffa657", "#a371f7", "#56d4dd"]
SECTOR_COLOR = {s: SECTOR_PALETTE[i % len(SECTOR_PALETTE)] for i, s in enumerate(SECTORS)}


def build_sector_comparison(selected, days):
    """Normalized %-change line per selected sector (avg of the sector's stocks, from window start)."""
    selected = [s for s in (selected or []) if s in SECTORS]
    if not selected:
        return html.Div("Select one or more sectors to compare.",
                        style={"color": MUTED, "fontSize": "13px", "padding": "16px 0"})
    needed = [t for s in selected for t in SECTORS[s]]
    yfs = [yf_symbol(t) for t in needed]
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(days, 30))

    def _dl():
        yf.set_tz_cache_location("D:/yf_cache")
        return yf.download(yfs, start=start.strftime("%Y-%m-%d"),
                           end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
                           interval="1d", progress=False)["Close"]

    data = cached(("seccmp", tuple(sorted(yfs)), days), 300, _dl)
    if data is None or len(data) == 0:
        return html.Div("Sector comparison data temporarily unavailable (yfinance rate-limited).",
                        style={"color": MUTED, "padding": "16px 0"})

    fig = go.Figure()
    for sector in selected:
        norms = []
        for t in SECTORS[sector]:
            ysym = yf_symbol(t)
            col = data[ysym] if (hasattr(data, "columns") and ysym in data.columns) else data
            s = col.dropna()
            if not s.empty:
                norms.append((s / s.iloc[0] - 1) * 100)
        if not norms:
            continue
        avg = pd.concat(norms, axis=1).mean(axis=1)      # equal-weight the sector's stocks
        fig.add_trace(go.Scatter(x=avg.index, y=avg, mode="lines", name=sector,
                                 line={"color": SECTOR_COLOR[sector], "width": 2}))
    fig.add_hline(y=0, line_dash="dot", line_color=MUTED)
    fig.update_layout(template="plotly_dark", paper_bgcolor=PANEL, plot_bgcolor=PANEL, height=360,
                      margin={"t": 30, "l": 50, "r": 20, "b": 36}, yaxis_title="% change",
                      legend={"orientation": "h", "y": 1.13, "x": 0})
    return dcc.Graph(figure=fig, config={"displayModeBar": False})


# ---- Custom dropdown wiring -------------------------------------------------
# One callback per selector handles BOTH opening/closing (trigger click) and selecting (option
# click). Open/close is controlled fully via the panel's style so it can't desync like <details>.
# Selecting sets the hidden value-holder that update_charts reads, so the charts can't break.
@app.callback(
    Output("ticker-options", "style"),
    Output("ticker-trigger", "className"),
    Output("ticker-dropdown", "value"),
    Input("ticker-trigger", "n_clicks"),
    Input({"type": "tk-opt", "index": ALL}, "n_clicks"),
    State("ticker-options", "style"),
    prevent_initial_call=True,
)
def ticker_dropdown(_trig, opt_clicks, style):
    style = dict(style or {})
    trig = ctx.triggered_id
    if trig == "ticker-trigger":                                   # toggle open/close
        opening = style.get("display") != "block"
        style["display"] = "block" if opening else "none"
        return style, ("fp-summary fp-open" if opening else "fp-summary"), no_update
    if isinstance(trig, dict) and any(opt_clicks):                 # an option was picked
        style["display"] = "none"
        return style, "fp-summary", trig["index"]
    raise PreventUpdate


@app.callback(
    Output("tf-options", "style"),
    Output("tf-trigger", "className"),
    Output("timeframe-dropdown", "value"),
    Input("tf-trigger", "n_clicks"),
    Input({"type": "tf-opt", "index": ALL}, "n_clicks"),
    State("tf-options", "style"),
    prevent_initial_call=True,
)
def timeframe_dropdown(_trig, opt_clicks, style):
    style = dict(style or {})
    trig = ctx.triggered_id
    if trig == "tf-trigger":
        opening = style.get("display") != "block"
        style["display"] = "block" if opening else "none"
        return style, ("fp-summary fp-open" if opening else "fp-summary"), no_update
    if isinstance(trig, dict) and any(opt_clicks):
        style["display"] = "none"
        return style, "fp-summary", trig["index"]
    raise PreventUpdate


@app.callback(
    Output("sentiment-detail", "children"),
    Input("combined-graph", "clickData"),
    Input("ticker-dropdown", "value"),
)
def show_day_detail(click, ticker):
    # Reset to the hint when the ticker changes; otherwise show the clicked day's headlines.
    if ctx.triggered_id == "ticker-dropdown" or not click:
        return _detail_hint()
    pts = click.get("points", [])
    if not pts:
        return _detail_hint()
    pt = pts[0]
    if pt.get("curveNumber") != 0:   # curve 0 = sentiment line; 1 = candlestick
        return _detail_hint("Click a point on the SENTIMENT line (top panel) to see its headlines.")
    day = pd.to_datetime(pt["x"]).date()
    return build_day_detail(ticker, day)


@app.callback(Output("ticker-trigger", "children"), Input("ticker-dropdown", "value"))
def update_ticker_trigger(ticker):
    return _ticker_trigger_inner(ticker)


@app.callback(Output("tf-trigger", "children"), Input("timeframe-dropdown", "value"))
def update_tf_trigger(tf):
    return _tf_trigger_inner(tf)


@app.callback(
    Output("sector-cmp", "children"),
    Input("sector-cmp-select", "value"),
    Input("sector-cmp-timeframe", "value"),
)
def update_sector_cmp(sectors, timeframe):
    return build_sector_comparison(sectors, TIMEFRAMES.get(timeframe, 30))


def _register_custom_select(cid, kind):
    """Wire a custom_select: trigger toggles the panel; clicking an option sets the value + label."""
    @app.callback(
        Output(f"{cid}-opts", "style"),
        Output(f"{cid}-trigger", "className"),
        Output(cid, "value"),
        Output(f"{cid}-label", "children"),
        Input(f"{cid}-trigger", "n_clicks"),
        Input({"type": f"{cid}-opt", "val": ALL}, "n_clicks"),
        State(f"{cid}-opts", "style"),
        prevent_initial_call=True,
    )
    def _dd(_trig, opt_clicks, style, _cid=cid, _kind=kind):
        style = dict(style or {})
        trig = ctx.triggered_id
        if trig == f"{_cid}-trigger":                              # open/close
            opening = style.get("display") != "block"
            style["display"] = "block" if opening else "none"
            return style, ("fp-summary fp-open" if opening else "fp-summary"), no_update, no_update
        if isinstance(trig, dict) and any(opt_clicks):            # picked an option
            style["display"] = "none"
            return style, "fp-summary", trig["val"], _label_for(_kind, trig["val"])
        raise PreventUpdate


_register_custom_select("news-ticker", "scope")
_register_custom_select("news-sentiment", "sent")
_register_custom_select("news-timeframe", "tf")


@app.callback(
    Output("combined-graph", "figure"),
    Output("price-comparison", "children"),
    Output("news-summary", "children"),
    Input("ticker-dropdown", "value"),
    Input("timeframe-dropdown", "value"),
    Input("tick", "n_intervals"),       # fires every 60s -> re-pull + redraw
)
def update_charts(ticker, timeframe, _tick):
    days = TIMEFRAMES[timeframe]
    ohlc = cached(("ohlc", ticker, days), 300, lambda: load_ohlc(ticker, days=days))

    if ohlc is None or ohlc.empty:                  # yfinance throttled / no data
        _CACHE.pop(("ohlc", ticker, days), None)    # don't keep a failed result cached
        msg = "Price data temporarily unavailable (yfinance is rate-limiting). Try again in a moment."
        empty = go.Figure()
        empty.update_layout(template="plotly_dark", paper_bgcolor=BG, plot_bgcolor=BG, height=720,
                            annotations=[{"text": msg, "showarrow": False, "font": {"color": MUTED, "size": 14}}])
        note = html.Div(msg, style={**CARD_STYLE, "flex": "unset", "color": MUTED, "marginTop": "20px"})
        return empty, html.Div(), note

    sent = aggregate_sentiment(ticker, "1D")        # always daily buckets
    sent = sent[sent.index >= ohlc.index.min()]     # trim sentiment to the timeframe

    # two stacked panels sharing ONE x-axis -> zoom/pan syncs and they always align
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06, row_heights=[0.4, 0.6],
        subplot_titles=(f"{ticker} — Aggregated Sentiment", f"{ticker} — Price (OHLC)"),
    )
    fig.add_trace(go.Scatter(
        x=sent.index, y=sent["mean"], mode="lines+markers",
        line={"color": ACCENT, "width": 2}, connectgaps=True, name="sentiment",
        marker={"size": 8}, customdata=sent["count"],
        hovertemplate="%{x|%b %d, %Y}<br>Avg sentiment %{y:+.2f}"
                      "<br>%{customdata} headlines · click to view<extra></extra>",
    ), row=1, col=1)
    fig.add_hline(y=0, line_dash="dot", line_color=MUTED, row=1, col=1)
    fig.add_trace(go.Candlestick(
        x=ohlc.index, open=ohlc["Open"], high=ohlc["High"], low=ohlc["Low"], close=ohlc["Close"],
        increasing_line_color=GREEN, decreasing_line_color=RED, name="price",
    ), row=2, col=1)

    fig.update_layout(
        template="plotly_dark", paper_bgcolor=BG, plot_bgcolor=BG, height=720,
        showlegend=False, margin={"t": 40, "l": 55, "r": 20, "b": 40},
        xaxis2_rangeslider_visible=False,
    )
    fig.update_yaxes(title_text="Sentiment", range=[-1, 1], row=1, col=1)
    fig.update_yaxes(title_text=f"Price ({currency(ticker)})", row=2, col=1)
    return fig, build_price_comparison(ticker, days), build_news_summary(ticker, ohlc, timeframe)


if __name__ == "__main__":
    # use_reloader=False avoids the Windows "WinError 10038 (not a socket)" spam
    # from Werkzeug's file-watcher. Restart manually after code edits.
    app.run(debug=True, use_reloader=False, port=8050)
