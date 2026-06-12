"""Pull REAL headlines from multiple sources, score them, dedupe, and store them.

Sources (all return the same {text, source, timestamp, url} dict shape):
  - NewsAPI            (per-ticker, finance domains)
  - Google News RSS    (per-ticker, great Indian + global coverage, no key)
  - Moneycontrol RSS   (category-level Indian market news, tagged to our tickers)

Adds to the existing DB (delete finpulse.db first if you want a clean rebuild).
Run from the repo root:  python fetch_news.py
"""

from finpulse.ingestion.news_api import fetch_headlines
from finpulse.ingestion.news_rss import fetch_rss, fetch_moneycontrol
from finpulse.sentiment.analyzer import score, label
from finpulse.sentiment.ticker_tagger import tag
from finpulse.storage.db import init_db, insert_headline, fetch_all
from config import STOCKS


def ingest(per_company=20):
    init_db()
    rows = fetch_all()
    seen_urls = {r[6] for r in rows if len(r) > 6 and r[6]}
    seen_titles = {r[1].strip().lower() for r in rows if len(r) > 1 and r[1]}

    def store(text, ticker, ts, url):
        title_key = text.strip().lower()
        if (url and url in seen_urls) or title_key in seen_titles:   # dedupe by URL AND title
            return 0
        insert_headline(text, ticker, score(text), label(text), ts, url=url)
        if url:
            seen_urls.add(url)
        seen_titles.add(title_key)
        return 1

    total = 0
    # 1. Per-ticker: NewsAPI + Google News RSS
    for ticker, info in STOCKS.items():
        q = info.get("query", info["name"])
        items = []
        try:
            items += fetch_headlines(q, limit=per_company)
        except Exception as e:
            print(f"{ticker} NewsAPI skipped ({e})")
        try:
            items += fetch_rss(q, limit=per_company)
        except Exception as e:
            print(f"{ticker} RSS skipped ({e})")
        new = sum(store(h["text"], ticker, h["timestamp"], h.get("url")) for h in items)
        total += new
        print(f"{ticker}: {new} new")

    # 2. Category-level: Moneycontrol -> tag each headline to our tickers
    try:
        mc_new = 0
        for h in fetch_moneycontrol(limit=120):
            for tk in tag(h["text"]):
                mc_new += store(h["text"], tk, h["timestamp"], h.get("url"))
        total += mc_new
        print(f"Moneycontrol (tagged): {mc_new} new")
    except Exception as e:
        print(f"Moneycontrol skipped ({e})")

    print(f"--- ingested {total} new headlines ---")
    return total


if __name__ == "__main__":
    ingest()
