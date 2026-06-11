import re

from config import STOCKS

# Backward-compatible keyword -> ticker map (used by the API's /tickers, etc.).
ALIASES = {kw: ticker for ticker, info in STOCKS.items() for kw in info["keywords"]}


def tag(text):
    """Return the tickers whose company keyword(s) appear in the text (word-boundary match)."""
    text = text.lower()
    found = []
    for ticker, info in STOCKS.items():
        if any(re.search(r"\b" + re.escape(kw) + r"\b", text) for kw in info["keywords"]):
            found.append(ticker)
    return found
