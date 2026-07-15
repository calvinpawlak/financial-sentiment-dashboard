"""
Storage layer (foundation for layer 3). Supports two backends:

  - SQLite (default) - a local file, used by the ingestion side (main.py,
    run via Task Scheduler on your own machine) exactly as before.
  - Postgres - used automatically when a DATABASE_URL environment variable
    is set (e.g. a free Neon database). This is what lets the hosted
    Flask app (webapp/server.py, deployed to Render) read the same data
    your local machine writes, since a public host's local disk isn't a
    reliable place to keep a SQLite file (it's usually wiped on redeploy).

Added 2026-07-12 for public hosting. Every other module in this project
(storage/queries.py, processing/sentiment.py, prune.py, etc.) is UNCHANGED -
they only ever call conn.execute(query, params) with '?' placeholders, or
the insert_*() helpers below. _PGConnAdapter below makes a psycopg2
connection quack like a sqlite3.Connection (translating '?' -> '%s' and
providing the same .execute()/.commit()/.close() surface), so nothing
outside this file needs to know or care which backend is active.

Layer 1 writes RAW ingested data (raw_prices, raw_social, raw_news).
Layer 2 (NLP sentiment scoring) reads raw_social / raw_news and writes
results to scored_sentiment, keyed back to the originating row via
(origin_table, origin_id) so re-running scoring never double-scores a row.
"""
import sqlite3
import os
from contextlib import contextmanager

from config.settings import DB_PATH

# Postgres is used only if DATABASE_URL is set (e.g. a Neon connection
# string) - local ingestion runs on Calvin's machine keep using SQLite by
# default, no config change required for existing setups.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_POSTGRES = bool(DATABASE_URL)

if IS_POSTGRES:
    import psycopg2

_SIGNAL_TRACKING_TABLES = """
-- Prediction accuracy log, added 2026-07-12. One row per signal CHANGE per
-- ticker (not one row per ingestion cycle - that would log an unchanged
-- HOLD every 5 minutes forever). See processing/signal_tracking.py.
CREATE TABLE IF NOT EXISTS signal_log (
    id {id_pk},
    ticker TEXT NOT NULL,
    signal TEXT NOT NULL,              -- 'BUY' / 'SELL' / 'HOLD'
    sentiment_verdict TEXT NOT NULL,
    price_direction TEXT NOT NULL,
    reasoning TEXT,
    price_at_signal REAL,
    logged_at TEXT NOT NULL,
    -- Added 2026-07-12 (Calvin asked whether data sources need revising
    -- based on results): JSON string mapping each source name to its own
    -- bullish/bearish/neutral counts, captured at the moment this signal
    -- was logged, so accuracy can later be sliced by which source(s) drove
    -- a given call, not just by ticker. NULL for rows logged before this
    -- column existed (see the migration in init_db).
    source_breakdown TEXT
);

-- Each logged signal is graded at two horizons (4h and 24h) once enough
-- time has passed. `correct` is NULL for HOLD signals (not a directional
-- call, so "correct/incorrect" doesn't apply - see get_signal_accuracy_stats
-- in storage/queries.py for how this is surfaced honestly on the dashboard).
CREATE TABLE IF NOT EXISTS signal_evaluations (
    id {id_pk},
    signal_log_id INTEGER NOT NULL,
    horizon_hours INTEGER NOT NULL,
    evaluated_at TEXT NOT NULL,
    price_at_evaluation REAL,
    price_change_pct REAL,
    correct INTEGER,                   -- 1 = correct, 0 = incorrect, NULL = n/a (HOLD)
    UNIQUE(signal_log_id, horizon_hours)
);

CREATE INDEX IF NOT EXISTS idx_signal_log_ticker_time ON signal_log(ticker, logged_at);
CREATE INDEX IF NOT EXISTS idx_signal_evaluations_signal_log_id ON signal_evaluations(signal_log_id);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    price REAL,
    day_change_pct REAL,
    volume INTEGER,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_social (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,          -- 'reddit' or 'stocktwits'
    external_id TEXT,              -- source's own post/message id, for de-duping
    author TEXT,
    text TEXT,
    url TEXT,
    created_at TEXT,               -- when the post was made
    ingested_at TEXT NOT NULL,     -- when we pulled it
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS raw_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT,
    link TEXT UNIQUE,
    published_at TEXT,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    link TEXT UNIQUE,
    published_at TEXT,
    ingested_at TEXT NOT NULL
);

-- Finnhub's /stock/social-sentiment endpoint returns PRE-AGGREGATED
-- Reddit/Twitter mention counts + sentiment scores per ticker per period -
-- not per-post text, so it can't flow through the VADER scoring pipeline
-- like raw_social/raw_news do. Stored separately and surfaced as a
-- supplementary signal (see storage/queries.py's
-- get_latest_social_sentiment_agg), deliberately not merged into
-- scored_sentiment's bullish/bearish/neutral counts.
CREATE TABLE IF NOT EXISTS raw_social_sentiment_agg (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    platform TEXT NOT NULL,        -- 'reddit' or 'twitter'
    period TEXT,                   -- Finnhub's own bucket timestamp for this rollup
    mention INTEGER,
    positive_score REAL,
    negative_score REAL,
    positive_mention INTEGER,
    negative_mention INTEGER,
    fetched_at TEXT NOT NULL,
    UNIQUE(ticker, platform, period)
);

CREATE TABLE IF NOT EXISTS scored_sentiment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin_table TEXT NOT NULL,    -- 'raw_social' or 'raw_news'
    origin_id INTEGER NOT NULL,    -- id of the row in that table
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,          -- 'reddit' / 'stocktwits' / 'finviz'
    text TEXT,                     -- the text that was scored (post body or headline)
    compound REAL NOT NULL,        -- VADER compound score, -1 (most negative) to +1 (most positive)
    pos REAL NOT NULL,
    neu REAL NOT NULL,
    neg REAL NOT NULL,
    label TEXT NOT NULL,           -- 'bullish' / 'bearish' / 'neutral'
    scored_at TEXT NOT NULL,
    UNIQUE(origin_table, origin_id)
);

-- Layer 3: indexes backing the query patterns report.py (and eventually the
-- layer 4 dashboard) actually use - filtering scored_sentiment by a time
-- window and grouping by ticker. Without these, that query does a full
-- table scan that gets slower every day as scored_sentiment grows.
CREATE INDEX IF NOT EXISTS idx_scored_sentiment_ticker_time ON scored_sentiment(ticker, scored_at);
CREATE INDEX IF NOT EXISTS idx_scored_sentiment_time ON scored_sentiment(scored_at);
CREATE INDEX IF NOT EXISTS idx_raw_social_ticker ON raw_social(ticker);
CREATE INDEX IF NOT EXISTS idx_raw_news_ticker ON raw_news(ticker);
CREATE INDEX IF NOT EXISTS idx_raw_events_ticker_time ON raw_events(ticker, published_at);
CREATE INDEX IF NOT EXISTS idx_raw_prices_ticker_time ON raw_prices(ticker, fetched_at);
CREATE INDEX IF NOT EXISTS idx_social_sentiment_agg_ticker ON raw_social_sentiment_agg(ticker, fetched_at);
""" + _SIGNAL_TRACKING_TABLES.format(id_pk="INTEGER PRIMARY KEY AUTOINCREMENT")

# Same structure as SCHEMA, adapted for Postgres: SERIAL instead of
# AUTOINCREMENT (Postgres has no AUTOINCREMENT keyword), everything else -
# types, UNIQUE constraints, indexes - is valid standard SQL in both.
SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS raw_prices (
    id SERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    price REAL,
    day_change_pct REAL,
    volume INTEGER,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_social (
    id SERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    external_id TEXT,
    author TEXT,
    text TEXT,
    url TEXT,
    created_at TEXT,
    ingested_at TEXT NOT NULL,
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS raw_news (
    id SERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT,
    link TEXT UNIQUE,
    published_at TEXT,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_events (
    id SERIAL PRIMARY KEY,
    ticker TEXT,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    link TEXT UNIQUE,
    published_at TEXT,
    ingested_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_social_sentiment_agg (
    id SERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    platform TEXT NOT NULL,
    period TEXT,
    mention INTEGER,
    positive_score REAL,
    negative_score REAL,
    positive_mention INTEGER,
    negative_mention INTEGER,
    fetched_at TEXT NOT NULL,
    UNIQUE(ticker, platform, period)
);

CREATE TABLE IF NOT EXISTS scored_sentiment (
    id SERIAL PRIMARY KEY,
    origin_table TEXT NOT NULL,
    origin_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,
    text TEXT,
    compound REAL NOT NULL,
    pos REAL NOT NULL,
    neu REAL NOT NULL,
    neg REAL NOT NULL,
    label TEXT NOT NULL,
    scored_at TEXT NOT NULL,
    UNIQUE(origin_table, origin_id)
);

CREATE INDEX IF NOT EXISTS idx_scored_sentiment_ticker_time ON scored_sentiment(ticker, scored_at);
CREATE INDEX IF NOT EXISTS idx_scored_sentiment_time ON scored_sentiment(scored_at);
CREATE INDEX IF NOT EXISTS idx_raw_social_ticker ON raw_social(ticker);
CREATE INDEX IF NOT EXISTS idx_raw_news_ticker ON raw_news(ticker);
CREATE INDEX IF NOT EXISTS idx_raw_events_ticker_time ON raw_events(ticker, published_at);
CREATE INDEX IF NOT EXISTS idx_raw_prices_ticker_time ON raw_prices(ticker, fetched_at);
CREATE INDEX IF NOT EXISTS idx_social_sentiment_agg_ticker ON raw_social_sentiment_agg(ticker, fetched_at);
""" + _SIGNAL_TRACKING_TABLES.format(id_pk="SERIAL PRIMARY KEY")


class _PGConnAdapter:
    """Makes a psycopg2 connection usable exactly like a sqlite3.Connection,
    so every other module in this project (queries.py, sentiment.py,
    prune.py, signal_tracking.py) can keep calling conn.execute(query,
    params) with '?' placeholders and never know which backend is active.
    Only db.py itself needs to be dialect-aware."""

    def __init__(self, pg_conn):
        self._conn = pg_conn

    def execute(self, query, params=()):
        cur = self._conn.cursor()
        cur.execute(query.replace("?", "%s"), params)
        return cur

    def executescript(self, script):
        cur = self._conn.cursor()
        cur.execute(script)
        cur.close()

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def _add_column_if_missing(conn, table, column, coltype):
    """Migrate an existing database created before `column` existed.
    CREATE TABLE IF NOT EXISTS (used for the base schema above) is a no-op
    on a table that already exists, so a brand-new column added to the
    schema later needs an explicit ALTER TABLE for anyone upgrading in
    place (added 2026-07-12 for signal_log.source_breakdown, since Calvin's
    local SQLite file and Neon Postgres database both already had signal_log
    rows before this column was introduced)."""
    if IS_POSTGRES:
        # Postgres 9.6+ supports IF NOT EXISTS directly - no error to catch.
        conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype}")
    else:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise


def init_db():
    if not IS_POSTGRES:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA_POSTGRES if IS_POSTGRES else SCHEMA)
        _add_column_if_missing(conn, "signal_log", "source_breakdown", "TEXT")


@contextmanager
def get_conn():
    if IS_POSTGRES:
        pg_conn = psycopg2.connect(DATABASE_URL)
        conn = _PGConnAdapter(pg_conn)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
        return

    conn = sqlite3.connect(DB_PATH)
    # WAL mode lets a reader (report.py, or the layer 4 dashboard later)
    # run concurrently with a writer (main.py mid-ingestion) without either
    # side hitting "database is locked" - the default rollback-journal mode
    # blocks readers during writes, which becomes a real risk once
    # main.py is running on a 5/15-minute Task Scheduler cadence.
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def vacuum():
    """Reclaim disk space after a bulk delete (e.g. prune.py). SQLite-only -
    Postgres manages this itself via autovacuum, so this is a no-op there
    rather than a confusing error."""
    if IS_POSTGRES:
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute("VACUUM")
    conn.close()


def insert_price(conn, ticker, price, day_change_pct, volume, source, fetched_at):
    conn.execute(
        "INSERT INTO raw_prices (ticker, price, day_change_pct, volume, source, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ticker, price, day_change_pct, volume, source, fetched_at),
    )


def insert_social(conn, ticker, source, external_id, author, text, url, created_at, ingested_at):
    ignore_clause = "ON CONFLICT (source, external_id) DO NOTHING" if IS_POSTGRES else ""
    or_ignore = "" if IS_POSTGRES else "OR IGNORE "
    conn.execute(
        f"""INSERT {or_ignore}INTO raw_social
           (ticker, source, external_id, author, text, url, created_at, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?) {ignore_clause}""",
        (ticker, source, external_id, author, text, url, created_at, ingested_at),
    )


def insert_news(conn, ticker, source, title, link, published_at, ingested_at):
    ignore_clause = "ON CONFLICT (link) DO NOTHING" if IS_POSTGRES else ""
    or_ignore = "" if IS_POSTGRES else "OR IGNORE "
    conn.execute(
        f"""INSERT {or_ignore}INTO raw_news
           (ticker, source, title, link, published_at, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?) {ignore_clause}""",
        (ticker, source, title, link, published_at, ingested_at),
    )


def insert_event(conn, ticker, source, category, title, link, published_at, ingested_at):
    """Store authoritative events separately from sentiment-scored chatter/news."""
    ignore_clause = "ON CONFLICT (link) DO NOTHING" if IS_POSTGRES else ""
    or_ignore = "" if IS_POSTGRES else "OR IGNORE "
    conn.execute(
        f"""INSERT {or_ignore}INTO raw_events
           (ticker, source, category, title, link, published_at, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?) {ignore_clause}""",
        (ticker, source, category, title, link, published_at, ingested_at),
    )


def insert_social_sentiment_agg(
    conn, ticker, platform, period, mention, positive_score, negative_score,
    positive_mention, negative_mention, fetched_at,
):
    ignore_clause = "ON CONFLICT (ticker, platform, period) DO NOTHING" if IS_POSTGRES else ""
    or_ignore = "" if IS_POSTGRES else "OR IGNORE "
    conn.execute(
        f"""INSERT {or_ignore}INTO raw_social_sentiment_agg
           (ticker, platform, period, mention, positive_score, negative_score,
            positive_mention, negative_mention, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) {ignore_clause}""",
        (ticker, platform, period, mention, positive_score, negative_score,
         positive_mention, negative_mention, fetched_at),
    )


def get_unscored(conn, origin_table, text_column):
    """Rows in `origin_table` (either 'raw_social' or 'raw_news') that don't
    yet have a matching scored_sentiment row. origin_table/text_column are
    always fixed internal constants (never user input), so the f-string
    here isn't an injection risk."""
    query = f"""
        SELECT r.id, r.ticker, r.source, r.{text_column}
        FROM {origin_table} r
        LEFT JOIN scored_sentiment s
            ON s.origin_table = ? AND s.origin_id = r.id
        WHERE s.id IS NULL
    """
    return conn.execute(query, (origin_table,)).fetchall()


def insert_scored_sentiment(conn, origin_table, origin_id, ticker, source, text,
                             compound, pos, neu, neg, label, scored_at):
    ignore_clause = "ON CONFLICT (origin_table, origin_id) DO NOTHING" if IS_POSTGRES else ""
    or_ignore = "" if IS_POSTGRES else "OR IGNORE "
    conn.execute(
        f"""INSERT {or_ignore}INTO scored_sentiment
           (origin_table, origin_id, ticker, source, text, compound, pos, neu, neg, label, scored_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) {ignore_clause}""",
        (origin_table, origin_id, ticker, source, text, compound, pos, neu, neg, label, scored_at),
    )


def insert_signal_log(conn, ticker, signal, sentiment_verdict, price_direction, reasoning, price_at_signal, logged_at, source_breakdown=None):
    """Plain INSERT (no dedup needed - processing/signal_tracking.py decides
    whether a new row is warranted before calling this). Evaluation later
    finds rows to grade via a SELECT/JOIN against signal_evaluations
    (see evaluate_pending_signals), so there's no need to hand back the
    new row's id here. source_breakdown is a pre-serialized JSON string
    (or None) - see processing/signal_tracking.py."""
    conn.execute(
        """INSERT INTO signal_log
           (ticker, signal, sentiment_verdict, price_direction, reasoning, price_at_signal, logged_at, source_breakdown)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (ticker, signal, sentiment_verdict, price_direction, reasoning, price_at_signal, logged_at, source_breakdown),
    )


def insert_signal_evaluation(conn, signal_log_id, horizon_hours, evaluated_at, price_at_evaluation, price_change_pct, correct):
    ignore_clause = "ON CONFLICT (signal_log_id, horizon_hours) DO NOTHING" if IS_POSTGRES else ""
    or_ignore = "" if IS_POSTGRES else "OR IGNORE "
    conn.execute(
        f"""INSERT {or_ignore}INTO signal_evaluations
           (signal_log_id, horizon_hours, evaluated_at, price_at_evaluation, price_change_pct, correct)
           VALUES (?, ?, ?, ?, ?, ?) {ignore_clause}""",
        (signal_log_id, horizon_hours, evaluated_at, price_at_evaluation, price_change_pct, correct),
    )
