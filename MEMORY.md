# Memory

Durable, project-specific facts and preferences that should stay
consistent across sessions and across the migration to ChatGPT/Codex.
Distilled 2026-07-12 from this project's working history. Items marked
**[unverified/may be stale]** should be double-checked against the current
code before being treated as fact.

## Naming conventions

- Project folder: `Financial Sentiment Dashboard` (outer, human-facing) >
  `financial-sentiment-dashboard/` (inner, actual git repo root - lowercase,
  hyphenated).
- GitHub repo: `calvinpawlak/financial-sentiment-dashboard`.
- Render service name: `financial-sentiment-dashboard` (public URL:
  `https://financial-sentiment-dashboard.onrender.com`).
- Windows Task Scheduler task names: `FinancialSentimentDashboard-Ingestion-Fast`
  and `FinancialSentimentDashboard-Ingestion-Slow`. An older single-task
  version (`FinancialSentimentDashboard-Ingestion`, no Fast/Slow suffix) may
  still exist on Calvin's machine from before the cadence split - check for
  and remove it if found, rather than assuming a clean slate.
- "Layer 1/2/3/4" = ingestion / processing / storage / dashboard, used
  throughout code comments, README, and commit messages. Keep using this
  numbering if adding a genuinely new stage rather than inventing new
  terminology.

## Fixed facts (stable, don't relitigate without a new explicit request)

- **Ticker list (9, fixed):** SPY, QQQ, MSFT, AAPL, GOOG, NVDA, NDAQ, VOO,
  SPCX. SPCX = Space Exploration Technologies Corp (SpaceX), IPO'd Nasdaq
  2026-06-12 - confirmed valid despite looking unfamiliar. INX and ^GSPC
  were both tried and dropped (INX isn't a real symbol on any source used
  here; ^GSPC only gets price coverage, not social/news, so it was dropped
  rather than kept as partial coverage).
- **Sentiment engine:** VADER (`vaderSentiment` package), not TextBlob or
  an LLM-based classifier. Thresholds: compound ≥ 0.05 → bullish, ≤ -0.05 →
  bearish, else neutral (VADER's own convention). A small custom lexicon
  patch exists for finance slang (crush/beat/miss/bullish/bearish/moon/
  rally/selloff/downgrade/upgrade) - deliberately does NOT touch ambiguous
  terms like "dip."
- **Signal rule** (`storage/queries.py::get_signal()`): BUY only if
  sentiment verdict is BULLISH and price (over the same lookback window)
  is UP or FLAT; SELL only if BEARISH and price is DOWN or FLAT; HOLD for
  every other case, including disagreement or insufficient data. This is
  intentionally conservative - don't change it to force more BUY/SELL calls
  without an explicit request.
- **Accuracy grading horizons:** 4 hours and 24 hours, fixed
  (`EVALUATION_HORIZONS_HOURS` in `processing/signal_tracking.py`). HOLD is
  logged but never graded correct/incorrect.
- **Low-sample threshold:** `MIN_GRADED_FOR_CONFIDENCE = 20` graded calls
  in `storage/queries.py` - below this, the dashboard shows a caution
  rather than treating the accuracy percentage as reliable.
- **Hosting stack:** Neon (free Postgres) + Render (free web hosting,
  `gunicorn webapp.server:app`, deployed via `render.yaml` Blueprint).
  Chosen after Railway and Fly.io were found to have effectively no usable
  free tier as of when this was researched (2026-07-12).
- **Ingestion cadence:** fast group (prices, StockTwits, Reddit, Finnhub)
  every 5 minutes; slow group (FinViz, Google News) every 15 minutes.
  Controlled by `main.py --fast-only` / `--slow-only` and two separate
  Windows Task Scheduler jobs.

## User preferences

- Calvin wants concise, direct answers - minimal padding, no restating
  things he already knows.
- Calvin is comfortable running terminal/PowerShell commands himself but
  wants them handed to him exact and copy-pasteable, not described
  abstractly.
- Calvin appreciates a brief "why" alongside technical decisions, but not a
  full essay - one to a few sentences.
- Calvin has asked for a genuine logic/quality audit of this project once
  already (2026-07-12) rather than just trusting prior claims of
  correctness - a sign he values verification over reassurance. Don't
  over-claim confidence in untested logic.

## Known recurring gotchas (worth remembering, not re-discovering)

- **Python string `.format()` and literal curly braces don't mix.** A code
  comment containing literal `{...}` inside a string that later gets
  `.format()`-called elsewhere in the same string will raise a `KeyError`.
  This broke `storage/db.py` once (a comment describing a JSON shape used
  curly braces) and broke both local ingestion and the Render deploy until
  fixed. Watch for this specifically in `storage/db.py`'s `_SIGNAL_TRACKING_TABLES`
  template string.
- **Windows Task Scheduler always briefly flashes a console window** for
  any action that's `python.exe` directly - not fixable via a Task
  Scheduler setting. The workaround used here is a generated VBScript
  (`run_hidden.vbs`) launched via `wscript.exe` with window style 0.
- **`Register-ScheduledTask -Force` can fail with "Access is denied"**
  unless PowerShell is running as Administrator, even if the original
  (non-Force) registration didn't require it.
- **A scheduled task that's actively running can't have its definition
  replaced** - `Stop-ScheduledTask` before re-registering avoids a
  "Cannot create a file when that file already exists" error.
- **`source_breakdown` (per-source attribution) only populates on a Signal
  CHANGE**, not retroactively - old signal_log rows and tickers whose
  Signal hasn't flipped since the feature was added will show no source
  data. This is expected, not a bug, if it comes up again.

## Uncertain / needs re-verification **[unverified/may be stale]**

- Whether the old single-task Task Scheduler job
  (`FinancialSentimentDashboard-Ingestion`) still exists on Calvin's
  machine - he was told to remove it manually but this was never
  confirmed.
- Whether Reddit API access has been approved yet - as of the last known
  state, Reddit ingestion was still gated behind a pending manual approval
  request and skipped cleanly each cycle.
- Exact current Neon/Render free-tier terms - these were researched and
  confirmed as of 2026-07-12; free-tier terms are exactly the kind of
  thing that changes without much notice, so re-verify before relying on
  specifics (0.5GB Neon storage, 15-minute Render sleep, etc.) if much time
  has passed since this document was written.
