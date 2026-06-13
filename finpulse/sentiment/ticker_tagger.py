import re

from config import STOCKS

# Backward-compatible keyword -> ticker map (used by the API's /tickers, etc.).
ALIASES = {kw: ticker for ticker, info in STOCKS.items() for kw in info["keywords"]}


def is_relevant(text, ticker):
    """False if the headline contains a per-ticker EXCLUDE term (off-topic disambiguation).

    A safety net so a keyword match alone can't mis-tag news — e.g. "Trent" the footballer /
    university, or "Tech Mahindra" (a different listed company) tagged to MM.
    """
    low = text.lower()
    return not any(term in low for term in STOCKS.get(ticker, {}).get("exclude", []))


def tag(text):
    """Return the tickers whose company keyword(s) appear in the text (word-boundary match),
    skipping any ticker the text is NOT relevant to (per-ticker exclude terms)."""
    low = text.lower()
    found = []
    for ticker, info in STOCKS.items():
        if any(re.search(r"\b" + re.escape(kw) + r"\b", low) for kw in info["keywords"]):
            if is_relevant(text, ticker):
                found.append(ticker)
    return found
