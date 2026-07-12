"""
Central configuration for the Financial Sentiment Dashboard.
Edit TICKERS and REFRESH_INTERVAL_MINUTES here as your watchlist evolves.
"""

import os

# --- Ticker universe -------------------------------------------------------
# Pulled from the initial watchlist. Updated 2026-07-12:
#   - SPCX: confirmed VALID. This is Space Exploration Technologies Corp
#           (SpaceX), which IPO'd on Nasdaq on 2026-06-12 - it's simply a
#           very new listing, not an invalid ticker.
#   - INX:  confirmed dead/invalid ("$INX: possibly delisted; no price data
#           found" from Yahoo itself) and dropped from the list. Briefly
#           tried ^GSPC (the real Yahoo symbol for the S&P 500 index) as a
#           replacement, but StockTwits/FinViz don't carry index-level
#           pages, so it would only ever get partial (price-only) coverage.
#           Dropped rather than kept as a partial-coverage entry - SPY
#           already tracks the S&P 500 closely and has full 3-source
#           coverage, so nothing is lost by not tracking the raw index too.
TICKERS = [
    "SPY",     # SPDR S&P 500 ETF
    "QQQ",     # Invesco QQQ (Nasdaq-100 ETF)
    "MSFT",    # Microsoft
    "AAPL",    # Apple
    "GOOG",    # Alphabet (Class C)
    "NVDA",    # Nvidia
    "NDAQ",    # Nasdaq, Inc. (the exchange operator company, not an index)
    "VOO",     # Vanguard S&P 500 ETF
    "SPCX",    # Space Exploration Technologies Corp (SpaceX) - confirmed valid, IPO'd 2026-06-12
]

# Friendly names / extra search terms used when scanning Reddit post text
# for mentions, since cashtags alone sometimes under-match.
TICKER_ALIASES = {
    "SPY": ["S&P 500", "SPY"],
    "QQQ": ["Nasdaq 100", "QQQ"],
    "MSFT": ["Microsoft", "MSFT"],
    "AAPL": ["Apple", "AAPL"],
    "GOOG": ["Google", "Alphabet", "GOOG", "GOOGL"],
    "NVDA": ["Nvidia", "NVDA"],
    "NDAQ": ["Nasdaq Inc", "NDAQ"],
    "VOO": ["Vanguard S&P 500", "VOO"],
    "SPCX": ["SPCX"],
}

# --- Scheduling --------------------------------------------------------
# Split cadence, added 2026-07-12 (Calvin asked for 5-minute scanning, but
# FinViz only updates news ~every 30 min and its terms discourage
# high-frequency automated hits - and Google News RSS is unofficial with no
# documented rate limit either. Polling either one every 5 min would just
# refetch the same headlines 3x as often for no new data, while raising
# scraping-detection risk. So the fast sources (prices, StockTwits, Reddit,
# Finnhub) run every 5 min; the scraped/slower news sources (FinViz, Google
# News) keep the original 15-min cadence. See `python main.py --fast-only`
# / `--slow-only` and setup_task_scheduler.ps1, which now registers two
# separate scheduled tasks. These values aren't enforced by the script
# itself (the OS scheduler controls actual timing) - they're here so other
# parts of the pipeline can reference the expected cadence.
FAST_REFRESH_INTERVAL_MINUTES = 5   # prices, StockTwits, Reddit, Finnhub
SLOW_REFRESH_INTERVAL_MINUTES = 15  # FinViz, Google News (scraped/unofficial)

# --- Reddit ----------------------------------------------------------------
SUBREDDITS = ["wallstreetbets", "stocks", "investing", "StockMarket"]
REDDIT_POST_LIMIT = 25  # posts scanned per subreddit per run
REDDIT_USER_AGENT = "financial-sentiment-dashboard/0.1 by u/your_username"

# --- StockTwits --------------------------------------------------------
# StockTwits' unauthenticated public endpoint is rate-limited (roughly
# 200 requests/hour per IP as of this writing). With 10 tickers, don't run
# this more often than every 5 minutes or you'll start getting 429s.
STOCKTWITS_MESSAGE_LIMIT = 30

# --- Google News RSS (added 2026-07-12) ---------------------------------
# No key required. Caps headlines per ticker per cycle - with three news
# sources now (FinViz, Finnhub, Google News) all deduping into the same
# raw_news table, there's no need to pull deep history from any single one.
GOOGLE_NEWS_HEADLINE_LIMIT = 15

# --- Finnhub (added 2026-07-12) -----------------------------------------
# Free API key from https://finnhub.io/register, set as FINNHUB_API_KEY in
# .env (see .env.example). Free tier is 60 calls/min as of mid-2026 - plenty
# for this ticker list across both endpoints on a 15-min cycle. Used for:
#   - /company-news: another free news headline source (raw_news)
#   - /stock/social-sentiment: Finnhub's own aggregated Reddit/Twitter
#     mention+sentiment rollup - the main way this pipeline gets a
#     Reddit/Twitter-adjacent signal without our own gated Reddit API access
# How many days of company news to request each cycle - a small window is
# fine since raw_news dedupes on link, so re-requesting overlapping days
# just costs a wasted call, not duplicate rows.
FINNHUB_NEWS_DAYS_BACK = 2

# --- Storage -----------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_PROJECT_ROOT, "data", "sentiment_dashboard.db")
LOG_PATH = os.path.join(_PROJECT_ROOT, "logs", "ingestion.log")
