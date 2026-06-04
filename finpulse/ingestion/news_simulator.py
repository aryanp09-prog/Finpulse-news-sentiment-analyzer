import json

headlines = [
    "Apple shares soared after record iPhone sales",          # AAPL  positive
    "Tesla rally continues as deliveries surge",              # TSLA  positive
    "Microsoft announces layoffs across its cloud division",  # MSFT  negative
    "Google unveils a new AI agent at its conference",        # GOOGL neutral/slightly +
    "Amazon stock plunges on weak holiday guidance",          # AMZN  negative
    "Nvidia surges to a record high on AI chip demand",       # NVDA  positive
    "Meta downgrade weighs on the stock today",               # META  negative
    "Netflix subscriber growth slumps this quarter",          # NFLX  negative
    "Apple upgrade lifts optimism among analysts",            # AAPL  positive
    "Tesla recalls thousands of vehicles over safety issues", # TSLA  negative
    "Microsoft posts strong earnings and beats estimates",    # MSFT  positive
    "Google faces an antitrust lawsuit from regulators",      # GOOGL negative
    "Amazon expands its warehouse network nationwide",        # AMZN  neutral
    "Nvidia bearish outlook spooks investors",                # NVDA  negative
    "Meta turns bullish on its new VR headset launch",        # META  positive
    "Netflix announces new subscription pricing tiers",       # NFLX  neutral
    "Apple and Microsoft partner on enterprise AI",           # AAPL + MSFT  positive
    "Tesla and Nvidia collaborate on self-driving chips",     # TSLA + NVDA  neutral/+
    "Amazon downgrade triggers a sharp selloff",              # AMZN  negative
    "Google stock steadies after a volatile week",            # GOOGL neutral
]

def get_headlines():
    return headlines