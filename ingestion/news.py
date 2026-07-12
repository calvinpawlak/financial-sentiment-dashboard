"""
Layer 1 - free news headline ingestion via FinViz's per-ticker news table.

Why FinViz instead of a news API: it's free, updates roughly every 30
minutes, and is the approach used by comparable open-source projects
(e.g. SaloniJhalani/Stock-Market-Live-Sentiment) - Yahoo Finance's old RSS
feeds are largely defunct at this point, so a paid news API or this scrape
are the realistic free options.

Caveat: this is HTML scraping, not a stable API contract. FinViz's terms
restrict heavy automated/commercial use - keep this to a low, personal-use
frequency (e.g. every 15-30 min, matching their own update cadence), and if
parsing suddenly returns nothing, FinViz likely changed their page markup
and the CSS selector below (`table#news-table`) will need updating.
"""
import logging
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from config.settings import TICKERS

logger = logging.getLogger(__name__)

FINVIZ_URL = "https://finviz.com/quote.ashx?t={symbol}"
HEADERS = {
    # FinViz blocks requests with no/obviously-scripted user agent.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def fetch_headlines(ticker: str):
    # quote() so tickers with special characters (e.g. "^GSPC") end up
    # correctly percent-encoded ("%5EGSPC") instead of raw in the URL.
    url = FINVIZ_URL.format(symbol=quote(ticker, safe=""))
    ingested_at = datetime.now(timezone.utc).isoformat()

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code == 404:
            logger.warning("FinViz has no quote page for '%s' - likely an invalid ticker.", ticker)
            return []
        resp.raise_for_status()
    except Exception as exc:
        logger.error("News fetch failed for '%s': %s", ticker, exc)
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    news_table = soup.find(id="news-table")
    if news_table is None:
        logger.warning(
            "Could not find the news table for '%s' - FinViz may have changed "
            "their page markup, or this ticker has no news history.", ticker
        )
        return []

    out = []
    last_date = None
    for row in news_table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        timestamp_text = cells[0].get_text(strip=True)
        link_tag = cells[1].find("a")
        if link_tag is None:
            continue

        # FinViz only prints the date on the first headline of each day;
        # subsequent rows that day show only the time.
        if len(timestamp_text) > 8:  # e.g. "Jul-12-26 09:31AM"
            parts = timestamp_text.split(" ")
            last_date = parts[0]
            time_part = parts[1] if len(parts) > 1 else ""
        else:
            time_part = timestamp_text

        published_at = f"{last_date} {time_part}".strip()

        out.append({
            "ticker": ticker,
            "source": "finviz",
            "title": link_tag.get_text(strip=True),
            "link": link_tag.get("href"),
            "published_at": published_at,
            "ingested_at": ingested_at,
        })

    return out


def fetch_all_headlines(tickers=None):
    tickers = tickers or TICKERS
    all_headlines = []
    for ticker in tickers:
        all_headlines.extend(fetch_headlines(ticker))
    return all_headlines
