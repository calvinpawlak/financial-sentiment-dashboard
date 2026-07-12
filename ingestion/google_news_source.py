"""
Layer 1 - free news headline ingestion via Google News' unofficial RSS
search feed. No API key, no signup, no published rate limit - a second,
independent news source alongside FinViz and Finnhub, so a format change
or outage in one source doesn't take down news coverage entirely.

Caveat: this is an unofficial feed, not a documented/stable contract -
Google could change or retire it without notice, same fragility class as
the FinViz HTML scrape (see README's "Known fragility" section). If this
starts returning zero headlines for everything, check whether
https://news.google.com/rss/search?q=test still returns an RSS feed in a
browser before assuming the code broke.
"""
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from config.settings import TICKERS, GOOGLE_NEWS_HEADLINE_LIMIT

logger = logging.getLogger(__name__)

RSS_URL = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _parse_pub_date(raw: str):
    """Google News RSS uses RFC 2822 dates, e.g. 'Sat, 12 Jul 2026 14:03:00 GMT'.
    Falls back to the raw string (rather than dropping it) if the format
    ever shifts, since a rough timestamp is still better than nothing."""
    if not raw:
        return None
    try:
        return (
            datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S %Z")
            .replace(tzinfo=timezone.utc)
            .isoformat()
        )
    except ValueError:
        return raw


def fetch_headlines(ticker: str, limit: int = None):
    limit = GOOGLE_NEWS_HEADLINE_LIMIT if limit is None else limit
    query = quote(f"{ticker} stock", safe="")
    url = RSS_URL.format(query=query)
    ingested_at = datetime.now(timezone.utc).isoformat()

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Google News fetch failed for '%s': %s", ticker, exc)
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        logger.error("Google News RSS parse failed for '%s': %s", ticker, exc)
        return []

    out = []
    items = root.findall("./channel/item")[:limit]
    for item in items:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        out.append(
            {
                "ticker": ticker,
                "source": "google_news",
                "title": title,
                "link": link,
                "published_at": _parse_pub_date(item.findtext("pubDate")),
                "ingested_at": ingested_at,
            }
        )
    return out


def fetch_all_headlines(tickers=None, limit: int = None):
    tickers = tickers or TICKERS
    out = []
    for ticker in tickers:
        out.extend(fetch_headlines(ticker, limit=limit))
    return out
