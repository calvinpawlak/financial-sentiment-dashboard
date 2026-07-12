"""
Layer 3 - shared read queries.

Centralizes the SQL that report.py (and eventually the layer 4 dashboard)
needs, so there's one place to fix/optimize queries instead of duplicated
ad hoc SQL scattered across every consumer.
"""
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from storage.db import get_conn

# Below this many graded BUY/SELL calls at a horizon, an accuracy percentage
# is close to a coin flip dressed up as a stat - flagged so the dashboard can
# show a caution instead of a bare, falsely-confident number (added
# 2026-07-12 after reviewing the log with Calvin).
MIN_GRADED_FOR_CONFIDENCE = 20


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


def get_sentiment_summary_by_source(ticker: str, hours: int = 24) -> dict:
    """Same as get_sentiment_summary(), but broken out by data source for a
    single ticker - added 2026-07-12 so each logged BUY/SELL/HOLD call can
    record which source(s) actually drove it (StockTwits chatter? Finnhub
    news? Reddit?). Without this, the accuracy log can only be sliced by
    ticker, not by which of the 5 ingestion sources produced the sentiment
    behind a given call - which matters if some sources turn out to be
    noise and others real signal.
    Returns {source: {"bullish": n, "bearish": n, "neutral": n}}."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT source, label, COUNT(*)
               FROM scored_sentiment
               WHERE ticker = ? AND scored_at >= ?
               GROUP BY source, label""",
            (ticker, cutoff),
        ).fetchall()

    summary = defaultdict(lambda: {"bullish": 0, "bearish": 0, "neutral": 0})
    for source, label, count in rows:
        summary[source][label] = count
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


def _direction_from_pct(pct: float) -> str:
    if pct > 0:
        return "UP"
    if pct < 0:
        return "DOWN"
    return "FLAT"


def get_price_change_over_window(ticker: str, hours: int) -> tuple:
    """Price % change measured over the SAME lookback window as the
    sentiment side of get_signal() - added 2026-07-12 to fix a real
    inconsistency Calvin caught: the Signal's price component previously
    always used yfinance's fixed day-over-day change_pct, even when the
    dashboard's 1H/6H/etc. tab selected a much shorter sentiment window. A
    1-hour sentiment read was being combined with a full day's price move.

    Uses our own raw_prices samples (earliest vs latest inside the window)
    so both halves of the Signal are measured on the same clock. Falls back
    to the fixed day-change (with is_windowed=False) if there aren't yet at
    least 2 in-window price samples - e.g. right after a fresh deploy, before
    enough ingestion cycles have run to fill the window. That fallback is
    imperfect but better than reporting UNKNOWN/HOLD for every ticker during
    the first hour of a new install; is_windowed tells the caller (and the
    dashboard) which measurement was actually used.

    Returns (direction, pct_change, is_windowed). direction is
    UP/DOWN/FLAT/UNKNOWN; pct_change is None only if no price data exists
    at all yet for this ticker.
    """
    history = get_price_history(ticker, hours=hours)
    if len(history) >= 2 and history[0]["price"]:
        pct = (history[-1]["price"] - history[0]["price"]) / history[0]["price"] * 100
        return _direction_from_pct(pct), pct, True

    price_info = get_latest_prices().get(ticker, {})
    day_change = price_info.get("day_change_pct")
    if day_change is None:
        return "UNKNOWN", None, False
    return _direction_from_pct(day_change), day_change, False


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
                      sl.reasoning, sl.price_at_signal, sl.logged_at, sl.source_breakdown
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
    for id_, ticker_, signal, verdict, direction, reasoning, price_at_signal, logged_at, source_breakdown in rows:
        try:
            sources = json.loads(source_breakdown) if source_breakdown else None
        except (TypeError, ValueError):
            sources = None  # tolerate malformed/legacy values rather than 500ing the API
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
                "source_breakdown": sources,
                "eval_4h": evals_by_signal_id[id_].get(4),
                "eval_24h": evals_by_signal_id[id_].get(24),
            }
        )
    return out


def _wilson_interval(correct: int, graded: int, z: float = 1.96) -> tuple:
    """95% Wilson score confidence interval for a correct/graded proportion,
    added 2026-07-12 - a bare accuracy percentage looks equally confident at
    n=2 and n=200, which is misleading with a watchlist this small. Wilson
    (rather than the simpler normal-approximation interval) holds up better
    at small n and never produces an out-of-range bound. Returns
    (lower_pct, upper_pct), or (None, None) if graded == 0."""
    if graded == 0:
        return None, None
    phat = correct / graded
    denom = 1 + z ** 2 / graded
    center = phat + z ** 2 / (2 * graded)
    margin = z * math.sqrt(phat * (1 - phat) / graded + z ** 2 / (4 * graded ** 2))
    lower = max(0.0, (center - margin) / denom)
    upper = min(1.0, (center + margin) / denom)
    return round(lower * 100, 1), round(upper * 100, 1)


def get_signal_accuracy_stats(horizon_hours: int = 24) -> dict:
    """Accuracy of graded BUY/SELL calls at one horizon (4 or 24 hours).
    HOLD signals are logged and counted but never graded correct/incorrect
    (they're not a directional bet) - `hold` is reported separately from
    `accuracy_pct`, which is computed only over BUY/SELL calls, so a ticker
    that mostly sits at HOLD can't inflate or deflate its own accuracy
    number. `pending` counts signals not old enough (or not yet gradable
    for lack of a current price) to have been evaluated at this horizon.

    Added 2026-07-12, after reviewing the log with Calvin, three things a
    bare accuracy percentage was missing:
      - `baseline_up_pct` / `baseline_n`: the fraction of ALL graded
        evaluations at this horizon (BUY/SELL/HOLD alike) where price simply
        went up. Markets drift upward over time, so a BUY-heavy rule can
        look "accurate" purely by riding that drift, not because sentiment
        adds real predictive value - compare accuracy_pct to this baseline
        before crediting the signal itself.
      - `accuracy_ci_low` / `accuracy_ci_high`: a 95% Wilson confidence
        interval on the overall accuracy_pct, and `low_sample` (True below
        MIN_GRADED_FOR_CONFIDENCE) so the dashboard can flag "not enough
        calls yet to trust this number" instead of showing a falsely
        precise percentage.
      - `by_signal`: accuracy broken out separately for BUY vs SELL calls
        (a confusion-matrix-style split), since a rule can be strong on
        BUYs and weak on SELLs (or vice versa) and a single pooled number
        hides that entirely.
    """
    with get_conn() as conn:
        graded_rows = conn.execute(
            """SELECT sl.ticker, sl.signal, se.correct
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
        baseline_rows = conn.execute(
            """SELECT price_change_pct FROM signal_evaluations
               WHERE horizon_hours = ? AND price_change_pct IS NOT NULL""",
            (horizon_hours,),
        ).fetchall()

    def _new_bucket():
        return {"correct": 0, "incorrect": 0, "hold": 0}

    per_ticker = defaultdict(_new_bucket)
    per_signal = {"BUY": _new_bucket(), "SELL": _new_bucket()}
    overall = _new_bucket()
    for ticker, signal, correct in graded_rows:
        bucket = "hold" if correct is None else ("correct" if correct == 1 else "incorrect")
        per_ticker[ticker][bucket] += 1
        overall[bucket] += 1
        if signal in per_signal:
            per_signal[signal][bucket] += 1

    def _accuracy_pct(counts):
        graded = counts["correct"] + counts["incorrect"]
        return round(counts["correct"] / graded * 100, 1) if graded else None

    def _with_ci(counts):
        graded = counts["correct"] + counts["incorrect"]
        ci_low, ci_high = _wilson_interval(counts["correct"], graded)
        return {
            **counts,
            "accuracy_pct": _accuracy_pct(counts),
            "graded": graded,
            "accuracy_ci_low": ci_low,
            "accuracy_ci_high": ci_high,
            "low_sample": graded < MIN_GRADED_FOR_CONFIDENCE,
        }

    baseline_total = len(baseline_rows)
    baseline_up = sum(1 for (pct,) in baseline_rows if pct is not None and pct > 0)
    baseline_up_pct = round(baseline_up / baseline_total * 100, 1) if baseline_total else None

    return {
        "horizon_hours": horizon_hours,
        **_with_ci(overall),
        "pending": pending,
        "baseline_up_pct": baseline_up_pct,
        "baseline_n": baseline_total,
        "by_signal": {sig: _with_ci(counts) for sig, counts in per_signal.items()},
        "per_ticker": {t: _with_ci(counts) for t, counts in per_ticker.items()},
    }


def get_signal(ticker: str, hours: int = 24) -> dict:
    """A simple, fully transparent BUY/SELL/HOLD heuristic - NOT financial
    advice, see the disclaimer everywhere this is shown.

    Deliberately uses two independent, weak signals together rather than
    sentiment alone (which is noisy and easy to game/misjudge on its own):
      - the existing sentiment verdict (bullish/bearish/mixed, from
        verdict_for) over the given lookback window
      - the ticker's price direction over that SAME window (fixed
        2026-07-12 - this used to always be yfinance's fixed day-over-day
        change regardless of the selected window, so a 1-hour sentiment
        read could get combined with a full day's price move; see
        get_price_change_over_window)

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

    price_direction, price_change_pct, is_windowed = get_price_change_over_window(ticker, hours)
    window_note = (
        f"{price_change_pct:+.2f}% over this window" if is_windowed and price_change_pct is not None
        else f"{price_change_pct:+.2f}% day change - not enough in-window price history yet" if price_change_pct is not None
        else "no price data yet"
    )

    if verdict == "BULLISH" and price_direction in ("UP", "FLAT"):
        signal = "BUY"
        reasoning = f"Sentiment is net bullish and price isn't falling ({window_note})."
    elif verdict == "BEARISH" and price_direction in ("DOWN", "FLAT"):
        signal = "SELL"
        reasoning = f"Sentiment is net bearish and price isn't rising ({window_note})."
    elif verdict == "NO DATA" or price_direction == "UNKNOWN":
        signal = "HOLD"
        reasoning = "Not enough data yet to form a signal."
    else:
        signal = "HOLD"
        reasoning = f"Sentiment and price direction disagree, or sentiment is mixed - conflicting signals ({window_note})."

    return {
        "signal": signal,
        "sentiment_verdict": verdict,
        "price_direction": price_direction,
        "price_change_pct": price_change_pct,
        "price_change_is_windowed": is_windowed,
        "reasoning": reasoning,
    }
