"""Real headline source via NewsAPI (https://newsapi.org).

Drop-in alternative to news_simulator: returns the SAME dict shape
({text, source, timestamp}) so the rest of the pipeline doesn't change.

Needs a free API key in a .env file at the repo root:
    NEWSAPI_KEY=your_key_here
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()                       # read .env into environment variables
API_KEY = os.getenv("NEWSAPI_KEY")
URL = "https://newsapi.org/v2/everything"

# Restrict to financial outlets so "Apple" means the company, not a fruit or a football match.
FINANCE_DOMAINS = (
    # global finance
    "bloomberg.com,reuters.com,cnbc.com,wsj.com,marketwatch.com,fortune.com,"
    "businessinsider.com,finance.yahoo.com,fool.com,investing.com,"
    # indian finance (for the NSE-listed tickers)
    "moneycontrol.com,economictimes.indiatimes.com,livemint.com,business-standard.com,"
    "thehindubusinessline.com,financialexpress.com,ndtvprofit.com,zeebiz.com"
)


def fetch_headlines(query, limit=20):
    """Fetch recent English finance headlines matching `query` (e.g. a company name)."""
    if not API_KEY:
        raise RuntimeError("NEWSAPI_KEY not set — add it to a .env file at the repo root")

    params = {
        "qInTitle": query,            # company must appear in the HEADLINE, not just the body
        "language": "en",
        "sortBy": "relevancy",        # most on-topic first (not just newest)
        "domains": FINANCE_DOMAINS,   # only financial news sources
        "pageSize": limit,
        "apiKey": API_KEY,
    }
    resp = requests.get(URL, params=params, timeout=10)
    resp.raise_for_status()                       # raise on HTTP errors (bad key, rate limit)

    out = []
    for a in resp.json().get("articles", []):
        if not a.get("title"):
            continue
        out.append({
            "text": a["title"],
            "source": (a.get("source") or {}).get("name", "unknown"),
            "timestamp": a["publishedAt"],         # ISO 8601, e.g. 2026-06-08T12:30:00Z
            "url": a.get("url"),                   # link to the original article
        })
    return out
