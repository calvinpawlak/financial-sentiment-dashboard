"""
Layer 3 - shared read queries.

Centralizes the SQL that report.py (and eventually the layer 4 dashboard)
needs, so there's one place to fix/optimize queries instead of duplicated
ad hoc SQL scattered across every consumer.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from storage.db import get_conn


def get_sentiment_summary(hours: int = 24) -> dict:
    """Per-ticker bullish/bearish/neutral counts over the last N hours.
    Returns {ticker: {"bullish": n, "bearish": n, "neutral": n}}."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ticker, label, COUNT(*)
               FROM scored_sentiment
               WHERE scored_at >= ?
               GROUP BY ticker, label""",
            (cutoff,),
        ).fetchall()

    summary = defaultdict(lambda: {"bullish": 0, "bearish": 0, "neutral": 0})
    for ticker, label, count in rows:
        summary[ticker][label] = count
    return dict(summary)


def verdict_for(counts: dict) -> str:
    """Simple lean label from a {"bullish": n, "bearish": n, "neutral": n}
    count dict - a >10 percentage-point gap either way, else mixed."""
    total = counts["bullish"] + counts["bearish"] + counts["neutral"]
    if total == 0:
        return "NO DATA"
    bullish_pct = counts["bullish"] / total * 100
    bearish_pct = counts["bearish"] / total * 100
    if bullish_pct > bearish_pct + 10:
        return "BULLISH"
    if bearish_pct > bullish_pct + 10:
        return "BEARISH"
    return "MIXED/NEUTRAL"


def get_latest_prices() -> dict:
    """Most recent price snapshot per ticker.
    Returns {ticker: {"price": ..., "day_change_pct": ..., "volume": ...,
    "fetched_at": ...}}."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT ticker, price, day_change_pct, volume, fetched_at
               FROM raw_prices rp
               WHERE fetched_at = (
                   SELECT MAX(fetched_at) FROM raw_prices WHERE ticker = rp.ticker
               )"""
        ).fetchall()

    return {
        ticker: {"price": price, "day_change_pct": day_change_pct, "volume": volume, "fetched_at": fetched_at}
        for ticker, price, day_change_pct, volume, fetched_at in rows
    }


def get_recent_posts(ticker: str, limit: int = 10) -> list:
    """Most recent scored posts/headlines for one ticker, newest first -
    useful for a "why is this ticker bullish/bearish" drill-down."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT source, text, label, compound, scored_at
               FROM scored_sentiment
               WHERE ticker = ?
               ORDER BY scored_at DESC
               LIMIT ?""",
            (ticker, limit),
        ).fetchall()

    return [
        {"source": source, "text": text, "label": label, "compound": compound, "scored_at": scored_at}
        for source, text, label, compound, scored_at in rows
    ]


def get_sentiment_timeseries(ticker: str, hours: int = 168) -> list:
    """Hourly-bucketed sentiment for one ticker: average compound score and
    post count per hour, oldest first - feeds the dashboard's trend chart.

    Buckets using substr(scored_at, 1, 13) (the "YYYY-MM-DDTHH" prefix of
    our ISO timestamps) rather than SQLite's date functions - sorts and
    groups correctly with zero ambiguity about SQLite's ISO-8601 parsing
    quirks, since we control the exact timestamp format everywhere it's
    written (datetime.now(timezone.utc).isoformat())."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT substr(scored_at, 1, 13) AS bucket,
                      AVG(compound) AS avg_compound,
                      COUNT(*) AS n
               FROM scored_sentiment
               WHERE ticker = ? AND scored_at >= ?
               GROUP BY bucket
               ORDER BY bucket ASC""",
            (ticker, cutoff),
        ).fetchall()

    return [{"bucket": bucket, "avg_compound": avg_compound, "n": n} for bucket, avg_compound, n in rows]


def get_price_history(ticker: str, hours: int = 168) -> list:
    """Price snapshots for one ticker over the lookback window, oldest
    first - feeds the price line on the dashboard's trend chart."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT fetched_at, price
               FROM raw_prices
               WHERE ticker = ? AND fetched_at >= ?
               ORDER BY fetched_at ASC""",
            (ticker, cutoff),
        ).fetchall()

    return [{"fetched_at": fetched_at, "price": price} for fetched_at, price in rows]


def get_known_tickers() -> list:
    """Distinct tickers actually present in the data, for populating the
    dashboard's ticker selector dynamically rather than hardcoding it."""
    with get_conn() as conn:
        rows = conn.execute("SELECT DISTINCT ticker FROM raw_prices ORDER BY ticker").fetchall()
    return [r[0] for r in rows]


def get_latest_social_sentiment_agg(ticker: str) -> dict:
    """Most recent Finnhub-aggregated Reddit/Twitter mention+sentiment rollup
    per platform for one ticker. This is a SUPPLEMENTARY signal, separate
    from get_sentiment_summary()'s VADER-scored bullish/bearish/neutral
    counts - Finnhub's numbers are pre-aggregated by them, not scored by us,
    so the two shouldn't be averaged or added together. Either value in the
    returned dict is None if Finnhub hasn't returned data for that platform
    (e.g. no FINNHUB_API_KEY configured, or that endpoint returned 403).
    Returns {"reddit": {...} | None, "twitter": {...} | None}."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT platform, period, mention, positive_score, negative_score, fetched_at
               FROM raw_social_sentiment_agg rssa
               WHERE ticker = ? AND fetched_at = (
                   SELECT MAX(fetched_at) FROM raw_social_sentiment_agg
                   WHERE ticker = ? AND platform = rssa.platform
               )
               ORDER BY period DESC""",
            (ticker, ticker),
        ).fetchall()

    result = {"reddit": None, "twitter": None}
    seen = set()
    for platform, period, mention, positive_score, negative_score, fetched_at in rows:
        if platform in seen:
            continue
        seen.add(platform)
        result[platform] = {
            "period": period,
            "mention": mention,
            "positive_score": positive_score,
            "negative_score": negative_score,
            "fetched_at": fetched_at,
        }
    return result


def get_signal_log(ticker: str = None, limit: int = 50) -> list:
    """Recent logged BUY/SELL/HOLD calls (one row per signal CHANGE, written
    by processing/signal_tracking.py), newest first, each with its 4h/24h
    grading if evaluated yet (None if the horizon hasn't been reached, or a
    price wasn't available yet to grade it)."""
    query = """SELECT sl.id, sl.ticker, sl.signal, sl.sentiment_verdict, sl.price_direction,
                      sl.reasoning, sl.price_at_signal, sl.logged_at
               FROM signal_log sl"""
    params = []
    if ticker:
        query += " WHERE sl.ticker = ?"
        params.append(ticker)
    query += " ORDER BY sl.logged_at DESC LIMIT ?"
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
        ids = [r[0] for r in rows]
        evals_by_signal_id = defaultdict(dict)
        if ids:
            placeholders = ",".join("?" * len(ids))
            eval_rows = conn.execute(
                f"""SELECT signal_log_id, horizon_hours, correct, price_change_pct, price_at_evaluation
                    FROM signal_evaluations WHERE signal_log_id IN ({placeholders})""",
                tuple(ids),
            ).fetchall()
            for signal_log_id, horizon_hours, correct, price_change_pct, price_at_evaluation in eval_rows:
                evals_by_signal_id[signal_log_id][horizon_hours] = {
                    "correct": correct,
                    "price_change_pct": price_change_pct,
                    "price_at_evaluation": price_at_evaluation,
                }

    out = []
    for id_, ticker_, signal, verdict, direction, reasoning, price_at_signal, logged_at in rows:
        out.append(
            {
                "id": id_,
                "ticker": ticker_,
                "signal": signal,
                "sentiment_verdict": verdict,
                "price_direction": direction,
                "reasoning": reasoning,
                "price_at_signal": price_at_signal,
                "logged_at": logged_at,
                "eval_4h": evals_by_signal_id[id_].get(4),
                "eval_24h": evals_by_signal_id[id_].get(24),
            }
        )
    return out


def get_signal_accuracy_stats(horizon_hours: int = 24) -> dict:
    """Accuracy of graded BUY/SELL calls at one horizon (4 or 24 hours).
    HOLD signals are logged and counted but never graded correct/incorrect
    (they're not a directional bet) - `hold` is reported separately from
    `accuracy_pct`, which is computed only over BUY/SELL calls, so a ticker
    that mostly sits at HOLD can't inflate or deflate its own accuracy
    number. `pending` counts signals not old enough (or not yet gradable
    for lack of a current price) to have been evaluated at this horizon."""
    with get_conn() as conn:
        graded_rows = conn.execute(
            """SELECT sl.ticker, se.correct
               FROM signal_log sl
               JOIN signal_evaluations se
                   ON se.signal_log_id = sl.id AND se.horizon_hours = ?""",
            (horizon_hours,),
        ).fetchall()
        pending = conn.execute(
            """SELECT COUNT(*) FROM signal_log sl
               LEFT JOIN signal_evaluations se
                   ON se.signal_log_id = sl.id AND se.horizon_hours = ?
               WHERE se.id IS NULL""",
            (horizon_hours,),
        ).fetchone()[0]

    def _new_bucket():
        return {"correct": 0, "incorrect": 0, "hold": 0}

    per_ticker = defaultdict(_new_bucket)
    overall = _new_bucket()
    for ticker, correct in graded_rows:
        bucket = "hold" if correct is None else ("correct" if correct == 1 else "incorrect")
        per_ticker[ticker][bucket] += 1
        overall[bucket] += 1

    def _accuracy_pct(counts):
        graded = counts["correct"] + counts["incorrect"]
        return round(counts["correct"] / graded * 100, 1) if graded else None

    return {
        "horizon_hours": horizon_hours,
        "correct": overall["correct"],
        "incorrect": overall["incorrect"],
        "hold": overall["hold"],
        "accuracy_pct": _accuracy_pct(overall),
        "pending": pending,
        "per_ticker": {t: {**counts, "accuracy_pct": _accuracy_pct(counts)} for t, counts in per_ticker.items()},
    }


def get_signal(ticker: str, hours: int = 24) -> dict:
    """A simple, fully transparent BUY/SELL/HOLD heuristic - NOT financial
    advice, see the disclaimer everywhere this is shown.

    Deliberately uses two independent, weak signals together rather than
    sentiment alone (which is noisy and easy to game/misjudge on its own):
      - the existing sentiment verdict (bullish/bearish/mixed, from
        verdict_for) over the given lookback window
      - the ticker's most recent day-over-day price direction

    Rule (conservative by design - HOLD is the default unless both signals
    agree):
      BUY  = sentiment BULLISH and price is not falling (up or flat)
      SELL = sentiment BEARISH and price is not rising (down or flat)
      HOLD = everything else - mixed sentiment, insufficient data, or the
             two signals disagree (e.g. bullish chatter while the price is
             actually falling - exactly when a confident call is least
             warranted, not the moment to force a decision).
    """
    counts = get_sentiment_summary(hours=hours).get(ticker, {"bullish": 0, "bearish": 0, "neutral": 0})
    verdict = verdict_for(counts)

    price_info = get_latest_prices().get(ticker, {})
    day_change = price_info.get("day_change_pct")
    if day_change is None:
        price_direction = "UNKNOWN"
    elif day_change > 0:
        price_direction = "UP"
    elif day_change < 0:
        price_direction = "DOWN"
    else:
        price_direction = "FLAT"

    if verdict == "BULLISH" and price_direction in ("UP", "FLAT"):
        signal = "BUY"
        reasoning = "Sentiment is net bullish and price isn't falling."
    elif verdict == "BEARISH" and price_direction in ("DOWN", "FLAT"):
        signal = "SELL"
        reasoning = "Sentiment is net bearish and price isn't rising."
    elif verdict == "NO DATA" or price_direction == "UNKNOWN":
        signal = "HOLD"
        reasoning = "Not enough data yet to form a signal."
    else:
        signal = "HOLD"
        reasoning = "Sentiment and price direction disagree, or sentiment is mixed - conflicting signals."

    return {
        "signal": signal,
        "sentiment_verdict": verdict,
        "price_direction": price_direction,
        "reasoning": reasoning,
    }
