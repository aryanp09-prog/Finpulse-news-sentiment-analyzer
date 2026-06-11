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
                 "sector": "Banking", "peers": ["SBIN"], "keywords": ["hdfc bank", "hdfc"]},
    "SBIN": {"name": "State Bank of India", "query": "SBI", "yf": "SBIN.NS", "currency": "₹", "market": "IN",
             "sector": "Banking", "peers": ["HDFCBANK"], "keywords": ["state bank", "sbi"]},
    # ---- Retail (India) ----
    "TRENT": {"name": "Trent", "yf": "TRENT.NS", "currency": "₹", "market": "IN",
              "sector": "Retail", "peers": ["DMART"], "keywords": ["trent"]},
    "DMART": {"name": "Avenue Supermarts", "query": "DMart", "yf": "DMART.NS", "currency": "₹", "market": "IN",
              "sector": "Retail", "peers": ["TRENT"], "keywords": ["avenue supermarts", "dmart"]},
    # ---- Manufacturing (India) ----
    "SIEMENS": {"name": "Siemens India", "yf": "SIEMENS.NS", "currency": "₹", "market": "IN",
                "sector": "Manufacturing", "peers": ["ABB"], "keywords": ["siemens"]},
    "ABB": {"name": "ABB India", "yf": "ABB.NS", "currency": "₹", "market": "IN",
            "sector": "Manufacturing", "peers": ["SIEMENS"], "keywords": ["abb"]},
    # ---- Automobile (India) ----
    "MARUTI": {"name": "Maruti Suzuki", "yf": "MARUTI.NS", "currency": "₹", "market": "IN",
               "sector": "Automobile", "peers": ["MM"], "keywords": ["maruti", "suzuki"]},
    "MM": {"name": "Mahindra & Mahindra", "yf": "M&M.NS", "currency": "₹", "market": "IN",
           "sector": "Automobile", "peers": ["MARUTI"], "keywords": ["mahindra"]},
    # ---- Global ----
    "MSFT": {"name": "Microsoft", "yf": "MSFT", "currency": "$", "market": "US",
             "sector": "Global Tech", "peers": ["NVDA"], "keywords": ["microsoft"]},
    "NVDA": {"name": "NVIDIA", "yf": "NVDA", "currency": "$", "market": "US",
             "sector": "Global Tech", "peers": ["MSFT"], "keywords": ["nvidia"]},
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
