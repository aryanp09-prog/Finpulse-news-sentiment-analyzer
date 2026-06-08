from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
analyzer = SentimentIntensityAnalyzer()

FINANCE_LEXICON = {
    "soars": 3.0,
    "soared":3.0,
    "rally": 2.0,
    "upgrade": 2.0,
    "bullish": 2.5,
    "layoffs": -2.5,
    "plunge": -3.0,
    "downgrade": -2.0,
    "bearish": -2.5,
    "slump": -2.0,
    "surge": 2.5,
    "surges":2.5,
    "plunges":-3.0,
    "plunged":-3.0,
    "slumps":-2.0,
    "slumped":-2.0,
    "selloff":-2.0,
    "recall":-1.5,
    "recalls":-1.5,
}
analyzer.lexicon.update(FINANCE_LEXICON)

def score(text):
    return analyzer.polarity_scores(text)["compound"]

def label(text):
    c = score(text)
    if c >=0.05:
        return "positive"
    elif c<= -0.05:
        return "negative"
    else:
        return "neutral"
