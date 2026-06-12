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


def fetch_moneycontrol(limit=80):
    """Category-level Indian market news from Moneycontrol RSS (tagged to tickers by the caller)."""
    out = []
    for feed_url in MONEYCONTROL_FEEDS:
        feed = feedparser.parse(feed_url)
        for e in feed.entries:
            title = e.get("title")
            if not title:
                continue
            out.append({"text": title, "source": "Moneycontrol",
                        "timestamp": _timestamp(e), "url": e.get("link")})
            if len(out) >= limit:
                return out
    return out
