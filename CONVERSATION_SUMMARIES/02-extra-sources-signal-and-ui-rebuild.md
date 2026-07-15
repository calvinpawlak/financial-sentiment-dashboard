# Conversation Summary: Extra Sources, BUY/SELL/HOLD Signal, and UI Rebuild

**Date:** 2026-07-12 (continuation of the same day's work)

## What happened

**More data sources.** Calvin asked what else was available beyond
StockTwits/Reddit. Researched current (2026) free-tier terms before
building anything - ruled out Alpha Vantage (25 req/day free cap, would
exhaust in under an hour) and NewsAPI.org (free tier is dev/localhost-only,
blocked in a real deployed app). Built Finnhub (`ingestion/finnhub_source.py`
- company news, plus an attempted aggregated Reddit/Twitter
social-sentiment endpoint) and Google News RSS
(`ingestion/google_news_source.py` - unofficial feed, no key). On Calvin's
first real run with a Finnhub key, `/stock/social-sentiment` returned a
clean 403 - confirmed paid-only, not a bug. Fixed a real inefficiency this
exposed: the original code retried the same 403 for every ticker every
cycle; patched to detect it once and stop.

**BUY/SELL/HOLD Signal.** Calvin asked for the dashboard to recommend
buy/sell/hold. Built as a deliberately conservative rule combining the
existing sentiment verdict with the ticker's price direction - HOLD unless
both agree. Added a prominent "not financial advice" warning banner and a
per-ticker "why" reasoning line, not just a footer disclaimer.

**Dashboard UI rebuild.** Calvin shared a reference mockup screenshot (dark
fintech theme, card-grid KPIs, gradient chart, sparkline table) and asked
for something similar. Offered three options (reskinned Streamlit, a
regenerated static HTML file, or a local Flask/FastAPI app); Calvin picked
Flask. Built `webapp/` (Flask API + plain HTML/CSS/vanilla JS frontend,
Chart.js for charts) as the new primary dashboard, keeping the Streamlit
version as a documented fallback. Fixed a real bug shortly after: the main
chart and the "recent chatter" panel could both go blank together because
one try/catch block covered all three render calls - split into
independent try/catch blocks per panel so one failure can't blank the
others, plus proper alignment of price history (per-cycle timestamps) and
sentiment timeseries (hourly-bucketed) onto one shared set of hour labels.

## Unresolved at the end of this phase

- No prediction accuracy log yet.
- Still local-only, no public hosting.
- Still on a single ~15-minute ingestion cadence for all sources.

See `DECISIONS.md` for formal records and `README.md` for current state.
