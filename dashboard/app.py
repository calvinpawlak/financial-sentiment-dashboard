"""
Layer 4 - interactive Streamlit dashboard.

Run with:
    streamlit run dashboard/app.py

Reads directly from the local SQLite database via storage/queries.py - no
external connectors, no cloud services, nothing beyond what's already on
this machine. Auto-refreshes every 60 seconds so it picks up new data as
main.py's Task Scheduler job writes it.

Honest framing: "live" here means "reflects the latest completed
ingestion cycle" (every ~15 minutes, per setup_task_scheduler.ps1), not
sub-second real-time - that's genuinely how often new data arrives, so
refreshing the dashboard faster than that wouldn't show anything new.
"""
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
)

st.set_page_config(page_title="Financial Sentiment Dashboard", page_icon="📈", layout="wide")

# Auto-refresh every 60s - see module docstring on why not faster.
st_autorefresh(interval=60_000, key="autorefresh")

VERDICT_LABELS = {
    "BULLISH": "🟢 BULLISH",
    "BEARISH": "🔴 BEARISH",
    "MIXED/NEUTRAL": "⚪ MIXED/NEUTRAL",
    "NO DATA": "⚫ NO DATA",
}
SIGNAL_LABELS = {
    "BUY": "🟢 BUY",
    "SELL": "🔴 SELL",
    "HOLD": "🟡 HOLD",
}

st.title("📈 Financial Sentiment Dashboard")
st.caption(
    f"Last checked: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  ·  "
    "Auto-refreshes every 60s  ·  Reflects the latest completed ingestion cycle (~every 15 min)"
)

st.warning(
    "**Not financial advice.** The Signal column/metric below is a simple, mechanical rule — "
    "public sentiment direction combined with the ticker's latest price direction — not a "
    "recommendation from a financial advisor. It defaults to HOLD whenever those two inputs "
    "disagree or data is thin. Treat it as one heuristic input among many, and do your own "
    "research before making any investment decision.",
    icon="⚠️",
)

# --- Sidebar controls -------------------------------------------------------
st.sidebar.header("Controls")
hours = st.sidebar.select_slider(
    "Lookback window",
    options=[1, 6, 12, 24, 48, 72, 168],
    value=24,
    format_func=lambda h: f"{h}h" if h < 48 else f"{h // 24}d",
)

known_tickers = get_known_tickers()
if not known_tickers:
    st.warning("No data yet — run `python main.py` at least once, then reload this page.")
    st.stop()

# --- Overview table ----------------------------------------------------
summary = get_sentiment_summary(hours=hours)
prices = get_latest_prices()

overview_rows = []
for ticker in known_tickers:
    counts = summary.get(ticker, {"bullish": 0, "bearish": 0, "neutral": 0})
    verdict = verdict_for(counts)
    price_info = prices.get(ticker, {})
    signal_info = get_signal(ticker, hours=hours)
    overview_rows.append(
        {
            "Ticker": ticker,
            "Price": price_info.get("price"),
            "Day Change %": price_info.get("day_change_pct"),
            "Bullish": counts["bullish"],
            "Bearish": counts["bearish"],
            "Neutral": counts["neutral"],
            "Posts": sum(counts.values()),
            "Verdict": VERDICT_LABELS.get(verdict, verdict),
            "Signal": SIGNAL_LABELS.get(signal_info["signal"], signal_info["signal"]),
        }
    )

overview_df = pd.DataFrame(overview_rows)

st.subheader(f"Overview — last {hours}h")
st.dataframe(
    overview_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Price": st.column_config.NumberColumn(format="$%.2f"),
        "Day Change %": st.column_config.NumberColumn(format="%+.2f%%"),
    },
)

# --- Sentiment breakdown chart ------------------------------------------
st.subheader("Sentiment breakdown by ticker")
breakdown_fig = go.Figure()
breakdown_fig.add_bar(name="Bullish", x=overview_df["Ticker"], y=overview_df["Bullish"], marker_color="#16a34a")
breakdown_fig.add_bar(name="Bearish", x=overview_df["Ticker"], y=overview_df["Bearish"], marker_color="#dc2626")
breakdown_fig.add_bar(name="Neutral", x=overview_df["Ticker"], y=overview_df["Neutral"], marker_color="#9ca3af")
breakdown_fig.update_layout(
    barmode="stack",
    height=400,
    legend=dict(orientation="h", yanchor="bottom", y=1.02),
    margin=dict(t=30),
)
st.plotly_chart(breakdown_fig, use_container_width=True)

# --- Per-ticker drill-down -----------------------------------------------
st.subheader("Drill down")
selected = st.selectbox("Ticker", known_tickers)

col1, col2 = st.columns([2, 1])

with col1:
    series = get_sentiment_timeseries(selected, hours=hours)
    price_hist = get_price_history(selected, hours=hours)

    if series:
        s_df = pd.DataFrame(series)
        p_df = pd.DataFrame(price_hist) if price_hist else pd.DataFrame(columns=["fetched_at", "price"])

        trend_fig = go.Figure()
        trend_fig.add_trace(
            go.Scatter(
                x=s_df["bucket"],
                y=s_df["avg_compound"],
                name="Avg sentiment (VADER compound)",
                mode="lines+markers",
                line=dict(color="#2563eb"),
                yaxis="y1",
            )
        )
        if not p_df.empty:
            trend_fig.add_trace(
                go.Scatter(
                    x=p_df["fetched_at"],
                    y=p_df["price"],
                    name="Price",
                    mode="lines",
                    line=dict(color="#f59e0b", dash="dot"),
                    yaxis="y2",
                )
            )
        trend_fig.update_layout(
            height=400,
            title=f"{selected} — sentiment vs. price",
            yaxis=dict(title="Avg sentiment (-1 to +1)", range=[-1, 1]),
            yaxis2=dict(title="Price ($)", overlaying="y", side="right"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(t=40),
        )
        st.plotly_chart(trend_fig, use_container_width=True)
    else:
        st.info(f"No scored sentiment data yet for {selected} in this window.")

with col2:
    counts = summary.get(selected, {"bullish": 0, "bearish": 0, "neutral": 0})
    verdict = verdict_for(counts)
    signal_info = get_signal(selected, hours=hours)

    st.metric("Signal", SIGNAL_LABELS.get(signal_info["signal"], signal_info["signal"]))
    st.caption(f"Why: {signal_info['reasoning']} (sentiment {signal_info['sentiment_verdict']}, price {signal_info['price_direction']})")

    st.metric("Verdict", VERDICT_LABELS.get(verdict, verdict))

    price_info = prices.get(selected, {})
    if price_info.get("price") is not None:
        delta = f"{price_info['day_change_pct']:+.2f}%" if price_info.get("day_change_pct") is not None else None
        st.metric("Latest price", f"${price_info['price']:.2f}", delta=delta)

    st.metric("Posts analyzed", sum(counts.values()))

    social_agg = get_latest_social_sentiment_agg(selected)
    agg_lines = []
    for platform, label in (("reddit", "Reddit"), ("twitter", "Twitter/X")):
        info = social_agg.get(platform)
        if info and info["mention"] is not None:
            agg_lines.append(
                f"**{label}** (Finnhub): {info['mention']} mentions, "
                f"+{info['positive_score']:.2f} / -{info['negative_score']:.2f}"
            )
    if agg_lines:
        st.caption("Supplementary — Finnhub's own aggregated mention/sentiment rollup, "
                    "not part of the counts/verdict above:")
        for line in agg_lines:
            st.caption(line)

st.subheader(f"Recent posts — {selected}")
posts = get_recent_posts(selected, limit=15)
if posts:
    posts_df = pd.DataFrame(posts)
    posts_df["scored_at"] = pd.to_datetime(posts_df["scored_at"]).dt.strftime("%Y-%m-%d %H:%M UTC")
    st.dataframe(
        posts_df.rename(
            columns={"source": "Source", "text": "Text", "label": "Label", "compound": "Score", "scored_at": "Time"}
        )[["Time", "Source", "Label", "Score", "Text"]],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No posts to show yet.")

st.divider()
st.caption(
    "Sentiment scores are heuristic (VADER + a small finance-slang patch), and the BUY/SELL/HOLD "
    "Signal is a simple mechanical rule combining that sentiment with recent price direction — "
    "neither is financial advice. Treat both as one input among many, and do your own research "
    "before making investment decisions."
)
