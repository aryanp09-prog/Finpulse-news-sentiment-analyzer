"""Pull REAL headlines from NewsAPI for each tracked ticker, score them, store them.

Same pipeline as seed.py, but the headlines are real instead of simulated.
Adds to the existing DB (delete finpulse.db first if you want only-real data).

Run from the repo root:  python fetch_news.py
"""

from finpulse.ingestion.news_api import fetch_headlines
from finpulse.sentiment.analyzer import score, label
from finpulse.storage.db import init_db, insert_headline, fetch_all
from config import STOCKS


def ingest(per_company=20):
    init_db()
    existing = {r[6] for r in fetch_all() if len(r) > 6 and r[6]}   # URLs already stored
    total = 0
    for ticker, info in STOCKS.items():
        try:
            headlines = fetch_headlines(info.get("query", info["name"]), limit=per_company)
        except Exception as e:                       # bad key, rate limit, network -> skip ticker
            print(f"{ticker}: skipped ({e})")
            continue
        new = 0
        for h in headlines:
            if h.get("url") in existing:             # skip articles we already have
                continue
            insert_headline(h["text"], ticker, score(h["text"]), label(h["text"]),
                            h["timestamp"], url=h.get("url"))
            existing.add(h.get("url"))
            new += 1
            total += 1
        print(f"{ticker}: {new} new")
    print(f"--- ingested {total} new headlines ---")
    return total


if __name__ == "__main__":
    ingest()
