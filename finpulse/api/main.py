from fastapi import FastAPI
import json 
from finpulse.storage.db import fetch_all
from finpulse.aggregation.aggregator import aggregate_sentiment , align
from finpulse.sentiment.ticker_tagger import ALIASES
app = FastAPI(title = "Finpulse API")

def to_records(df):
    return json.loads(df.reset_index().to_json(orient = "records", date_format ="iso"))
@app.get("/health")
def health():
    return{"status":"ok", "rows":len(fetch_all())}

@app.get("/sentiment/{ticker}")
def sentiment(ticker :str):
    return to_records(aggregate_sentiment(ticker, "1D" ))

@app.get("/alignment/{ticker}")
def alignment(ticker : str):
    return to_records(align(ticker))

@app.get("/tickers")
def tickers():
    return sorted(set(ALIASES.values()))

@app.get("/headlines")
def headlines(ticker : str| None = None, limit: int = 50):
    rows = fetch_all()

    if ticker:
        rows = [r for r in rows if  r[2] == ticker]
    rows = rows[-limit:]
    keys = ["id", "text", "ticker", "score", "label", "timestamp", "url"]
    return [dict(zip(keys, r)) for r in rows]

@app.get("/snapshot")
def snapshot():
    result = []
    for ticker in sorted(set(ALIASES.values())):
        df = aggregate_sentiment(ticker, "1D")
        df = df[df["count"] > 0]

        if df.empty:
            continue
        last = df.iloc[-1]
        result.append({
            "ticker" : ticker,
            "timestamp" : str(df.index[-1]),
            "mean" : float(last["mean"]),
            "count" : int(last["count"]),
        })
    return result