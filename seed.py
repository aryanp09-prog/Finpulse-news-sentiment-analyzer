"""Seed finpulse.db with headlines spread over the last ~10 days,
so time-window aggregation has an actual trend to show.

Reuses every stage you've built: news_simulator -> analyzer -> ticker_tagger -> db.
Run from the repo root:  python seed.py
"""

from datetime import datetime, timezone, timedelta

from finpulse.ingestion.news_simulator import get_headlines
from finpulse.sentiment.analyzer import score, label
from finpulse.sentiment.ticker_tagger import tag
from finpulse.storage.db import init_db, insert_headline


def seed():
    init_db()
    headlines = get_headlines()
    now = datetime.now(timezone.utc)
    rows = 0
    for i, h in enumerate(headlines):
        # space each headline 12 hours apart, going back in time
        ts = (now - timedelta(hours=12 * i)).isoformat()
        s = score(h)
        lab = label(h)
        for ticker in tag(h):
            insert_headline(h, ticker, s, lab, ts)
            rows += 1
    print(f"seeded {rows} rows from {len(headlines)} headlines")


if __name__ == "__main__":
    seed()
