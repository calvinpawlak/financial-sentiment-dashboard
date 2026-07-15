"""Bluesky social-post ingestion through the official authenticated API.

Ticker search currently requires authentication. Use a Bluesky app password
rather than the account's primary password. Missing/placeholder credentials
raise RuntimeError so main.py can skip this optional source cleanly.
"""
import os
from datetime import datetime, timezone

import requests

from config.settings import BLUESKY_POST_LIMIT, TICKERS

SESSION_URL = "https://bsky.social/xrpc/com.atproto.server.createSession"
SEARCH_URL = "https://bsky.social/xrpc/app.bsky.feed.searchPosts"
_PLACEHOLDERS = {"", "your_bluesky_handle_here", "your_bluesky_app_password_here"}


def _credentials():
    handle = (os.environ.get("BLUESKY_HANDLE") or "").strip()
    app_password = (os.environ.get("BLUESKY_APP_PASSWORD") or "").strip()
    if handle in _PLACEHOLDERS or app_password in _PLACEHOLDERS:
        raise RuntimeError(
            "BLUESKY_HANDLE / BLUESKY_APP_PASSWORD are missing or still set "
            "to placeholder values. Create a Bluesky app password, add both "
            "values to .env, and Bluesky ingestion will start automatically."
        )
    return handle, app_password


def _create_session():
    handle, app_password = _credentials()
    response = requests.post(
        SESSION_URL,
        json={"identifier": handle, "password": app_password},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    access_jwt = payload.get("accessJwt")
    if not access_jwt:
        raise RuntimeError("Bluesky authentication succeeded without an access token.")
    return access_jwt


def fetch_posts(tickers=None, limit=None):
    tickers = tickers or TICKERS
    limit = BLUESKY_POST_LIMIT if limit is None else limit
    access_jwt = _create_session()
    headers = {"Authorization": f"Bearer {access_jwt}"}
    ingested_at = datetime.now(timezone.utc).isoformat()
    results = []

    for ticker in tickers:
        response = requests.get(
            SEARCH_URL,
            headers=headers,
            params={"q": f"${ticker}", "limit": limit, "sort": "latest"},
            timeout=15,
        )
        response.raise_for_status()
        for post in response.json().get("posts", []):
            record = post.get("record") or {}
            text = (record.get("text") or "").strip()
            uri = post.get("uri")
            author = post.get("author") or {}
            handle = author.get("handle")
            if not text or not uri:
                continue
            rkey = uri.rsplit("/", 1)[-1]
            results.append(
                {
                    "ticker": ticker,
                    "source": "bluesky",
                    "external_id": uri,
                    "author": handle,
                    "text": text[:2000],
                    "url": f"https://bsky.app/profile/{handle}/post/{rkey}" if handle else None,
                    "created_at": record.get("createdAt"),
                    "ingested_at": ingested_at,
                }
            )
    return results
