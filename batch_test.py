"""Milestone 2 batch eyeball test.

The ONLY place that wires the stages together — modules stay pure and don't
import each other. This is the seed of finpulse/pipeline/runner.py (Milestone 3).

Run from the repo root:  python batch_test.py
"""

from finpulse.ingestion.news_simulator import get_headlines
from finpulse.sentiment.analyzer import score, label
from finpulse.sentiment.ticker_tagger import tag

print(f"{'score':>6}  {'label':8s}  {'tickers':10s}  headline")
print("-" * 80)

for h in get_headlines():
    tickers = ",".join(tag(h)) or "-"
    print(f"{score(h):+6.3f}  {label(h):8s}  {tickers:10s}  {h}")
