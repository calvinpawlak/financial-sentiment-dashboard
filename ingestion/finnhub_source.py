"""
Layer 1 - Finnhub ingestion: company news + aggregated social sentiment.

Requires a free Finnhub API key. Sign up at https://finnhub.io/register,
then set FINNHUB_API_KEY in your .env file (copy .env.example). Free tier
is 60 calls/min as of mid-2026 - plenty for 9 tickers x 2 endpoints on a
15-minute cycle.

Two independent endpoints, handled and stored differently:

  - /company-news: per-article headlines. Shaped exactly like FinViz/Google
    News output and flows through the same raw_news table + VADER scoring
    pipeline (processing/sentiment.py) - just another news source.

  - /stock/social-sentiment: Finnhub's own PRE-AGGREGATED Reddit/Twitter
    mention counts + positive/negative scores per ticker per day. This is
    NOT per-post text, so it can't be scored by VADER like raw_social/
    raw_news rows are. It's stored separately in raw_social_sentiment_agg
    and surfaced as a supplementary metric (report.py, dashboard) - it is
    deliberately NOT folded into the bullish/bearish/neutral counts from
    get_sentiment_summary(), since mixing a pre-scored aggregate with our
    own VADER-scored counts would muddy what those counts mean. This is
    the main way this pipeline gets a Reddit/Twitter-adjacent signal
    without needing our own (currently gated) Reddit API approval.

CONFIRMED 2026-07-12: /stock/social-sentiment returns 403 on a fresh
free-tier key - Finnhub has moved previously-free endpoints to premium-only
before without much notice (see finnhubio/Finnhub-API GitHub issue #271),
and this is apparently one of them now. fetch_all_social_sentiment() stops
after the first 403 instead of repeating the same failure (and burning an
API call) for every remaining ticker, every cycle. Company news is
unaffected - if you want the social-sentiment signal, it needs a paid
Finnhub plan; otherwise this whole feature just quietly contributes no
rows, and the dashboard/report already handle that (no line shown) rather
than erroring.

If FINNHUB_API_KEY is missing or still the .env.example placeholder text,
both fetch_all_* functions raise RuntimeError with setup instructions on
their first call - main.py catches this and skips Finnhub for that run.
"""
import logging
import os
from datetime import datetime, timezone, timedelta

import requests

from config.settings import TICKERS, FINNHUB_NEWS_DAYS_BACK

logger = logging.getLogger(__name__)

BASE_URL = "https://finnhub.io/api/v1"

# Same reasoning as reddit_source.py's _PLACEHOLDER_VALUES: catch the
# literal .env.example placeholder text so a straight `cp .env.example .env`
# fails fast with a clear message instead of making a doomed real request.
_PLACEHOLDER_VALUES = {"", "your_finnhub_api_key_here"}


class _PremiumRequired(Exception):
    """Internal signal: Finnhub returned 403 for this endpoint. Confirmed
    2026-07-12 (Calvin's first real run) that /stock/social-sentiment is
    now paid-only even on a fresh free-tier key - this is an account/plan
    restriction, not a per-ticker problem, so fetch_all_social_sentiment
    stops after the first 403 instead of repeating the same failure (and
    burning a call) for every remaining ticker, every single cycle."""


def _get_api_key() -> str:
    api_key = (os.environ.get("FINNHUB_API_KEY") or "").strip()
    if api_key in _PLACEHOLDER_VALUES:
        raise RuntimeError(
            "FINNHUB_API_KEY is missing or still set to the .env.example "
            "placeholder value. Sign up for a free key at "
            "https://finnhub.io/register and drop it into .env - Finnhub "
            "ingestion (company news + social sentiment) will start working "
            "automatically next cycle, no code changes needed."
        )
    return api_key


def fetch_company_news(ticker: str, days_back: int = None):
    """Per-article headlines for one ticker over the last `days_back` days,
    shaped for storage.db.insert_news() (same shape as ingestion/news.py
    and ingestion/google_news_source.py)."""
    api_key = _get_api_key()
    days_back = FINNHUB_NEWS_DAYS_BACK if days_back is None else days_back
    today = datetime.now(timezone.utc).date()
    from_date = today - timedelta(days=days_back)
    ingested_at = datetime.now(timezone.utc).isoformat()

    try:
        resp = requests.get(
            f"{BASE_URL}/company-news",
            params={
                "symbol": ticker,
                "from": from_date.isoformat(),
                "to": today.isoformat(),
                "token": api_key,
            },
            timeout=10,
        )
        if resp.status_code == 403:
            logger.warning(
                "Finnhub company-news returned 403 for '%s' - bad key, or this "
                "endpoint has moved to a paid plan since this was written. Skipping.",
                ticker,
            )
            return []
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Finnhub company-news fetch failed for '%s': %s", ticker, exc)
        return []

    try:
        articles = resp.json()
    except ValueError:
        logger.error("Finnhub company-news returned non-JSON for '%s'.", ticker)
        return []

    if not isinstance(articles, list):
        logger.warning("Unexpected Finnhub company-news response shape for '%s': %r", ticker, articles)
        return []

    out = []
    for item in articles:
        headline = (item.get("headline") or "").strip()
        url = item.get("url")
        if not headline or not url:
            continue
        published_ts = item.get("datetime")
        published_at = (
            datetime.fromtimestamp(published_ts, tz=timezone.utc).isoformat()
            if published_ts
            else None
        )
        out.append(
            {
                "ticker": ticker,
                "source": "finnhub",
                "title": headline,
                "link": url,
                "published_at": published_at,
                "ingested_at": ingested_at,
            }
        )
    return out


def fetch_all_company_news(tickers=None, days_back: int = None):
    tickers = tickers or TICKERS
    out = []
    for ticker in tickers:
        out.extend(fetch_company_news(ticker, days_back=days_back))
    return out


def fetch_social_sentiment(ticker: str):
    """Finnhub's pre-aggregated Reddit/Twitter mention+sentiment rollup for
    one ticker - NOT per-post text (see module docstring). Returns a list
    of dicts, one per (platform, period) Finnhub reports, shaped for
    storage.db.insert_social_sentiment_agg()."""
    api_key = _get_api_key()
    fetched_at = datetime.now(timezone.utc).isoformat()

    try:
        resp = requests.get(
            f"{BASE_URL}/stock/social-sentiment",
            params={"symbol": ticker, "token": api_key},
            timeout=10,
        )
        if resp.status_code == 403:
            raise _PremiumRequired(ticker)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Finnhub social-sentiment fetch failed for '%s': %s", ticker, exc)
        return []

    try:
        data = resp.json()
    except ValueError:
        logger.error("Finnhub social-sentiment returned non-JSON for '%s'.", ticker)
        return []

    if not isinstance(data, dict):
        logger.warning("Unexpected Finnhub social-sentiment response shape for '%s': %r", ticker, data)
        return []

    out = []
    for platform in ("reddit", "twitter"):
        for entry in data.get(platform, []) or []:
            out.append(
                {
                    "ticker": ticker,
                    "platform": platform,
                    "period": entry.get("atTime"),
                    "mention": entry.get("mention"),
                    "positive_score": entry.get("positiveScore"),
                    "negative_score": entry.get("negativeScore"),
                    "positive_mention": entry.get("positiveMention"),
                    "negative_mention": entry.get("negativeMention"),
                    "fetched_at": fetched_at,
                }
            )
    return out


def fetch_all_social_sentiment(tickers=None):
    tickers = tickers or TICKERS
    out = []
    for ticker in tickers:
        try:
            out.extend(fetch_social_sentiment(ticker))
        except _PremiumRequired:
            logger.warning(
                "Finnhub /stock/social-sentiment returned 403 - this endpoint isn't "
                "included in your current Finnhub plan (confirmed 2026-07-12: it's "
                "paid-only, even on a fresh free-tier key). Stopping social-sentiment "
                "calls for the rest of this cycle rather than repeating the same "
                "failure for every remaining ticker. Company news is unaffected - "
                "upgrade your Finnhub plan if you want this signal, otherwise it's "
                "safe to ignore; the dashboard already handles having no data here."
            )
            break
    return out
