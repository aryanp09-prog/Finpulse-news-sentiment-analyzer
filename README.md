# FinPulse — Financial News Sentiment Pipeline

FinPulse ingests financial news headlines, scores their **sentiment**, tags each to a
**stock ticker**, aggregates that sentiment over time, and **aligns it against real
price data** — all served through a documented **REST API** and an interactive
**dashboard** with a Market Mood Index, divergence alerts, and per-stock news summaries.

It runs on **simulated** headlines out of the box and on **real news** via NewsAPI.

> ⚠️ **FinPulse is an educational demonstration of a data pipeline. Nothing here is financial advice.**

---

## What it does

- **Two data sources** — a simulated headline feed *and* live finance news from NewsAPI; real daily prices from yfinance.
- **Sentiment scoring** — VADER tuned with a custom **finance lexicon** so it understands words like *soared*, *plunge*, *downgrade*, *bullish*.
- **Ticker tagging** — keyword matching maps each headline to the company it's about.
- **Streaming pipeline** — a producer → queue → consumer flow scores + stores headlines concurrently (threads), persisted to SQLite.
- **Aggregation + alignment** — daily sentiment is joined against price on a shared **UTC** time axis.
- **REST API** — six FastAPI endpoints with auto-generated Swagger docs.
- **Dashboard** — a 3-page Dash app: market overview, sentiment-vs-price analytics, and a searchable news table.

### Standout features
- **📊 Market Mood Index** — a transparent fear/greed gauge blending market breadth, momentum, volatility, and my own news sentiment.
- **⚠️ Divergence detector** — flags when news sentiment and price move in *opposite* directions (e.g. positive news, falling price).
- **🔎 Entity disambiguation** — NewsAPI queries use `qInTitle` + finance-only sources so "Apple" means the company, not the fruit (or a football match).
- **📝 News summary** — a plain-English directional *read* of a stock's recent news (observational — never buy/sell/hold).
- **🔗 Clickable headlines** that open the original article, and **timeframe selector** + 60-second auto-refresh on the charts.

---

## Architecture

Stages are **decoupled** — they communicate only through a queue (live) and the SQLite
store, and none import each other, so any one can be swapped independently.

```
 news_simulator / NewsAPI ─►  Queue  ─►  sentiment + ticker tagging  ─►  SQLite
                                                                           │
 yfinance prices ──────────────────────►  aggregation (windows + align) ──┤
                                                                           ▼
                                                    API (FastAPI)  ·  Dashboard (Dash/Plotly)
```

| Stage | Module |
|-------|--------|
| Ingestion — simulated news | `finpulse/ingestion/news_simulator.py` |
| Ingestion — real news (NewsAPI) | `finpulse/ingestion/news_api.py` |
| Ingestion — prices | `finpulse/ingestion/price_feed.py` |
| Sentiment (VADER + finance lexicon) | `finpulse/sentiment/analyzer.py` |
| Ticker tagging | `finpulse/sentiment/ticker_tagger.py` |
| Aggregation, alignment, divergence | `finpulse/aggregation/aggregator.py` |
| Storage (SQLite) | `finpulse/storage/db.py` |
| API (FastAPI) | `finpulse/api/main.py` |
| Dashboard (Dash) | `finpulse/dashboard/app.py` |
| Streaming orchestration | `finpulse/pipeline/runner.py` |

Top-level scripts: `seed.py` (generate a year of simulated data), `fetch_news.py`
(pull real news), `batch_test.py` (run the pipeline over a static batch).

---

## Tech stack
Python · pandas · VADER (`vaderSentiment`) · yfinance · NewsAPI (`requests`) ·
SQLite (`sqlite3`) · FastAPI + uvicorn · Dash + Plotly · `python-dotenv`.

---

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### (Optional) real news — NewsAPI key
For live headlines, get a free key at <https://newsapi.org> and create a `.env`
file in the project root:

```
NEWSAPI_KEY=your_key_here
```

`.env` is git-ignored, so the key stays private. Without it, the simulated feed still works.

---

## Running it

```powershell
# 1. Seed data so the charts have something to show
python seed.py            # simulated: a year of headlines
#  -- or, for real news (needs NEWSAPI_KEY) --
python fetch_news.py      # pulls real finance headlines per ticker

# 2. Start the API  (Swagger docs at http://127.0.0.1:8000/docs)
uvicorn finpulse.api.main:app --reload

# 3. Start the dashboard  (http://127.0.0.1:8050)
python -m finpulse.dashboard.app

# (optional) watch the streaming pipeline write rows live
python -m finpulse.pipeline.runner
```

The API and dashboard are **independent** — the dashboard reads SQLite directly, so it
runs without the API. Both just need `finpulse.db` to exist (run step 1 once).

---

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Liveness + stored row count |
| `GET /tickers` | Tracked tickers |
| `GET /headlines?ticker=AAPL&limit=50` | Recent processed headlines (with source URL) |
| `GET /sentiment/{ticker}` | Daily aggregated sentiment |
| `GET /alignment/{ticker}` | Sentiment aligned against price |
| `GET /snapshot` | Latest sentiment per ticker |

Interactive docs auto-generated at `/docs`.

---

## Dashboard pages
- **Home** — Market Mood Index gauge + zone guide, per-ticker price/sentiment cards (clickable → Analytics), divergence badges, top headlines, and a **Fetch latest news** button.
- **Analytics** — sentiment line + candlestick (OHLC) on a shared, scroll-synced time axis, a timeframe selector, and a **News Summary** with a directional read.
- **News** — a sortable/filterable table of every processed headline, linking to the source.

---

## How sentiment works
VADER is a general-purpose model and is blind to finance vocabulary (it scores
*"shares soared"* as neutral). FinPulse extends VADER's lexicon with finance terms
(`analyzer.FINANCE_LEXICON`), so the same engine reads financial language correctly.
Each headline gets a **compound score** in `[-1, +1]`, labelled positive / neutral /
negative at ±0.05.

---

## Configuration
Tracked tickers and their keyword aliases live in `ALIASES` in
[`finpulse/sentiment/ticker_tagger.py`](finpulse/sentiment/ticker_tagger.py).
Add a line like `"amd": "AMD"` and it propagates everywhere — ingestion, API, and dashboard.

---

## Known limitations (and how they'd be solved)
Being honest about the constraints:

- **News history is shallow.** NewsAPI's free tier is delayed ~24h and only goes back ~1 month, so real sentiment is recent and sparse against the longer price history. A paid/archival feed (or running the collector daily to accumulate history) fixes this.
- **VADER misses nuance.** Even tuned, a lexicon misses much financial language, so real headlines often score neutral. The upgrade is **FinBERT** (a finance-trained model), ideally via the HuggingFace Inference API.
- **Relevance isn't perfect.** `qInTitle` + finance domains filter most noise, but headlines that merely *mention* a company still slip through. True aspect-based sentiment / NER is the full fix.
- **The Market Mood Index is a heuristic.** It approximates a fear/greed gauge from public data; it does not use proprietary inputs (FII flows, options data). Weights are tunable.
- **Prices aren't tick-level.** yfinance is ~15-min delayed; genuinely live candles need a streaming feed (e.g. Finnhub WebSocket).

---

## Disclaimer
FinPulse is an **educational demonstration**. It does not provide financial advice,
and nothing in it should be used to make investment decisions.
