"""Federal Reserve macro events from official RSS feeds."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

FEEDS = {
    "press_release": "https://www.federalreserve.gov/feeds/press_all.xml",
    "monetary_policy": "https://www.federalreserve.gov/feeds/press_monetary.xml",
    "speech": "https://www.federalreserve.gov/feeds/speeches.xml",
}


def _text(item, tag):
    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""


def fetch_events(limit_per_feed=20):
    ingested_at = datetime.now(timezone.utc).isoformat()
    events = []
    for category, url in FEEDS.items():
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        for item in root.findall(".//item")[:limit_per_feed]:
            title, link, published = _text(item, "title"), _text(item, "link"), _text(item, "pubDate")
            if not title or not link:
                continue
            try:
                published_at = parsedate_to_datetime(published).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                published_at = published or None
            events.append({
                "ticker": None, "source": "federal_reserve", "category": category,
                "title": title, "link": link, "published_at": published_at,
                "ingested_at": ingested_at,
            })
    return events
