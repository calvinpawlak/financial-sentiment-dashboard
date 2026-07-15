import os
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
            graded = evaluate_pending_signals(conn, {"TEST": {"price": 120.0}}, now=now)
            rows = conn.execute(
                "SELECT horizon_hours, correct FROM signal_evaluations ORDER BY horizon_hours"
            ).fetchall()

        self.assertEqual(graded, 2)
        self.assertEqual(rows, [(4, 1), (24, 1)])

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


if __name__ == "__main__":
    unittest.main()
