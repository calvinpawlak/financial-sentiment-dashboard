# Tasks

Written 2026-07-12. Reflects state at the time of migration from Claude/Cowork
to ChatGPT/Codex.

## Now

- [ ] Add `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD` to local `.env`, then
  live-test the new Bluesky Fast-cycle source.

- [ ] Finish migrating this project to ChatGPT/Codex - this document set is
  part of that (see `CURRENT_STATUS.md` for the full picture).
- [ ] Confirm the most recent local commits (hidden-window Task Scheduler
  fix, this migration doc set) are committed and pushed to GitHub.
- [ ] Confirm the Render deploy is currently green/"Live" on the latest
  commit (it failed at least once mid-project on a bug that's since been
  fixed - worth a fresh check rather than assuming).

## Next

- [ ] Verify whether the old single-task Task Scheduler job
  (`FinancialSentimentDashboard-Ingestion`, pre-cadence-split) still exists
  on Calvin's machine and remove it if so - it was flagged for manual
  removal but never confirmed done.
- [ ] Let enough time pass for real signal_log history to accumulate
  (several days+), then actually review the prediction accuracy log with
  the new baseline/CI/BUY-SELL-split context to see if any data source or
  threshold genuinely looks worth revising - this was the whole point of
  the recent logic audit, but there wasn't enough graded history yet to
  act on at the time it was done.
- [ ] Re-verify Reddit API access status - file a check on the pending
  "Responsible Builder Policy" request if it's been a while with no
  response.

## Later

- [ ] Source-specific grading horizons for the accuracy log - research
  during the logic audit suggested different platforms (fast chatter vs.
  slower news) may have meaningfully different natural prediction
  horizons, which the current flat 4h/24h grading doesn't account for.
  Deferred until there's enough per-source history to make this
  worthwhile.
- [ ] Consider moving ingestion itself into the cloud (not just the
  dashboard) so the public site stays fresh even when Calvin's PC is off -
  explicitly deferred as a larger, separate project.
- [ ] Add more tickers or subreddits if Calvin wants broader coverage
  (config-only change).
- [ ] Price alerts / notifications layer on top of the existing verdicts -
  mentioned as a possible future direction, not started.
- [ ] Consider whether `MIN_GRADED_FOR_CONFIDENCE = 20` and the 4h/24h
  horizons are still the right thresholds once real history exists to
  evaluate them against.

## Waiting

- [x] Configure `SEC_USER_AGENT` in `.env` and validate one SEC slow-cycle fetch
  (completed 2026-07-15; 58 unique filing events stored).

- [ ] Reddit API access approval - external dependency, Calvin filed a
  request under Reddit's "Responsible Builder Policy"; no fixed timeline,
  reportedly anywhere from days to no response at all. Pipeline runs fine
  without it in the meantime (StockTwits/FinViz/Finnhub/Google News are
  unaffected).
- [ ] StockTwits approved API access - the legacy unauthenticated endpoint
  began returning 403 on 2026-07-15, and new developer registrations are
  currently paused. The pipeline degrades cleanly in the meantime.

## Completed

- [x] Codex recovery validation (2026-07-15): standardized on Python 3.12
  in `.venv`, centralized `.env` loading, migrated the local SQLite schema,
  added persistent offline tests, pinned direct dependencies, and moved
  both scheduled tasks to the project virtual environment.

- [x] Layer 1 (data ingestion): prices (yfinance), StockTwits, Reddit
  (pending approval), FinViz news.
- [x] Layer 2 (sentiment scoring): VADER + finance-slang lexicon patch.
- [x] Layer 3 (storage/backend): indexes, WAL mode, shared query layer,
  opt-in `prune.py`.
- [x] Layer 4 (dashboard): Streamlit (first), then a custom Flask app
  (primary, matching a visual mockup) with Streamlit kept as fallback.
- [x] Added Finnhub (company news + attempted social-sentiment) and Google
  News as extra layer-1 sources.
- [x] BUY/SELL/HOLD Signal feature with disclaimer.
- [x] Prediction accuracy log (log-on-change, dual 4h/24h grading, HOLD
  never scored).
- [x] Split ingestion cadence (5-min fast / 15-min slow).
- [x] Dual SQLite/Postgres backend support via `DATABASE_URL`.
- [x] Public hosting (Neon + Render), including `render.yaml` and full
  setup documentation.
- [x] Logic audit: fixed the price/sentiment-window mismatch bug; added
  baseline comparison, Wilson confidence intervals, BUY/SELL split, and
  per-source attribution to the accuracy log.
- [x] Fixed a `.format()`/curly-brace bug in `storage/db.py` that broke
  both local ingestion and the Render deploy.
- [x] Fixed the Task Scheduler console-window-flash issue via a generated
  hidden VBScript launcher.
- [x] This migration document set (README updates, `PROJECT_CONTEXT.md`,
  `AGENTS.md`, `MEMORY.md`, `DECISIONS.md`,
  `CURRENT_STATUS.md`, `WORKFLOWS.md`, `CONNECTORS.md`, `TASKS.md`,
  `CONVERSATION_SUMMARIES/`).
- [x] Corrected `AGENTS.md` naming/placement after confirming Codex reads
  an `AGENTS.md` file automatically rather than a pasted "Project
  Instructions" field - the original `CHATGPT_PROJECT_INSTRUCTIONS.md` was
  replaced with a redirect stub.
