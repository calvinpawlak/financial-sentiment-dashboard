"""
Entry point for one ingestion cycle. Run this on a schedule (cron on
Mac/Linux, Task Scheduler on Windows) to build up continuous history.
See README.md for setup and scheduling instructions.

Split cadence, added 2026-07-12:
    python main.py               # everything (manual/full run)
    python main.py --fast-only   # prices, StockTwits, Reddit, Finnhub - for a 5-min schedule
    python main.py --slow-only   # FinViz, Google News - for a 15-min schedule

Why split: FinViz only updates news ~every 30 min and its terms discourage
high-frequency automated hits; Google News RSS is unofficial with no
documented rate limit either. Polling either one every 5 min would just
refetch the same headlines 3x as often for no new data. The other sources
(yfinance, StockTwits, Reddit, Finnhub) all comfortably support 5 minutes.
setup_task_scheduler.ps1 registers two separate scheduled tasks matching
this split.

Signal logging + accuracy grading (processing/signal_tracking.py) runs
every cycle regardless of mode - it only reads data already accumulated in
the database, so it doesn't matter which sources just ran.
"""
import argparse
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from config.settings import LOG_PATH, TICKERS
from storage.db import (
    init_db, get_conn, insert_price, insert_social, insert_news,
    insert_social_sentiment_agg,
)
from storage.queries import get_known_tickers, get_latest_prices, get_signal
from ingestion import prices, stocktwits, reddit_source, news, finnhub_source, google_news_source
from processing import sentiment, signal_tracking


def setup_logging():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH),
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_cycle(mode: str = "full"):
    """mode: 'full' (everything, manual runs), 'fast' (5-min sources only),
    'slow' (15-min sources only)."""
    logger = logging.getLogger("main")
    run_fast = mode in ("full", "fast")
    run_slow = mode in ("full", "slow")
    logger.info("=== Starting '%s' ingestion cycle for %d tickers ===", mode, len(TICKERS))
    init_db()

    quotes, st_messages, reddit_posts = [], [], []
    finnhub_headlines, finnhub_social = [], []
    headlines, google_headlines = [], []

    if run_fast:
        # 1. Prices (yfinance - free, no key)
        quotes = prices.fetch_all_quotes()
        logger.info("Fetched %d price quotes", len(quotes))

        # 2. StockTwits (free public endpoint)
        st_messages = stocktwits.fetch_all_messages()
        logger.info("Fetched %d StockTwits messages", len(st_messages))

        # 3. Reddit (skipped gracefully if credentials aren't configured yet)
        try:
            reddit_posts = reddit_source.fetch_posts()
            logger.info("Fetched %d matching Reddit posts", len(reddit_posts))
        except RuntimeError as exc:
            logger.warning("Skipping Reddit ingestion: %s", exc)

        # 4. Finnhub company news + aggregated social sentiment (skipped
        # gracefully if FINNHUB_API_KEY isn't configured yet)
        try:
            finnhub_headlines = finnhub_source.fetch_all_company_news()
            logger.info("Fetched %d Finnhub news headlines", len(finnhub_headlines))
            finnhub_social = finnhub_source.fetch_all_social_sentiment()
            logger.info("Fetched %d Finnhub social-sentiment rows", len(finnhub_social))
        except RuntimeError as exc:
            logger.warning("Skipping Finnhub ingestion: %s", exc)

    if run_slow:
        # 5. News headlines (free FinViz scrape - ~30 min update cadence)
        headlines = news.fetch_all_headlines()
        logger.info("Fetched %d FinViz news headlines", len(headlines))

        # 6. Google News RSS (free, no key - second independent news source)
        try:
            google_headlines = google_news_source.fetch_all_headlines()
            logger.info("Fetched %d Google News headlines", len(google_headlines))
        except Exception as exc:
            logger.error("Google News ingestion failed: %s", exc)

    # Persist everything fetched this cycle
    with get_conn() as conn:
        for q in quotes:
            insert_price(conn, q["ticker"], q["price"], q["day_change_pct"], q["volume"], q["source"], q["fetched_at"])
        for m in st_messages + reddit_posts:
            insert_social(
                conn, m["ticker"], m["source"], m["external_id"], m["author"],
                m["text"], m["url"], m["created_at"], m["ingested_at"],
            )
        for h in headlines + google_headlines + finnhub_headlines:
            insert_news(conn, h["ticker"], h["source"], h["title"], h["link"], h["published_at"], h["ingested_at"])
        for s in finnhub_social:
            insert_social_sentiment_agg(
                conn, s["ticker"], s["platform"], s["period"], s["mention"],
                s["positive_score"], s["negative_score"], s["positive_mention"],
                s["negative_mention"], s["fetched_at"],
            )

    # 7. Score any newly-ingested text with VADER (layer 2)
    scored_count = sentiment.score_new_rows()
    logger.info("Scored %d new rows for sentiment", scored_count)

    # 8. Prediction accuracy log (added 2026-07-12) - log any signal changes
    # and grade any signals that have crossed the 4h/24h horizon. Runs every
    # cycle regardless of mode; cheap (local DB only, no network calls).
    with get_conn() as conn:
        current_prices = get_latest_prices()
        changed = 0
        for ticker in get_known_tickers():
            signal_info = get_signal(ticker, hours=24)
            price_at_signal = current_prices.get(ticker, {}).get("price")
            if signal_tracking.log_signal_if_changed(conn, ticker, signal_info, price_at_signal):
                changed += 1
                logger.info("Signal change logged for %s: %s", ticker, signal_info["signal"])
        graded = signal_tracking.evaluate_pending_signals(conn, current_prices)
    if changed or graded:
        logger.info("Signal log: %d new call(s) logged, %d evaluation(s) graded", changed, graded)

    logger.info("=== '%s' ingestion + scoring cycle complete at %s ===", mode, datetime.now(timezone.utc).isoformat())


def _parse_args():
    parser = argparse.ArgumentParser(description="Run one ingestion cycle.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--fast-only", action="store_true",
        help="Only run fast sources (prices, StockTwits, Reddit, Finnhub) - for a 5-minute schedule.",
    )
    group.add_argument(
        "--slow-only", action="store_true",
        help="Only run slow/scraped sources (FinViz, Google News) - for a 15-minute schedule.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    mode = "fast" if args.fast_only else "slow" if args.slow_only else "full"
    setup_logging()
    run_cycle(mode=mode)
