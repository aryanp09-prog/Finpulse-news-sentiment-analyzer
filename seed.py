"""Seed finpulse.db with a realistic spread of headlines.

For every tracked ticker, generate 1-2 headlines per day over the last ~20 days,
picking from positive / negative / neutral templates so daily sentiment varies
(gives the dashboard charts an actual wiggling line to draw).

Reuses every stage you built: analyzer -> ticker_tagger -> db.
Run from the repo root:  python seed.py
"""

import random
from datetime import datetime, timezone, timedelta

from finpulse.sentiment.analyzer import score, label
from finpulse.sentiment.ticker_tagger import tag, ALIASES
from finpulse.storage.db import init_db, insert_headline

POSITIVE = [
    "{n} shares soared on strong quarterly earnings",
    "{n} rallies as analysts upgrade the stock",
    "{n} surges to a record high on upbeat guidance",
    "{n} turns bullish after a positive outlook",
    "{n} jumps as investors cheer new growth",
]
NEGATIVE = [
    "{n} plunges on a weak revenue outlook",
    "{n} slumps after a surprise downgrade",
    "{n} announces layoffs amid bearish sentiment",
    "{n} selloff deepens as shares plunge",
    "{n} downgrade weighs heavily on the stock",
]
NEUTRAL = [
    "{n} announces a new product line",
    "{n} holds steady ahead of earnings",
    "{n} in focus for investors this week",
    "{n} unveils its quarterly business update",
]


def seed(days=365):
    init_db()
    random.seed(42)                       # reproducible data
    now = datetime.now(timezone.utc)
    rows = 0
    for keyword, ticker in ALIASES.items():
        name = keyword.capitalize()       # "apple" -> "Apple" (so ticker_tagger matches)
        for d in range(days):
            for _ in range(random.randint(1, 2)):       # 1-2 headlines per day
                pool = random.choices([POSITIVE, NEGATIVE, NEUTRAL], weights=[4, 3, 2])[0]
                headline = random.choice(pool).format(n=name)
                ts = (now - timedelta(days=d, hours=random.randint(0, 8))).isoformat()
                s = score(headline)
                lab = label(headline)
                for tk in tag(headline):
                    insert_headline(headline, tk, s, lab, ts)
                    rows += 1
    print(f"seeded {rows} rows across {days} days for {len(set(ALIASES.values()))} tickers")


if __name__ == "__main__":
    seed()
