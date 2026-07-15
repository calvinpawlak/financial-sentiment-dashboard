"""Layer 1 - StockTwits ingestion via its legacy symbol-stream endpoint.

The unauthenticated endpoint began returning HTTP 403 on 2026-07-15 while
StockTwits' official developer page said API registrations were paused.
Stop after the first 403 each cycle rather than sending one denied request
per ticker. Other ingestion sources continue normally.
"""
import logging
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from config.settings import TICKERS, STOCKTWITS_MESSAGE_LIMIT

logger = logging.getLogger(__name__)

BASE_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"


class StockTwitsAccessDenied(RuntimeError):
    """The legacy unauthenticated API is not available to this project."""


def fetch_messages(ticker: str):
    # quote() so tickers with special characters (e.g. "^GSPC") end up
    # correctly percent-encoded ("%5EGSPC") instead of raw in the URL.
    url = BASE_URL.format(symbol=quote(ticker, safe=""))
    try:
        resp = requests.get(
            url, timeout=10,
            headers={"User-Agent": "financial-sentiment-dashboard/0.1"},
        )
        if resp.status_code == 429:
            logger.warning("StockTwits rate limit hit for '%s' - slow down the schedule.", ticker)
            return []
        if resp.status_code == 404:
            logger.warning("StockTwits has no symbol stream for '%s' - likely an invalid ticker.", ticker)
            return []
        if resp.status_code == 403:
            raise StockTwitsAccessDenied(
                "StockTwits denied the legacy unauthenticated API (HTTP 403). "
                "Approved API access is required; skipping StockTwits for this cycle."
            )
        resp.raise_for_status()
        data = resp.json()
    except StockTwitsAccessDenied:
        raise
    except Exception as exc:
        logger.error("StockTwits fetch failed for '%s': %s", ticker, exc)
        return []

    messages = data.get("messages", [])[:STOCKTWITS_MESSAGE_LIMIT]
    ingested_at = datetime.now(timezone.utc).isoformat()

    out = []
    for m in messages:
        out.append({
            "ticker": ticker,
            "source": "stocktwits",
            "external_id": str(m.get("id")),
            "author": (m.get("user") or {}).get("username"),
            "text": m.get("body"),
            "url": f"https://stocktwits.com/message/{m.get('id')}",
            "created_at": m.get("created_at"),
            "ingested_at": ingested_at,
        })
    return out


def fetch_all_messages(tickers=None):
    tickers = tickers or TICKERS
    all_messages = []
    for ticker in tickers:
        try:
            all_messages.extend(fetch_messages(ticker))
        except StockTwitsAccessDenied as exc:
            logger.warning("%s", exc)
            break
    return all_messages
