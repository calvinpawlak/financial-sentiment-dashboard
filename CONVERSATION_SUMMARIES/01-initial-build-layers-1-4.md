# Conversation Summary: Initial Build (Layers 1-4)

**Date:** 2026-07-12

## What happened

Calvin asked to build a live financial sentiment dashboard. Before writing
code, scoping questions were asked and answered: free-data sources only
(no paid X/Instagram), local Python + OS-scheduler deployment (no
persistent cloud service at this stage), and a fixed ticker watchlist.

Built in sequence:
- **Layer 1 (ingestion):** `main.py` running one cycle per invocation;
  yfinance for prices, StockTwits (free public endpoint), Reddit (PRAW,
  found to require a gated manual approval Reddit had just rolled out),
  FinViz (HTML scrape for news). Confirmed working on Calvin's own machine
  after fixing two real bugs: a yfinance `fast_info` quirk returning no
  data, and a Reddit placeholder-credential value that caused a real
  (doomed) OAuth call instead of skipping cleanly.
- **Layer 2 (sentiment scoring):** VADER via `processing/sentiment.py`,
  with a custom finance-slang lexicon patch added after discovering VADER
  misreads terms like "crushes" (as violent, not "beat big").
  `report.py` added as a quick CLI summary.
- **Layer 3 (storage/backend):** hardened SQLite - indexes, WAL journal
  mode (needed once a scheduler would be writing every 15 min while
  `report.py` might read concurrently), a shared `storage/queries.py`
  query layer, and an opt-in `prune.py` retention script. Caught and fixed
  a real bug: SQLite's `VACUUM` can't run inside the same transaction as
  deletes.
- **Layer 4 (dashboard):** a Streamlit app (`dashboard/app.py`) reading the
  shared query layer, with an hourly-bucketed price/sentiment trend chart
  and an overview table. Confirmed with a headless smoke test (no browser
  available in the build environment).

## Ticker list resolved

Started with SPY, QQQ, MSFT, AAPL, GOOG, NVDA, NDAQ, VOO, SPCX, INX. INX
was confirmed invalid/delisted via Yahoo's own error message and dropped.
^GSPC was tried as a replacement but only gets price coverage (no
StockTwits/FinViz coverage for raw index symbols), so it was dropped too.
SPCX was initially miscategorized as possibly invalid but confirmed to be
a real, newly-IPO'd ticker (SpaceX, IPO'd 2026-06-12). Final list: SPY,
QQQ, MSFT, AAPL, GOOG, NVDA, NDAQ, VOO, SPCX (9 tickers).

## Unresolved at the end of this phase

- Reddit API access still pending manual approval.
- No BUY/SELL/HOLD signal yet (came in the next phase).
- No public hosting yet (local-only).

See `DECISIONS.md` for the formal decision records from this phase, and
`README.md` for the current (post-audit) state of everything built here.
