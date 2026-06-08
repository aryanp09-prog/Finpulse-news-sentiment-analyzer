"""Pull REAL headlines from NewsAPI for each tracked ticker, score them, store them.

Same pipeline as seed.py, but the headlines are real instead of simulated.
Adds to the existing DB (delete finpulse.db first if you want only-real data).

Run from the repo root:  python fetch_news.py
"""

from finpulse.ingestion.news_api import fetch_headlines
from finpulse.sentiment.analyzer import score, label
from finpulse.sentiment.ticker_tagger import ALIASES
from finpulse.storage.db import init_db, insert_headline


def ingest(per_company=20):
    init_db()
    total = 0
    for keyword, ticker in ALIASES.items():
        try:
            headlines = fetch_headlines(keyword.capitalize(), limit=per_company)
        except Exception as e:                       # bad key, rate limit, network -> skip ticker
            print(f"{ticker}: skipped ({e})")
            continue
        for h in headlines:
            s = score(h["text"])
            lab = label(h["text"])
            insert_headline(h["text"], ticker, s, lab, h["timestamp"], url=h.get("url"))
            total += 1
        print(f"{ticker}: stored {len(headlines)} real headlines")
    print(f"--- ingested {total} real headlines total ---")


if __name__ == "__main__":
    ingest()
