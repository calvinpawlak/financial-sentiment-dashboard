import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import storage.db as db


class OfflineSmokeTests(unittest.TestCase):
    """Exercise core behavior without credentials, network calls, or Neon."""

    @classmethod
    def setUpClass(cls):
        cls._original_db_path = db.DB_PATH
        cls._original_database_url = db.DATABASE_URL
        cls._original_is_postgres = db.IS_POSTGRES
        cls._tempdir = tempfile.TemporaryDirectory()

        db.DB_PATH = os.path.join(cls._tempdir.name, "test.db")
        db.DATABASE_URL = ""
        db.IS_POSTGRES = False
        db.init_db()

        # Import consumers only after the database module points at the
        # isolated fixture database.
        from webapp.server import app

        cls.app = app

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls._original_db_path
        db.DATABASE_URL = cls._original_database_url
        db.IS_POSTGRES = cls._original_is_postgres
        cls._tempdir.cleanup()

    def setUp(self):
        with db.get_conn() as conn:
            for table in (
                "signal_evaluations",
                "signal_log",
                "scored_sentiment",
                "raw_social_sentiment_agg",
                "raw_events",
                "raw_news",
                "raw_social",
                "raw_prices",
            ):
                conn.execute(f"DELETE FROM {table}")

    def _seed_bullish_rising_ticker(self, ticker="TEST"):
        now = datetime.now(timezone.utc)
        with db.get_conn() as conn:
            db.insert_price(conn, ticker, 100.0, 1.0, 1000, "fixture", (now - timedelta(hours=1)).isoformat())
            db.insert_price(conn, ticker, 110.0, 2.0, 1200, "fixture", now.isoformat())
            for index in range(3):
                db.insert_scored_sentiment(
                    conn,
                    "raw_social",
                    index + 1,
                    ticker,
                    "fixture",
                    "bullish fixture",
                    0.8,
                    0.8,
                    0.2,
                    0.0,
                    "bullish",
                    now.isoformat(),
                )
        return now

    def test_schema_contains_source_breakdown_migration(self):
        with db.get_conn() as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(signal_log)")]
        self.assertIn("source_breakdown", columns)

    def test_legacy_sqlite_uniqueness_migrates_without_changing_ids(self):
        original_path = db.DB_PATH
        legacy_dir = tempfile.TemporaryDirectory()
        legacy_path = os.path.join(legacy_dir.name, "legacy.db")
        conn = sqlite3.connect(legacy_path)
        conn.executescript(
            """
            CREATE TABLE raw_social (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
                source TEXT NOT NULL, external_id TEXT, author TEXT, text TEXT,
                url TEXT, created_at TEXT, ingested_at TEXT NOT NULL,
                UNIQUE(source, external_id)
            );
            CREATE TABLE raw_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT NOT NULL,
                source TEXT NOT NULL, title TEXT, link TEXT UNIQUE,
                published_at TEXT, ingested_at TEXT NOT NULL
            );
            INSERT INTO raw_social VALUES
                (41, 'TEST', 'fixture', 'post-1', NULL, 'text', NULL, NULL, '2026-07-15');
            INSERT INTO raw_news VALUES
                (73, 'TEST', 'fixture', 'title', 'https://example.test/a', NULL, '2026-07-15');
            """
        )
        conn.close()

        try:
            db.DB_PATH = legacy_path
            db.init_db()
            with db.get_conn() as migrated:
                db.insert_social(
                    migrated, "SECOND", "fixture", "post-1", None, "text",
                    None, None, "2026-07-15",
                )
                db.insert_news(
                    migrated, "SECOND", "fixture", "title",
                    "https://example.test/a", None, "2026-07-15",
                )
                social_ids = migrated.execute(
                    "SELECT id FROM raw_social ORDER BY id"
                ).fetchall()
                news_ids = migrated.execute(
                    "SELECT id FROM raw_news ORDER BY id"
                ).fetchall()
            self.assertEqual(social_ids[0], (41,))
            self.assertEqual(news_ids[0], (73,))
            self.assertEqual(len(social_ids), 2)
            self.assertEqual(len(news_ids), 2)
        finally:
            db.DB_PATH = original_path
            legacy_dir.cleanup()

    def test_conservative_signal_buy_and_no_data_hold(self):
        from storage.queries import get_signal

        self._seed_bullish_rising_ticker()
        self.assertEqual(get_signal("TEST", hours=24)["signal"], "BUY")
        self.assertEqual(get_signal("UNKNOWN", hours=24)["signal"], "HOLD")

    def test_signal_logging_and_dual_horizon_grading(self):
        from processing.signal_tracking import evaluate_pending_signals, log_signal_if_changed
        from storage.queries import get_signal

        now = self._seed_bullish_rising_ticker()
        signal = get_signal("TEST", hours=24)
        logged_at = (now - timedelta(hours=25)).isoformat()

        with db.get_conn() as conn:
            self.assertTrue(log_signal_if_changed(conn, "TEST", signal, 110.0, logged_at=logged_at))
            self.assertFalse(log_signal_if_changed(conn, "TEST", signal, 110.0, logged_at=logged_at))
            conn.execute("DELETE FROM raw_prices")
            sample_4h = (now - timedelta(hours=20, minutes=59)).isoformat()
            sample_24h = (now - timedelta(minutes=59)).isoformat()
            db.insert_price(conn, "TEST", 120.0, 1.0, 1000, "fixture", sample_4h)
            db.insert_price(conn, "TEST", 130.0, 1.0, 1000, "fixture", sample_24h)
            graded = evaluate_pending_signals(conn, {"TEST": {"price": 999.0}}, now=now)
            rows = conn.execute(
                """SELECT horizon_hours, correct, price_at_evaluation, evaluated_at
                   FROM signal_evaluations ORDER BY horizon_hours"""
            ).fetchall()

        self.assertEqual(graded, 2)
        self.assertEqual(rows, [(4, 1, 120.0, sample_4h), (24, 1, 130.0, sample_24h)])

    def test_multi_ticker_source_items_preserve_each_association(self):
        now = datetime.now(timezone.utc).isoformat()
        with db.get_conn() as conn:
            for ticker in ("TEST", "SECOND"):
                db.insert_social(
                    conn, ticker, "fixture", "same-post", "author",
                    "$TEST and $SECOND", "https://example.test/post", now, now,
                )
                db.insert_news(
                    conn, ticker, "fixture", "Shared article",
                    "https://example.test/article", now, now,
                )
            social_count = conn.execute(
                "SELECT COUNT(*) FROM raw_social WHERE external_id = ?", ("same-post",)
            ).fetchone()[0]
            news_count = conn.execute(
                "SELECT COUNT(*) FROM raw_news WHERE link = ?", ("https://example.test/article",)
            ).fetchone()[0]

        self.assertEqual(social_count, 2)
        self.assertEqual(news_count, 2)

    def test_flask_read_endpoints(self):
        self._seed_bullish_rising_ticker()
        client = self.app.test_client()
        for url in (
            "/",
            "/api/tickers",
            "/api/overview?hours=24",
            "/api/ticker/test?hours=24",
            "/api/accuracy",
            "/api/signal-log?limit=5",
            "/api/events",
        ):
            with self.subTest(url=url):
                response = client.get(url)
                try:
                    self.assertEqual(response.status_code, 200)
                finally:
                    response.close()

    def test_stocktwits_stops_after_first_access_denial(self):
        from ingestion import stocktwits

        denied = Mock(status_code=403)
        with patch.object(stocktwits.requests, "get", return_value=denied) as request_get:
            messages = stocktwits.fetch_all_messages(["TEST", "SECOND"])

        self.assertEqual(messages, [])
        self.assertEqual(request_get.call_count, 1)

    def test_bluesky_authenticated_search_shape(self):
        from ingestion import bluesky_source

        session_response = Mock()
        session_response.raise_for_status.return_value = None
        session_response.json.return_value = {"accessJwt": "test-token"}
        search_response = Mock()
        search_response.raise_for_status.return_value = None
        search_response.json.return_value = {
            "posts": [
                {
                    "uri": "at://did:plc:test/app.bsky.feed.post/abc123",
                    "author": {"handle": "investor.example"},
                    "record": {
                        "text": "$TEST looks bullish",
                        "createdAt": "2026-07-15T12:00:00Z",
                    },
                }
            ]
        }

        with patch.dict(
            os.environ,
            {"BLUESKY_HANDLE": "test.example", "BLUESKY_APP_PASSWORD": "app-password"},
        ), patch.object(bluesky_source.requests, "post", return_value=session_response) as post, patch.object(
            bluesky_source.requests, "get", return_value=search_response
        ) as get:
            posts = bluesky_source.fetch_posts(["TEST"], limit=5)

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["source"], "bluesky")
        self.assertEqual(posts[0]["external_id"], "at://did:plc:test/app.bsky.feed.post/abc123")
        self.assertIn("investor.example", posts[0]["url"])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(get.call_count, 1)

    def test_authoritative_event_storage_and_query(self):
        from storage.queries import get_recent_events
        now = datetime.now(timezone.utc).isoformat()
        with db.get_conn() as conn:
            db.insert_event(conn, "TEST", "sec_edgar", "8-K", "Test filing", "https://example.test/filing", now, now)
            db.insert_event(conn, None, "federal_reserve", "monetary_policy", "Policy release", "https://example.test/fed", now, now)
            db.insert_event(conn, "TEST", "sec_edgar", "8-K", "Duplicate", "https://example.test/filing", now, now)
        events = get_recent_events(ticker="TEST")
        self.assertEqual(len(events), 2)
        self.assertEqual({event["source"] for event in events}, {"sec_edgar", "federal_reserve"})

    def test_federal_reserve_rss_shape(self):
        from ingestion import federal_reserve_source
        rss = b"""<rss><channel><item><title>Policy update</title><link>https://example.test/policy</link><pubDate>Wed, 15 Jul 2026 12:00:00 GMT</pubDate></item></channel></rss>"""
        response = Mock(content=rss)
        response.raise_for_status.return_value = None
        with patch.object(federal_reserve_source.requests, "get", return_value=response):
            events = federal_reserve_source.fetch_events(limit_per_feed=1)
        self.assertEqual(len(events), 3)
        self.assertEqual({event["category"] for event in events}, set(federal_reserve_source.FEEDS))


if __name__ == "__main__":
    unittest.main()
