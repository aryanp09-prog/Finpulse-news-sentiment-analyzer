# FinPulse — Learning Roadmap & Milestones

A checklist to take this project from scaffold → something you fully understand
and can defend. Tick each box as you go. The goal is that you can explain every
line you submit.

> The `finpulse/` scaffold is a **reference implementation**. For each milestone,
> try it yourself first; peek at the matching file only when stuck, understand it,
> then write it in your own words.

> ⚠️ FinPulse is an educational demonstration. Nothing here is financial advice.

---

## Milestone 0 — Foundations ✅ DONE
- [x] Create & activate a virtual environment (`python -m venv .venv`)
- [x] `pip install -r requirements.txt`
- [x] Confirm imports work: `python -c "import pandas, fastapi, dash"`
- [x] Make your first commit
- **Learn:** venv, pip, packages/imports, Git basics

## Milestone 1 — Two data sources, working independently ✅ DONE
- [x] Pull price data with yfinance and print a DataFrame
- [x] Get headlines (NewsAPI **or** the simulated JSON pool) and print a few
- [x] Inspect and understand every field in both
- **Learn:** yfinance, DataFrames, timestamps/timezones, REST + `requests`
- **Reference:** `finpulse/ingestion/`

## Milestone 2 — Sentiment + ticker tagging (static batch)
- [ ] Score a headline with VADER; understand the `compound` score
- [ ] Map a headline to its ticker(s) via keyword matching
- [ ] Run over a static list of ~20 headlines; eyeball the results
- [ ] (Bonus) Try a finance-tuned model (FinBERT via Hugging Face)
- **Learn:** VADER, regex/word boundaries, why finance vocab needs tuning
- **Reference:** `finpulse/sentiment/`

## Milestone 3 — Persist + make it stream (the systems core)
- [ ] Create a SQLite table, INSERT and SELECT rows
- [ ] Build a producer → queue → consumer flow
- [ ] Consumer scores + tags + writes to SQLite
- [ ] Run it and watch rows accumulate over time
- [ ] Explain *why* the stages are decoupled
- **Learn:** sqlite3, `queue.Queue`, threading, producer/consumer pattern
- **Reference:** `finpulse/storage/db.py`, `finpulse/pipeline/runner.py`

## Milestone 4 — Aggregation + sentiment-vs-price alignment (analytical core)
- [ ] Resample sentiment into time windows (`resample("1h")`)
- [ ] Resample price to the same window
- [ ] Join both into one table on the timestamp
- [ ] Normalize all timestamps to UTC (the #1 silent bug)
- **Learn:** pandas resample/merge, time-series alignment, timezones
- **Reference:** `finpulse/aggregation/aggregator.py`

## Milestone 5 — API
- [ ] Build FastAPI endpoints reading from your store/aggregator
- [ ] Serve with uvicorn; open the auto-docs at `/docs`
- [ ] Test each endpoint from the Swagger UI
- **Learn:** FastAPI routes/params, uvicorn, REST, auto-generated docs
- **Reference:** `finpulse/api/main.py`

## Milestone 6 — Dashboard
- [ ] Build a dual-axis Plotly chart (sentiment vs price)
- [ ] Add a Dash ticker dropdown + callback to redraw
- [ ] (Optional) Auto-refresh so you can watch it update live
- **Learn:** Plotly figures/dual-axis, Dash layout + callbacks
- **Reference:** `finpulse/dashboard/app.py`

## Milestone 7 — Pick ONE creativity feature (do it well)
- [ ] Choose one: divergence/anomaly alert · source weighting · simple backtest · entity disambiguation
- [ ] Implement it
- [ ] Surface it in the API and/or dashboard
- [ ] Include the "educational tool, not financial advice" disclaimer
- **One done well beats five half-built.**

---

## Definition of done (your internship deliverable)
- [ ] All 6 must-have requirements run end-to-end without errors
- [ ] You can explain every part in a code review
- [ ] At least one creativity feature that's genuinely yours
- [ ] README in your own words; clean commit history
- [ ] Disclaimer present
