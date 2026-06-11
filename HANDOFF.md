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

**Date / session:**

**Completed this session:**
-

**In progress (file · function · what's half-done):**
-

**Next steps, in order (with exact file:function):**
1.
2.
3.

**Do NOT change:**
-

**Open questions (do NOT guess — leave for the human):**
-

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
