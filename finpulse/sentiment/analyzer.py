"""Sentiment scoring with a finance-trained model (FinBERT) and a safe VADER fallback.

Public interface (unchanged — everything downstream depends on these two):
  score(text) -> float in -1..+1   (compound: negative .. positive)
  label(text) -> "positive" | "negative" | "neutral"

Engine selection (env var SENTIMENT_ENGINE):
  "finbert" (default) -> ProsusAI/finbert, falls back to VADER on ANY failure
  "vader"             -> force the original VADER scorer

FinBERT is lazy-loaded (only when first needed) and any error -> VADER, so a
sentiment call can never crash the app. The model lives on D: (see HF_HOME below)
to spare the tiny C: drive.
"""

import os
from functools import lru_cache

# Point HuggingFace at the D: cache where the model was installed (C: is nearly full).
os.environ.setdefault("HF_HOME", r"d:\finance_news_project\.cache\hf")

# --- VADER (original scorer, kept intact as the fallback) -------------------
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

FINANCE_LEXICON = {
    "soars": 3.0, "soared": 3.0, "rally": 2.0, "upgrade": 2.0, "bullish": 2.5,
    "layoffs": -2.5, "plunge": -3.0, "downgrade": -2.0, "bearish": -2.5, "slump": -2.0,
    "surge": 2.5, "surges": 2.5, "plunges": -3.0, "plunged": -3.0, "slumps": -2.0,
    "slumped": -2.0, "selloff": -2.0, "recall": -1.5, "recalls": -1.5,
}
_vader = SentimentIntensityAnalyzer()
_vader.lexicon.update(FINANCE_LEXICON)


def _vader_score(text):
    return _vader.polarity_scores(text)["compound"]


# --- FinBERT (finance-trained, lazy-loaded) --------------------------------
ENGINE = os.environ.get("SENTIMENT_ENGINE", "finbert").lower()
_FINBERT = {"tok": None, "mod": None, "ok": None}  # ok: None=untried, True/False=result


def _load_finbert():
    """Load FinBERT once. Returns True if usable, False if we should use VADER."""
    if _FINBERT["ok"] is None:
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            name = "ProsusAI/finbert"
            _FINBERT["tok"] = AutoTokenizer.from_pretrained(name)
            _FINBERT["mod"] = AutoModelForSequenceClassification.from_pretrained(name)
            _FINBERT["ok"] = True
        except Exception as e:
            print(f"[sentiment] FinBERT unavailable -> using VADER ({e})")
            _FINBERT["ok"] = False
    return _FINBERT["ok"]


def _finbert_score(text):
    """Map FinBERT class probabilities to a -1..+1 compound: P(pos) - P(neg)."""
    import torch
    tok, mod = _FINBERT["tok"], _FINBERT["mod"]
    with torch.no_grad():
        logits = mod(**tok(text, return_tensors="pt", truncation=True, max_length=256))[0]
        probs = torch.softmax(logits, dim=1)[0]
        idx = mod.config.label2id
        return float(probs[idx["positive"]] - probs[idx["negative"]])


@lru_cache(maxsize=8192)
def _analyze(text):
    """Compound score, cached. FinBERT if enabled+working, else VADER. Never raises."""
    if ENGINE == "finbert" and _load_finbert():
        try:
            return _finbert_score(text)
        except Exception:
            return _vader_score(text)   # any per-call failure -> safe fallback
    return _vader_score(text)


def score(text):
    return _analyze(text)


def label(text):
    c = _analyze(text)
    if c >= 0.05:
        return "positive"
    elif c <= -0.05:
        return "negative"
    else:
        return "neutral"
