"""
Layer 1 - Reddit ingestion via PRAW.

Requires a free Reddit API app (script type). Create one at
https://www.reddit.com/prefs/apps, then set these in a .env file
(copy .env.example) or as environment variables:
    REDDIT_CLIENT_ID
    REDDIT_CLIENT_SECRET

If these aren't set (or are still the .env.example placeholder text),
fetch_posts() raises a RuntimeError with setup instructions rather than
crashing the whole ingestion cycle - main.py catches this and skips Reddit
for that run.

As of mid-2026, Reddit gates new API credentials behind a manual approval
process (its "Responsible Builder Policy") - if you've filed a request but
haven't heard back yet, this module will just keep skipping Reddit cleanly
until real credentials are in place.
"""
import logging
import os
from datetime import datetime, timezone

import praw

from config.settings import SUBREDDITS, REDDIT_POST_LIMIT, REDDIT_USER_AGENT, TICKER_ALIASES, TICKERS

logger = logging.getLogger(__name__)

_reddit_client = None

# The literal placeholder text from .env.example. If someone just copies
# that file to .env without editing it, these values are non-empty strings
# and would otherwise sail past a plain "is it empty" check straight into a
# real (and doomed) OAuth call against Reddit, which returns a 401 for
# every subsequent request rather than failing fast with a clear message.
_PLACEHOLDER_VALUES = {"", "your_client_id_here", "your_client_secret_here"}


def get_client():
    global _reddit_client
    if _reddit_client is None:
        client_id = (os.environ.get("REDDIT_CLIENT_ID") or "").strip()
        client_secret = (os.environ.get("REDDIT_CLIENT_SECRET") or "").strip()
        if client_id in _PLACEHOLDER_VALUES or client_secret in _PLACEHOLDER_VALUES:
            raise RuntimeError(
                "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are missing or still "
                "set to the .env.example placeholder values. If you've filed "
                "a Reddit API access request, this is expected until it's "
                "approved - once you get real credentials, drop them into "
                ".env and Reddit ingestion will start working automatically, "
                "no code changes needed."
            )
        _reddit_client = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=REDDIT_USER_AGENT,
        )
        _reddit_client.read_only = True
    return _reddit_client


def _mentions_ticker(text: str, ticker: str) -> bool:
    text_upper = f" {text.upper()} "
    if f"${ticker}" in text_upper or f" {ticker} " in text_upper:
        return True
    for alias in TICKER_ALIASES.get(ticker, []):
        if alias.upper() in text_upper:
            return True
    return False


def fetch_posts(tickers=None, subreddits=None):
    tickers = tickers or TICKERS
    subreddits = subreddits or SUBREDDITS
    reddit = get_client()
    ingested_at = datetime.now(timezone.utc).isoformat()
    results = []

    for sub_name in subreddits:
        try:
            subreddit = reddit.subreddit(sub_name)
            for post in subreddit.new(limit=REDDIT_POST_LIMIT):
                combined_text = f"{post.title} {post.selftext or ''}"
                for ticker in tickers:
                    if _mentions_ticker(combined_text, ticker):
                        results.append({
                            "ticker": ticker,
                            "source": "reddit",
                            "external_id": post.id,
                            "author": str(post.author) if post.author else None,
                            "text": combined_text[:2000],
                            "url": f"https://reddit.com{post.permalink}",
                            "created_at": datetime.fromtimestamp(post.created_utc, tz=timezone.utc).isoformat(),
                            "ingested_at": ingested_at,
                        })
        except Exception as exc:
            logger.error("Reddit fetch failed for r/%s: %s", sub_name, exc)

    return results
