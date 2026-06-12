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
from dash import Dash, dcc, html, dash_table, Input, Output

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


# ----------------------------------------------------------------------------- caching
# yfinance throttles if called too often. Cache results briefly so the 60s auto-refresh
# and repeated page loads reuse data instead of hammering Yahoo (prices are ~15min delayed anyway).
_CACHE = {}


def cached(key, ttl, fn):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = fn()
    _CACHE[key] = (now, value)
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
    html.Div([navlink("Home", "/"), navlink("Analytics", "/analytics"), navlink("News", "/news")],
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
                               "gap": "14px", "marginBottom": "32px"}),
        html.H2("Top Headlines"),
        html.Div(news_items, style={**CARD_STYLE, "flex": "unset"}),
    ])


def home_page():
    return html.Div([
        html.Div([
            html.Div([
                html.H2("Market Overview", style={"marginBottom": "4px"}),
                html.P("Latest daily price move per ticker — sentiment shown underneath.",
                       style={"color": MUTED, "marginTop": 0}),
            ]),
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
        html.H2("Analytics"),
        html.P("Sentiment vs. price — aligned on the same time axis.", style={"color": MUTED}),
        html.Div([
            dcc.Dropdown(
                id="ticker-dropdown", options=[{"label": t, "value": t} for t in TICKERS],
                value=ticker_value, clearable=False,
                style={"width": "180px", "color": "#000"},
            ),
            dcc.Dropdown(
                id="timeframe-dropdown", options=[{"label": k, "value": k} for k in TIMEFRAMES],
                value="Daily", clearable=False,
                style={"width": "140px", "color": "#000"},
            ),
        ], style={"display": "flex", "gap": "12px", "marginBottom": "10px"}),
        html.P("Choose a timeframe. Auto-refreshes every 60s. "
               "Drag across either panel to pan/zoom; double-click to reset.",
               style={"color": MUTED, "fontSize": "12px"}),
        html.Div(ticker_header(ticker_value), id="ticker-logo",
                 style={**CARD_STYLE, "flex": "unset", "padding": "14px 18px", "marginBottom": "14px"}),
        dcc.Graph(id="combined-graph", style={"height": "720px"}),
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


def _filter_news_df(df, ticker="All", sentiment="All", timeframe="All time"):
    if ticker and ticker != "All":
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


def news_page():
    drop = {"width": "190px", "color": "#000"}
    return html.Div([
        html.H2("All News"),
        html.P(_news_count_text(), id="news-count", style={"color": MUTED}),
        html.Div([
            dcc.Dropdown(id="news-ticker", clearable=False, value="All", style=drop,
                         options=[{"label": "All tickers", "value": "All"}]
                                 + [{"label": t, "value": t} for t in TICKERS]),
            dcc.Dropdown(id="news-sentiment", clearable=False, value="All", style=drop,
                         options=[{"label": "All sentiment", "value": "All"},
                                  {"label": "Positive", "value": "positive"},
                                  {"label": "Neutral", "value": "neutral"},
                                  {"label": "Negative", "value": "negative"}]),
            dcc.Dropdown(id="news-timeframe", clearable=False, value="All time", style=drop,
                         options=[{"label": k, "value": k} for k in NEWS_TIMEFRAMES]),
        ], style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="news-list", children=build_news_feed()),
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


@app.callback(Output("ticker-logo", "children"), Input("ticker-dropdown", "value"))
def update_ticker_header(ticker):
    # Separate from update_charts so the logo header swaps instantly and can't break the charts.
    return ticker_header(ticker)


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
