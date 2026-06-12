"""RSS news sources (Google News + Moneycontrol).

Both return the SAME dict shape as news_api.fetch_headlines
({text, source, timestamp(ISO-UTC), url}) so fetch_news can merge them transparently.
Needs: pip install feedparser
"""

import calendar
import urllib.parse
from datetime import datetime, timezone

import feedparser

GOOGLE_NEWS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"

MONEYCONTROL_FEEDS = [
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://www.moneycontrol.com/rss/business.xml",
    "https://www.moneycontrol.com/rss/marketreports.xml",
]

# Economic Times — Indian business/markets news (category-level)
ET_FEEDS = [
    "https://economictimes.indiatimes.com/markets/stocks/news/rssfeeds/2146843.cms",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://economictimes.indiatimes.com/news/economy/rssfeeds/1373380680.cms",
]

# CNBC — market-moving global/US news (category-level)
CNBC_FEEDS = [
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",   # Markets
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",   # Finance
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",  # Top News
]

# Reuters dropped its public RSS in 2020 — pull it via Google News filtered to reuters.com.
REUTERS_QUERY = "site:reuters.com (business OR markets OR stocks OR economy)"


def _timestamp(entry):
    if entry.get("published_parsed"):
        # feedparser gives a UTC struct_time -> ISO-8601 UTC
        return datetime.fromtimestamp(calendar.timegm(entry.published_parsed), tz=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def fetch_rss(query, limit=20):
    """Per-query news from Google News RSS (great Indian + global coverage, no key)."""
    url = GOOGLE_NEWS.format(q=urllib.parse.quote(query))
    feed = feedparser.parse(url)
    out = []
    for e in feed.entries[:limit]:
        title = e.get("title")
        if not title:
            continue
        source = "Google News"
        if e.get("source") and getattr(e.source, "title", None):
            source = e.source.title
            # Google News appends " - Publisher" to titles; strip it when it matches.
            if title.endswith(f" - {source}"):
                title = title[: -len(f" - {source}")]
        out.append({"text": title, "source": source, "timestamp": _timestamp(e), "url": e.get("link")})
    return out


def _fetch_feeds(feed_urls, source, limit):
    """Pull headlines from a list of RSS feeds under one source label (category-level)."""
    out = []
    for feed_url in feed_urls:
        feed = feedparser.parse(feed_url)
        for e in feed.entries:
            title = e.get("title")
            if not title:
                continue
            out.append({"text": title, "source": source,
                        "timestamp": _timestamp(e), "url": e.get("link")})
            if len(out) >= limit:
                return out
    return out


def fetch_moneycontrol(limit=80):
    """Category-level Indian market news from Moneycontrol RSS (tagged to tickers by the caller)."""
    return _fetch_feeds(MONEYCONTROL_FEEDS, "Moneycontrol", limit)


def fetch_economictimes(limit=80):
    """Category-level Indian business/markets news from Economic Times RSS."""
    return _fetch_feeds(ET_FEEDS, "Economic Times", limit)


def fetch_cnbc(limit=80):
    """Category-level market-moving US/global news from CNBC RSS."""
    return _fetch_feeds(CNBC_FEEDS, "CNBC", limit)


def fetch_reuters(limit=40):
    """High-quality global news from Reuters (via Google News, since Reuters' own RSS is gone)."""
    items = fetch_rss(REUTERS_QUERY, limit=limit)
    for it in items:
        it["source"] = "Reuters"
    return items
