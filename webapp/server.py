"""
Layer 4 (v2) - local Flask web app, replacing the Streamlit dashboard as the
primary UI. Chosen over a Streamlit reskin or a regenerated-static-HTML file
so the frontend can be fully custom-styled (card grid, gradient chart,
inline sparklines) and refresh smoothly via polling instead of a full-page
rerun.

Run with:
    python webapp/server.py
Then open http://localhost:5000 in a browser.

This is a thin JSON API layer over storage/queries.py - no new query logic,
no new database access patterns, just HTTP plumbing. The actual frontend
lives in webapp/static/ (index.html, style.css, app.js) and is served as
static files; app.js calls the /api/* routes below with fetch().

The original Streamlit dashboard (dashboard/app.py) is left in place as a
lightweight fallback - `streamlit run dashboard/app.py` still works if you
ever want it instead of running a local server.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request

from storage.queries import (
    get_sentiment_summary,
    verdict_for,
    get_latest_prices,
    get_recent_posts,
    get_sentiment_timeseries,
    get_price_history,
    get_known_tickers,
    get_signal,
    get_latest_social_sentiment_agg,
    get_signal_log,
    get_signal_accuracy_stats,
)

app = Flask(__name__, static_folder="static", static_url_path="")

# Valid lookback windows - same set exposed in the old Streamlit sidebar.
_VALID_HOURS = {1, 6, 12, 24, 48, 72, 168}


def _parse_hours() -> int:
    try:
        hours = int(request.args.get("hours", 24))
    except (TypeError, ValueError):
        hours = 24
    return hours if hours in _VALID_HOURS else 24


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/tickers")
def api_tickers():
    return jsonify(get_known_tickers())


@app.route("/api/overview")
def api_overview():
    hours = _parse_hours()
    known_tickers = get_known_tickers()
    summary = get_sentiment_summary(hours=hours)
    prices = get_latest_prices()

    rows = []
    for ticker in known_tickers:
        counts = summary.get(ticker, {"bullish": 0, "bearish": 0, "neutral": 0})
        verdict = verdict_for(counts)
        price_info = prices.get(ticker, {})
        signal_info = get_signal(ticker, hours=hours)
        rows.append(
            {
                "ticker": ticker,
                "price": price_info.get("price"),
                "day_change_pct": price_info.get("day_change_pct"),
                "bullish": counts["bullish"],
                "bearish": counts["bearish"],
                "neutral": counts["neutral"],
                "posts": sum(counts.values()),
                "verdict": verdict,
                "signal": signal_info["signal"],
                "reasoning": signal_info["reasoning"],
            }
        )
    return jsonify({"hours": hours, "tickers": rows})


@app.route("/api/ticker/<ticker>")
def api_ticker_detail(ticker):
    hours = _parse_hours()
    ticker = ticker.upper()

    counts = get_sentiment_summary(hours=hours).get(ticker, {"bullish": 0, "bearish": 0, "neutral": 0})
    verdict = verdict_for(counts)
    signal_info = get_signal(ticker, hours=hours)
    price_info = get_latest_prices().get(ticker, {})
    social_agg = get_latest_social_sentiment_agg(ticker)

    return jsonify(
        {
            "ticker": ticker,
            "hours": hours,
            "price_info": price_info,
            "counts": counts,
            "verdict": verdict,
            "signal": signal_info,
            "social_agg": social_agg,
            "price_history": get_price_history(ticker, hours=hours),
            "sentiment_timeseries": get_sentiment_timeseries(ticker, hours=hours),
            "recent_posts": get_recent_posts(ticker, limit=15),
        }
    )


@app.route("/api/accuracy")
def api_accuracy():
    """Prediction accuracy log, added 2026-07-12. Returns both grading
    horizons (4h and 24h) - see storage.queries.get_signal_accuracy_stats
    for what "correct"/"hold"/"pending" mean here."""
    return jsonify(
        {
            "horizon_4h": get_signal_accuracy_stats(horizon_hours=4),
            "horizon_24h": get_signal_accuracy_stats(horizon_hours=24),
        }
    )


@app.route("/api/signal-log")
def api_signal_log():
    ticker = request.args.get("ticker") or None
    if ticker:
        ticker = ticker.upper()
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 200))  # sane bounds regardless of what's requested
    return jsonify(get_signal_log(ticker=ticker, limit=limit))


if __name__ == "__main__":
    # debug=False: this reads a SQLite DB that main.py may be writing to on
    # its own Task Scheduler cadence - the Flask reloader's double-process
    # startup isn't worth the risk of a confusing double-init here.
    app.run(host="127.0.0.1", port=5000, debug=False)
