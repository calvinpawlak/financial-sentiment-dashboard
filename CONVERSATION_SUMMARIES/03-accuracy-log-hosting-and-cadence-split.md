# Conversation Summary: Prediction Accuracy Log, Public Hosting, and Split Cadence

**Date:** 2026-07-12 (continuation of the same day's work)

## What happened

**Prediction accuracy log.** Calvin wanted to track whether the BUY/SELL/HOLD
Signal actually calls the market correctly. Built `signal_log` (every time a
ticker's Signal changes, log it - not every cycle) and `signal_evaluations`
(grades each logged Signal against the ticker's own price move at two fixed
horizons after the Signal fired: 4h and 24h). HOLD calls are never graded -
there's no "correct" outcome to score a non-call against. Added an accuracy
panel to the Flask dashboard.

**Public hosting.** Calvin wanted the dashboard viewable without leaving his
PC on and a browser open. Researched free-tier hosting options currently
available. Rejected Railway (free tier removed / trial-credit only now),
Fly.io (card-required free allowance), Supabase (evaluated as a Postgres
option but Neon's scale-to-zero fit better for a low-traffic hobby project),
and Render's own managed Postgres (paid-only; Render doesn't offer a free
DB). Landed on: Neon (free Postgres) + Render (free web service). Added
`render.yaml`, a `_PGConnAdapter` facade in `storage/db.py` so the exact same
code path works against SQLite locally or Postgres when `DATABASE_URL` is
set, and walked Calvin step-by-step through creating both accounts, wiring
`DATABASE_URL` into Render's Environment tab, and connecting the GitHub
repo. Confirmed working end-to-end from a screenshot Calvin shared of the
live public page.

**Split ingestion cadence.** Realized StockTwits/prices could support a much
tighter loop than FinViz/Google News (which have slower natural update
rates and, in FinViz's case, scraping terms discouraging high-frequency
hits). Split `main.py` into `--fast-only` (yfinance, StockTwits, Reddit,
Finnhub - every 5 min) and `--slow-only` (FinViz, Google News - every 15
min), each with its own Task Scheduler job.

## Errors hit and fixed in this phase

- `ModuleNotFoundError: No module named 'psycopg2'` on first Neon-connected
  run - `requirements.txt` had been updated but not reinstalled; fixed with
  `pip install -r requirements.txt`.
- A combined one-line PowerShell command (`git branch -M main git remote add
  origin ... git push -u origin main`) failed - PowerShell needs separate
  commands per line or joined with `;`, not just spaces.
- `KeyError: 'source'` from `storage/db.py` - a table-creation SQL constant
  was run through `.format()`, and a code *comment* elsewhere in the same
  string contained a literal `{source: {bullish,...}}`, which `.format()`
  misread as a placeholder. Fixed by rewriting the comment to avoid curly
  braces; verified with an isolated Python test and a full grep for stray
  `{` in the file. This same error recurred once more on Render because the
  fix existed locally but hadn't been pushed yet - resolved by walking
  Calvin through `git add`/`commit`/`push`.

## Unresolved at the end of this phase

- No statistical rigor yet in the accuracy log (no baseline comparison, no
  confidence interval, no BUY/SELL split) - addressed in the next phase.
- Only SPCX and AAPL had shown per-source tags in the signal log at this
  point - later confirmed as expected (source attribution didn't exist
  retroactively; it only started populating going forward).

See `DECISIONS.md` for the formal records and `README.md` for current state.
