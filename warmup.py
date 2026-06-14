"""Pre-fetch all yfinance-derived data into the PERSISTENT on-disk cache.

Why: yfinance rate-limits, so a live demo/presentation shouldn't fetch at click-time. Run this
when yfinance is CALM (e.g. the morning of the presentation). Afterwards the dashboard serves the
cached data even if Yahoo rate-limits mid-demo (the cache is stale-tolerant), so fundamentals,
charts, and the sector views never show NA.

It's safe to re-run: cached results are reused, so a second run just fills whatever the first
missed (e.g. if Yahoo throttled partway).

Run from the repo root:  python warmup.py
"""

import time
import warnings

warnings.filterwarnings("ignore")

import finpulse.dashboard.app as dash_app
from config import TICKERS

TFS = ["Daily", "Weekly", "1 Month", "3 Months", "6 Months"]


def warmup():
    # Fundamentals FIRST — the most rate-limit-prone (yf .info) and the one that showed NA.
    print("[1/4] Fundamentals (all tickers) + sector metrics ...", flush=True)
    dash_app.sector_metrics()

    print("[2/4] Home (prices + market mood) ...", flush=True)
    dash_app.build_home_content()

    print("[3/4] Sector comparison charts ...", flush=True)
    for tf in ["1 Month", "3 Months", "6 Months"]:
        dash_app.build_sector_comparison(list(dash_app.SECTORS.keys()), dash_app.TIMEFRAMES[tf])

    print("[4/4] Analytics charts per ticker x timeframe ...", flush=True)
    ok = 0
    for t in TICKERS:
        for tf in TFS:
            try:
                dash_app.update_charts(t, tf, 0)
                ok += 1
            except Exception as e:
                print(f"   {t}/{tf}: {e}", flush=True)
        print(f"   cached {t}", flush=True)
        time.sleep(1.5)        # be gentle on yfinance

    print(f"done — {ok} chart views + fundamentals + prices cached to disk.", flush=True)


if __name__ == "__main__":
    warmup()
