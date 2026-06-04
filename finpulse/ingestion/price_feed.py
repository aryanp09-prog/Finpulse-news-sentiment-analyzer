import yfinance as yf
yf.set_tz_cache_location("D:/yf_cache")

data= yf.download("AAPL", period = "5d", interval = "1d")
print(data)
print(data.columns)
print(data.index)