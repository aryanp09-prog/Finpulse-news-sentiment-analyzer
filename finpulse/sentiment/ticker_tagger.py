ALIASES = {
    "apple": "AAPL",
    "tesla": "TSLA",
    "microsoft": "MSFT",
    "google": "GOOGL",
    "amazon": "AMZN",
    "nvidia": "NVDA",
    "meta": "META",
    "netflix": "NFLX",
}

def tag(text):
    words = text.lower().split()
    found = []
    for keyword, ticker in ALIASES.items():
        if keyword in words:
            found.append(ticker)
    return found
        