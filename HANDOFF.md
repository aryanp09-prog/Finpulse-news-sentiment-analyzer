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
- Redesigned the home "Tracked Tickers" section in `app.build_home_content`: responsive CSS-grid
  of equal-height cards, an IN/US market chip, a labeled sentiment row (Positive/Neutral/Negative
  + score), a prominent amber "Disagreement" divergence flag, and a legend explaining it.
- STEP 1 DONE — multi-source news: added `finpulse/ingestion/news_rss.py` (Google News RSS
  `fetch_rss` + Moneycontrol `fetch_moneycontrol`, via feedparser); `fetch_news.ingest()` now
  merges NewsAPI + Google RSS per ticker + Moneycontrol (tagged), deduped by URL AND title.
  Coverage jumped 107 -> 309 headlines; every ticker now has 20+ (DMART fixed: 0 -> 20).

**Recent work (2026-06-12 — newest first):**
- STEP 3 FinBERT ✅ DONE. `analyzer.py` rewritten: VADER kept as fallback; `ProsusAI/finbert`
  lazy-loaded behind the SAME `score()/label()` interface (compound = P(pos)-P(neg), -1..+1);
  `SENTIMENT_ENGINE` env toggle (default "finbert", "vader" to force); any FinBERT error -> VADER
  (never crashes). Installed torch(CPU)+transformers+model to **D:** with caches redirected off the
  near-full C: (HF_HOME/PIP_CACHE_DIR/TMP -> `d:\finance_news_project\.cache\*`); C: moved ~120MB.
  `analyzer.py` sets HF_HOME itself so it's self-contained. `rescore.py` (new, repo root) backs up
  the DB then re-scores all rows — ran it on 394 headlines (neutral 159->72, pos 178->231, neg 57->91).
  requirements += feedparser/transformers/torch; .gitignore += *.db.bak, .cache/.
- More RSS: `news_rss.py` += `fetch_economictimes`/`fetch_cnbc`/`fetch_reuters` (Reuters via Google
  News, its own RSS is dead) over a shared `_fetch_feeds` helper; `fetch_news.py` runs all 4
  category feeds (MC/ET/CNBC/Reuters) through one tag-and-store loop. Coverage 309 -> 394.
- Timezone labels: `app._news_row` now shows each headline in ITS market's local tz via
  `_local_time` + `MARKET_TZ` (IN->IST, US->ET, else UTC). Storage stays UTC.

**Next steps (Step 4 — Live data; biggest/most complex, do only when user says go):**
- **Fyers API** (user HAS account) WebSocket -> live Indian ticks (daily OAuth session token).
- **Finnhub** free WebSocket -> live US ticks. Build a `price_source(ticker)` router (IN->Fyers,
  US->Finnhub/yfinance), common UTC OHLC shape, graceful fallback to yfinance if a feed/token fails.

**Small optional cleanups (not blocking):**
- Widen FinBERT neutral band ±0.05 -> ±0.15 in `analyzer.label()` (borderline e.g. "bank holiday"
  -0.09 currently reads negative).
- DB doesn't persist a `source` column -> can't do per-source analytics / source badges yet.

**Do NOT change:**
- The `config.py` dict shape (other files depend on the keys: name, query, yf, currency, peers...).
- The UTC handling in STORAGE/aggregation (`tz_localize` / `to_datetime(..., utc=True)`). Display-time
  tz conversion (IST/ET in `_local_time`) is fine and intended.
- The `score()/label()` interface or the VADER fallback in `analyzer.py`.
- The decoupling — sources must return the common `{text, source, timestamp, url}` dict.

**Open questions (do NOT guess — leave for the human):**
- Live data (Fyers / Finnhub) — separate later task; start only on explicit go.

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
