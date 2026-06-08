"""FinPulse dashboard — a 3-page Dash app.

Pages:
  /            Home      — market summary cards + top news
  /analytics   Analytics — sentiment line (left) + candlestick (right), time-aligned
  /news        News      — full table of processed headlines

Reads directly from the aggregator + storage layers (could equally hit the API).
Run from the repo root:  python -m finpulse.dashboard.app   ->  http://127.0.0.1:8050
"""

from urllib.parse import parse_qs

import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import Dash, dcc, html, dash_table, Input, Output

from finpulse.storage.db import fetch_all
from finpulse.aggregation.aggregator import aggregate_sentiment, load_ohlc
from finpulse.sentiment.ticker_tagger import ALIASES

TICKERS = sorted(set(ALIASES.values()))

# One self-contained timeframe per option: candle size + a sensible lookback baked in.
# (Daily is the finest meaningful bucket — news isn't intraday.)
TIMEFRAMES = {
    "Daily": {"window": "1D", "interval": "1d", "period": "1mo"},
    "Weekly": {"window": "1W", "interval": "1wk", "period": "1y"},
    "1 Month": {"window": "1D", "interval": "1d", "period": "1mo"},
    "3 Months": {"window": "1D", "interval": "1d", "period": "3mo"},
    "6 Months": {"window": "1D", "interval": "1d", "period": "6mo"},
    "1 Year": {"window": "1D", "interval": "1d", "period": "1y"},
}

# ----------------------------------------------------------------------------- theme
BG = "#0e1117"
PANEL = "#161b22"
BORDER = "#2a3038"
TEXT = "#e6edf3"
MUTED = "#8b949e"
GREEN = "#3fb950"
RED = "#f85149"
ACCENT = "#58a6ff"

CARD_STYLE = {
    "background": PANEL, "border": f"1px solid {BORDER}", "borderRadius": "12px",
    "padding": "18px", "minWidth": "150px", "flex": "1",
}


# ----------------------------------------------------------------------------- data helpers
def headlines_df():
    cols = ["id", "text", "ticker", "score", "label", "timestamp"]
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
    data = yf.download(TICKERS, period="5d", interval="1d", progress=False)["Close"]
    out = {}
    for t in TICKERS:
        s = data[t].dropna()
        if len(s) >= 2:
            last, prev = float(s.iloc[-1]), float(s.iloc[-2])
            out[t] = {"price": last, "pct": (last - prev) / prev * 100}
    return out


# ----------------------------------------------------------------------------- app
app = Dash(__name__, suppress_callback_exceptions=True)
app.title = "FinPulse"


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
def home_page():
    snap = snapshot()
    prices = latest_price_changes()
    cards = []
    for s in snap:
        t = s["ticker"]
        pc = prices.get(t)
        if pc:
            pcolor = GREEN if pc["pct"] >= 0 else RED
            price_rows = [
                html.Div(f"${pc['price']:,.2f}", style={"fontSize": "24px", "fontWeight": "800"}),
                html.Div(f"{pc['pct']:+.2f}%", style={"fontSize": "16px", "fontWeight": "700", "color": pcolor}),
            ]
        else:
            price_rows = [html.Div("price n/a", style={"color": MUTED})]
        scolor = GREEN if s["mean"] > 0.05 else RED if s["mean"] < -0.05 else MUTED
        card = html.Div([
            html.Div(t, style={"fontSize": "18px", "fontWeight": "700"}),
            *price_rows,
            html.Div(f"sentiment {s['mean']:+.2f}",
                     style={"fontSize": "12px", "color": scolor, "marginTop": "8px"}),
        ], style=CARD_STYLE)
        cards.append(dcc.Link(card, href=f"/analytics?ticker={t}",
                              style={"textDecoration": "none", "color": "inherit",
                                     "flex": "1", "minWidth": "150px"}))

    top = headlines_df().head(8)
    news_items = []
    for _, r in top.iterrows():
        color = GREEN if r["label"] == "positive" else RED if r["label"] == "negative" else MUTED
        news_items.append(html.Div([
            html.Span(r["ticker"], style={"color": ACCENT, "fontWeight": "700", "marginRight": "10px"}),
            html.Span(r["text"]),
            html.Span(r["label"].capitalize(), style={"color": color, "float": "right", "fontWeight": "700"}),
        ], style={"padding": "12px 0", "borderBottom": f"1px solid {BORDER}"}))

    return html.Div([
        html.H2("Market Overview"),
        html.P("Latest daily price move per ticker — sentiment shown underneath.", style={"color": MUTED}),
        html.Div(cards, style={"display": "flex", "gap": "14px", "flexWrap": "wrap", "marginBottom": "32px"}),
        html.H2("Top Headlines"),
        html.Div(news_items, style={**CARD_STYLE, "flex": "unset"}),
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
        dcc.Graph(id="combined-graph", style={"height": "720px"}),
        dcc.Interval(id="tick", interval=60_000, n_intervals=0),   # redraw every 60 seconds
    ])


def news_page():
    df = headlines_df()
    if not df.empty:
        df = df.copy()
        df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
        df["score"] = df["score"].round(3)
    return html.Div([
        html.H2("All News"),
        html.P(f"{len(df)} processed headlines.", style={"color": MUTED}),
        dash_table.DataTable(
            data=df[["timestamp", "ticker", "label", "score", "text"]].to_dict("records") if not df.empty else [],
            columns=[{"name": c.title(), "id": c} for c in ["timestamp", "ticker", "label", "score", "text"]],
            page_size=20, sort_action="native", filter_action="native",
            style_table={"overflowX": "auto"},
            style_header={"background": PANEL, "color": TEXT, "fontWeight": "700", "border": f"1px solid {BORDER}"},
            style_cell={"background": BG, "color": TEXT, "border": f"1px solid {BORDER}",
                        "textAlign": "left", "padding": "8px", "fontFamily": "Segoe UI, sans-serif"},
            style_data_conditional=[
                {"if": {"filter_query": "{label} = positive", "column_id": "label"}, "color": GREEN},
                {"if": {"filter_query": "{label} = negative", "column_id": "label"}, "color": RED},
            ],
        ),
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


# ----------------------------------------------------------------------------- charts
@app.callback(
    Output("combined-graph", "figure"),
    Input("ticker-dropdown", "value"),
    Input("timeframe-dropdown", "value"),
    Input("tick", "n_intervals"),       # fires every 60s -> re-pull + redraw
)
def update_charts(ticker, timeframe, _tick):
    tf = TIMEFRAMES[timeframe]
    sent = aggregate_sentiment(ticker, tf["window"])
    ohlc = load_ohlc(ticker, period=tf["period"], interval=tf["interval"])
    sent = sent[sent.index >= ohlc.index.min()]    # trim sentiment to the timeframe

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
    fig.update_yaxes(title_text="Price ($)", row=2, col=1)
    return fig


if __name__ == "__main__":
    # use_reloader=False avoids the Windows "WinError 10038 (not a socket)" spam
    # from Werkzeug's file-watcher. Restart manually after code edits.
    app.run(debug=True, use_reloader=False, port=8050)
