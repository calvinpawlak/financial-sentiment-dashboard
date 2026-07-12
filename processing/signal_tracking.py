"""
Prediction accuracy log, added 2026-07-12 (Calvin: "I want to keep a log of
when the prediction was correct vs incorrect based on movement of the
stock"). Two parts:

1. log_signal_if_changed() - called every ingestion cycle for every ticker.
   Writes a new signal_log row ONLY when the computed BUY/SELL/HOLD signal
   differs from the most recently logged one for that ticker (or none
   exists yet). Logging on every cycle instead would mean ~9 tickers x 12
   cycles/hour (once the 5-minute fast schedule is running) x 24h = far too
   many near-duplicate "still HOLD" rows to be a useful track record -
   logging on CHANGE gives a clean history of actual calls made.

2. evaluate_pending_signals() - called every cycle too (cheap - no network
   calls, just local price lookups already fetched this cycle). Grades any
   logged signal that's now old enough, at two horizons: 4h and 24h.
   Grading rule (mirrors storage.queries.get_signal's own logic):
     BUY  correct  if price is higher at the evaluation horizon
     SELL correct  if price is lower at the evaluation horizon
     HOLD is not a directional call, so it's logged for transparency but
          graded as correct=NULL (neither right nor wrong) rather than
          forcing a fabricated win/loss - see get_signal_accuracy_stats in
          storage/queries.py for how this is surfaced honestly on the
          dashboard (HOLD counted separately from the accuracy %).
   "Evaluated 4h/24h later" really means "at the first cycle occurring at
   or after that many hours have passed" - given a 5-15 min ingestion
   cadence this is accurate to within one cycle, not to the second, and
   that approximation is documented here rather than silently assumed.
"""
import logging
from datetime import datetime, timedelta, timezone

from storage.db import insert_signal_log, insert_signal_evaluation

logger = logging.getLogger(__name__)

EVALUATION_HORIZONS_HOURS = (4, 24)


def _get_last_signal(conn, ticker):
    row = conn.execute(
        """SELECT signal FROM signal_log
           WHERE ticker = ?
           ORDER BY logged_at DESC
           LIMIT 1""",
        (ticker,),
    ).fetchone()
    return row[0] if row else None


def log_signal_if_changed(conn, ticker, signal_info, price_at_signal, logged_at=None):
    """signal_info is the dict returned by storage.queries.get_signal():
    {"signal", "sentiment_verdict", "price_direction", "reasoning"}.
    Returns True if a new row was logged, False if the signal is unchanged
    from the last logged entry for this ticker (no-op)."""
    logged_at = logged_at or datetime.now(timezone.utc).isoformat()
    last_signal = _get_last_signal(conn, ticker)
    if last_signal == signal_info["signal"]:
        return False

    insert_signal_log(
        conn,
        ticker=ticker,
        signal=signal_info["signal"],
        sentiment_verdict=signal_info["sentiment_verdict"],
        price_direction=signal_info["price_direction"],
        reasoning=signal_info["reasoning"],
        price_at_signal=price_at_signal,
        logged_at=logged_at,
    )
    return True


def _grade(signal, price_change_pct):
    if price_change_pct is None:
        return None
    if signal == "BUY":
        return 1 if price_change_pct > 0 else 0
    if signal == "SELL":
        return 1 if price_change_pct < 0 else 0
    return None  # HOLD - not a directional call, see module docstring


def evaluate_pending_signals(conn, current_prices, now=None):
    """current_prices: the dict from storage.queries.get_latest_prices(),
    i.e. {ticker: {"price": ..., ...}}. Grades every signal_log row that has
    crossed a horizon and hasn't been graded at that horizon yet. Returns
    the number of new evaluation rows written."""
    now = now or datetime.now(timezone.utc)
    written = 0

    for horizon in EVALUATION_HORIZONS_HOURS:
        cutoff = (now - timedelta(hours=horizon)).isoformat()
        pending = conn.execute(
            """SELECT sl.id, sl.ticker, sl.signal, sl.price_at_signal
               FROM signal_log sl
               LEFT JOIN signal_evaluations se
                   ON se.signal_log_id = sl.id AND se.horizon_hours = ?
               WHERE se.id IS NULL AND sl.logged_at <= ?""",
            (horizon, cutoff),
        ).fetchall()

        for signal_log_id, ticker, signal, price_at_signal in pending:
            price_info = current_prices.get(ticker)
            current_price = price_info.get("price") if price_info else None
            if current_price is None or price_at_signal is None or price_at_signal == 0:
                continue  # try again next cycle once a price is available

            price_change_pct = (current_price - price_at_signal) / price_at_signal * 100
            correct = _grade(signal, price_change_pct)

            insert_signal_evaluation(
                conn,
                signal_log_id=signal_log_id,
                horizon_hours=horizon,
                evaluated_at=now.isoformat(),
                price_at_evaluation=current_price,
                price_change_pct=price_change_pct,
                correct=correct,
            )
            written += 1

    return written
