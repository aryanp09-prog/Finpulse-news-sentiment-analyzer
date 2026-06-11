# FinPulse — AI Handoff Brief

> Purpose: hand work between AI assistants (e.g. Claude Code <-> Codex) without losing context
> or breaking the app. When one assistant is near its usage limit, it fills in the **CURRENT
> HANDOFF** section below; the next assistant reads this file first, then continues.

---

## Standing context (always true — read this first)

**Project:** FinPulse — a financial news sentiment pipeline. News is fetched, scored (sentiment)
and tagged to a ticker, stored in SQLite, aggregated, and aligned against price; served via a
FastAPI REST API and a Dash/Plotly dashboard.

- **Full architecture + run steps:** `README.md`
- **Per-file explanation:** `code_explanation.pdf`
- **Stock universe / config:** `config.py` (single source of truth — tickers, yfinance symbols,
  currency, sector, peers, NewsAPI query terms).

**Golden rules (do not violate):**
- Always run from the **doubled-name folder**: `D:\finance_news_project\Finance_news_project`.
- Activate the venv (it lives in the OUTER folder): `..\.venv\Scripts\Activate.ps1`.
- Keep stages **decoupled** — modules talk only through the SQLite store and the queue; don't make
  them import each other beyond what's already there.
- All timestamps are **UTC**. Don't remove the `tz_localize` / `to_datetime(..., utc=True)` calls.
- Secrets live in **`.env`** (git-ignored) — never commit `.env` or `finpulse.db`.
- yfinance is called via `yf_symbol(ticker)` (Indian stocks use `.NS`). Don't pass display tickers
  straight to yfinance.

---

## CURRENT HANDOFF  (the outgoing assistant fills this in)

**Date / session:** 2026-06-11 — Claude Code

**Completed this session:**
- Switched the ticker universe to 8 Indian (.NS) + 2 US stocks via new `config.py`
  (HDFCBANK, SBIN, TRENT, DMART, SIEMENS, ABB, MARUTI, MM, MSFT, NVDA). `config.py` now holds
  name, NewsAPI `query`, yfinance symbol, currency, market, sector, peers, keywords.
- Wired every consumer to config: `ticker_tagger.py` (ALIASES + tag from STOCKS),
  `aggregation/aggregator.py` (load_price/load_ohlc use `yf_symbol`), `dashboard/app.py`
  (TICKERS/PEERS/currency from config), `seed.py` and `fetch_news.py` (iterate STOCKS).
- Added Indian finance domains to `ingestion/news_api.py` (moneycontrol, economictimes, livemint...).
- Replaced simulated seed with REAL NewsAPI news: 107 headlines across 9 tickers.
- Added `aggregator.recommendation(avg_sentiment, price_change_pct)` (Strong Buy..Strong Sell,
  60% sentiment + 40% momentum) and rendered it in `app.build_news_summary` (the analytics summary).
- Added this `HANDOFF.md` + smoke-test gate in `commands.txt` (section 7).

**In progress (file · function · what's half-done):**
- News coverage is thin/zero for some Indian tickers (DMART = 0, ABB = 1, SIEMENS = 2, TRENT = 3).
  NewsAPI free tier alone isn't enough for Indian names.

**Next steps, in order (with exact file:function):**
1. Create `finpulse/ingestion/news_rss.py` with `fetch_rss(query, limit=20)` that queries
   **Google News RSS** (`https://news.google.com/rss/search?q=<query>&hl=en-IN&gl=IN&ceid=IN:en`)
   using `feedparser` (run `pip install feedparser` first). Return the SAME dict shape as
   `news_api.fetch_headlines`: `{text, source, timestamp(ISO/UTC), url}`. Normalize the RSS
   RFC-822 date to ISO-8601 UTC.
2. In `fetch_news.ingest()`: for each ticker, call BOTH `news_api.fetch_headlines(query)` and
   `news_rss.fetch_rss(query)`, concatenate, and dedupe by URL (the existing `existing` set) AND
   by near-duplicate title. Keep the per-ticker "N new" print.
3. Run `python fetch_news.py` and confirm DMART/ABB/SIEMENS/TRENT now get headlines.

**Do NOT change:**
- The `config.py` dict shape (other files depend on the keys: name, query, yf, currency, peers...).
- The UTC handling anywhere (`tz_localize` / `to_datetime(..., utc=True)`).
- The `recommendation()` weights/thresholds (they're the documented methodology) unless asked.
- The decoupling — sources must return the common `{text, source, timestamp, url}` dict.

**Open questions (do NOT guess — leave for the human):**
- Should we also add Moneycontrol/ET RSS (category-level), or is Google News RSS enough?
- Live data (Fyers for Indian, Finnhub/yfinance for US) is a separate later task — not now.

---

## Verify before committing (the smoke-test gate)

Run ALL of these from the repo root. If any fails, the app is broken — fix before committing.

```powershell
# 1. dashboard imports + home page builds
python -c "import finpulse.dashboard.app as a; a.build_home_content(); print('dashboard OK')"

# 2. API imports
python -c "import finpulse.api.main; print('api OK')"

# 3. an analytics chart builds (Indian + US ticker)
python -c "import finpulse.dashboard.app as a; a.update_charts('HDFCBANK','1 Month',0); a.update_charts('MSFT','1 Month',0); print('charts OK')"

# 4. config + tickers load
python -c "from config import TICKERS; print('tickers:', TICKERS)"
```

Only after all four print OK:
```powershell
git add .
git status          # confirm NO .env and NO finpulse.db are staged
git commit -m "..."
git push
```
