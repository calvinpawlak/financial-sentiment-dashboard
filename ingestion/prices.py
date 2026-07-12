"""
Layer 1 - price ingestion via yfinance (free, no API key required).
Pulls a recent daily quote snapshot for each configured ticker.

Uses t.history() rather than t.fast_info. fast_info's dict-style access
uses different key casing internally than its attribute-style access, and
has had several breaking changes upstream (see ranaroussi/yfinance issues
#1518, #1636, #1951) - it was returning None for every ticker here,
including obviously-valid ones like AAPL/MSFT, which is what tipped us off
that it was a library/key-mismatch issue rather than 10 bad tickers.
history() is a slightly heavier call but has been far more stable.
"""
import logging
from datetime import datetime, timezone

import yfinance as yf

from config.settings import TICKERS

logger = logging.getLogger(__name__)


def fetch_quote(ticker: str):
    """Fetch a recent quote for one ticker. Returns None (and logs a
    warning) if the ticker doesn't resolve to real market data."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="5d", interval="1d", auto_adjust=False)

        if hist.empty:
            logger.warning(
                "No price history returned for '%s' - this ticker may not be "
                "a valid/tradable symbol, or (if very recently IPO'd) Yahoo's "
                "data may not have caught up yet. Verify it on "
                "finance.yahoo.com before relying on it.", ticker
            )
            return None

        price = float(hist["Close"].iloc[-1])
        vol_val = hist["Volume"].iloc[-1]
        volume = int(vol_val) if vol_val == vol_val else None  # NaN check without pandas import

        prev_close = None
        if len(hist) > 1:
            prev_close = float(hist["Close"].iloc[-2])

        day_change_pct = None
        if prev_close:
            day_change_pct = ((price - prev_close) / prev_close) * 100

        return {
            "ticker": ticker,
            "price": price,
            "day_change_pct": day_change_pct,
            "volume": volume,
            "source": "yfinance",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error("Price fetch failed for '%s': %s", ticker, exc)
        return None


def fetch_all_quotes(tickers=None):
    tickers = tickers or TICKERS
    results = []
    for ticker in tickers:
        quote = fetch_quote(ticker)
        if quote:
            results.append(quote)
    return results
