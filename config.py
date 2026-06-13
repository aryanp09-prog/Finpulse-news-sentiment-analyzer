"""Single source of truth for the tracked stock universe.

Each entry separates:
  - the internal ticker (URL-safe key used across the app)
  - the yfinance symbol (Indian stocks need the .NS suffix; "M&M" has an &)
  - display name (for the dashboard + NewsAPI query)
  - currency, market, sector, peers (same-sector), and keywords (for tagging)
"""

STOCKS = {
    # ---- Banking (India) ----
    "HDFCBANK": {"name": "HDFC Bank", "yf": "HDFCBANK.NS", "currency": "₹", "market": "IN",
                 "sector": "Banking", "peers": ["SBIN"], "keywords": ["hdfc bank", "hdfc"],
                 "domain": "hdfcbank.com"},
    "SBIN": {"name": "State Bank of India", "query": "SBI", "yf": "SBIN.NS", "currency": "₹", "market": "IN",
             "sector": "Banking", "peers": ["HDFCBANK"], "keywords": ["state bank", "sbi"],
             "domain": "sbi.co.in",
             "logo": "https://www.google.com/s2/favicons?domain=onlinesbi.sbi&sz=64"},
    # ---- Retail (India) ----
    "TRENT": {"name": "Trent", "yf": "TRENT.NS", "currency": "₹", "market": "IN",
              "sector": "Retail", "peers": ["DMART"], "keywords": ["trent"],
              "domain": "trentlimited.com",
              "logo": "https://www.google.com/s2/favicons?domain=westside.com&sz=64"},
    "DMART": {"name": "Avenue Supermarts", "query": "DMart", "yf": "DMART.NS", "currency": "₹", "market": "IN",
              "sector": "Retail", "peers": ["TRENT"], "keywords": ["avenue supermarts", "dmart"],
              "domain": "dmartindia.com"},
    # ---- Manufacturing (India) ----
    "SIEMENS": {"name": "Siemens India", "yf": "SIEMENS.NS", "currency": "₹", "market": "IN",
                "sector": "Manufacturing", "peers": ["ABB"], "keywords": ["siemens"],
                "domain": "siemens.com"},
    "ABB": {"name": "ABB India", "yf": "ABB.NS", "currency": "₹", "market": "IN",
            "sector": "Manufacturing", "peers": ["SIEMENS"], "keywords": ["abb"],
            "domain": "abb.com"},
    # ---- Automobile (India) ----
    "MARUTI": {"name": "Maruti Suzuki", "yf": "MARUTI.NS", "currency": "₹", "market": "IN",
               "sector": "Automobile", "peers": ["MM"], "keywords": ["maruti", "suzuki"],
               "domain": "marutisuzuki.com"},
    "MM": {"name": "Mahindra & Mahindra", "yf": "M&M.NS", "currency": "₹", "market": "IN",
           "sector": "Automobile", "peers": ["MARUTI"], "keywords": ["mahindra"],
           "domain": "mahindra.com",
           "logo": "https://www.google.com/s2/favicons?domain=auto.mahindra.com&sz=64"},
    # ---- Global ----
    "MSFT": {"name": "Microsoft", "yf": "MSFT", "currency": "$", "market": "US",
             "sector": "Global Tech", "peers": ["NVDA"], "keywords": ["microsoft"],
             "domain": "microsoft.com"},
    "NVDA": {"name": "NVIDIA", "yf": "NVDA", "currency": "$", "market": "US",
             "sector": "Global Tech", "peers": ["MSFT"], "keywords": ["nvidia"],
             "domain": "nvidia.com"},
}

TICKERS = list(STOCKS.keys())


def yf_symbol(ticker):
    return STOCKS[ticker]["yf"]


def currency(ticker):
    return STOCKS[ticker]["currency"]


def peers(ticker):
    return STOCKS[ticker]["peers"]


def display_name(ticker):
    return STOCKS[ticker]["name"]


def logo_url(ticker, size=64):
    """Company logo. Uses a per-ticker `logo` override if set, else Google's favicon service
    (which always returns an icon — never a broken image)."""
    override = STOCKS[ticker].get("logo")
    if override:
        return override
    domain = STOCKS[ticker].get("domain")
    if not domain:
        return None
    return f"https://www.google.com/s2/favicons?domain={domain}&sz={size}"
