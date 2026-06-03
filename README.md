# Finance_news_project
# FinPulse — Real-Time Financial News Sentiment Pipeline

An end-to-end pipeline that ingests a stream of financial news headlines, scores
their sentiment, tags them to stock tickers, aggregates sentiment over time
windows, and aligns that sentiment against real price data — all exposed through
a documented API and an interactive dashboard.

> ⚠️ **FinPulse is an educational demonstration of a data pipeline. Nothing here is financial advice.**

## Architecture

Data flows left-to-right through decoupled stages. Stages communicate only
through a queue (live) and the SQLite store — none of them import each other,
so any one can be swapped out independently.

```
                    ┌──────────────┐
  news_simulator ─► │    Queue     │ ─► sentiment + ticker tagging ─► SQLite
  (or real feed)    └──────────────┘                                    │
                                                                        ▼
  yfinance price feed ───────────────────► aggregation (windows + ─► API (FastAPI)
                                            sentiment-vs-price align)    │
                                                                        ▼
                                                              dashboard (Dash/Plotly)
```

| Stage | Module | Brief requirement |
|-------|--------|-------------------|
| Ingestion (news) | `finpulse/ingestion/news_simulator.py` | (1) simulated streaming feed |
| Ingestion (price) | `finpulse/ingestion/price_feed.py` | (4) real price data + graceful fallback |
| Sentiment | `finpulse/sentiment/analyzer.py` | (2) sentiment analysis (VADER, finance-tuned lexicon) |
| Ticker tagging | `finpulse/sentiment/ticker_tagger.py` | (2) tag associated ticker(s) |
| Aggregation | `finpulse/aggregation/aggregator.py` | (3) time-window aggregation + (4) alignment |
| Storage | `finpulse/storage/db.py` | (5) persistence (SQLite) |
| API | `finpulse/api/main.py` | (5) documented API (FastAPI) |
| Dashboard | `finpulse/dashboard/app.py` | (6) sentiment-vs-price chart (Dash) |
| Orchestration | `finpulse/pipeline/runner.py` | streaming flow, decoupled stages |

## Setup

```powershell
# from the project root: c:\Users\Home\Desktop\fin_project
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run it

```powershell
# 1. Seed historical headlines so charts have data immediately
python scripts/run_pipeline.py seed

# 2a. Start the API (Swagger docs at http://127.0.0.1:8000/docs)
uvicorn finpulse.api.main:app --reload

# 2b. Start the dashboard (http://127.0.0.1:8050)
python -m finpulse.dashboard.app

# 3. (optional) Stream live-ish headlines and watch the pipeline react
python scripts/run_pipeline.py stream
```

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Liveness + stored row count |
| `GET /tickers` | Tracked tickers |
| `GET /headlines?ticker=AAPL&limit=50` | Recent processed headlines |
| `GET /sentiment/{ticker}` | Time-windowed aggregated sentiment |
| `GET /alignment/{ticker}` | Sentiment aligned against price |
| `GET /snapshot` | Latest window per ticker |

Interactive docs are auto-generated at `/docs` and `/redoc`.

## Configuration

All tickers, keyword aliases, source weights, and window settings live in
[`config.py`](config.py).

## Creativity hooks already scaffolded

- **Source weighting** — `config.SOURCE_WEIGHTS` weights a wire service above a forum post.
- **Graceful degradation** — `price_feed.py` falls back to a synthetic series if yfinance is down.
- **Entity disambiguation** — `ticker_tagger.py` is the place to grow "Apple the company vs the fruit".
- Room to add: backtesting a sentiment signal, anomaly/divergence alerts, replay mode.
