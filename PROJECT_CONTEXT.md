# Project Context

Background an assistant needs to work effectively on this project, beyond
what's in the code and README. Written 2026-07-12 as part of migrating this
project from Claude (Cowork) to ChatGPT/Codex.

## Who this is for

- **Owner / sole user / sole developer: Calvin** (calvinplax@icloud.com).
  This is a personal project — one person, no team, no external
  stakeholders, no clients. Calvin makes all product and technical
  decisions himself, usually by describing what he wants in plain language
  and having the assistant implement it.
- No one else consumes this dashboard. There is no "customer" persona to
  design for beyond Calvin's own preferences (concise communication, wants
  to understand *why* something works the way it does, comfortable running
  terminal commands himself when asked).

## What the project actually is

A four-layer local-first Python application:

1. **Ingestion** — pulls live stock prices and public sentiment-bearing
   text (social posts, news headlines) for a fixed 9-ticker watchlist.
2. **Processing** — scores that text with VADER sentiment analysis into
   bullish/bearish/neutral.
3. **Storage** — SQLite locally (default) or Postgres (via `DATABASE_URL`,
   used when hosted).
4. **Presentation** — a Flask web dashboard (primary) and a Streamlit
   dashboard (fallback), both reading the same data layer.

On top of those four layers sit two further features: a BUY/SELL/HOLD
**Signal** (a mechanical rule combining sentiment + price direction) and a
**prediction accuracy log** that tracks whether each Signal call was
actually right, so the tool can be evaluated rather than just trusted.

## Terminology (project-specific meanings)

- **"Layer 1/2/3/4"** — refers to the four-stage architecture above
  (ingestion / processing / storage / dashboard), a naming convention
  established at project kickoff and used throughout commit messages,
  README sections, and prior conversation history. Not a generic industry
  term — specific to how this project's build was staged.
- **"Signal"** — capitalized in docs/UI to distinguish the project's own
  BUY/SELL/HOLD output from generic "trading signal" jargon. Computed by
  `storage/queries.py`'s `get_signal()`.
- **"Verdict"** — the sentiment-only lean (BULLISH / BEARISH /
  MIXED-NEUTRAL / NO DATA), one of the two inputs to a Signal. Do not
  confuse Verdict (sentiment-only) with Signal (sentiment + price
  combined) — this distinction matters and is used precisely in the code
  and docs.
- **"Fast" vs "slow" sources** — ingestion sources are split into a 5-minute
  group (prices, StockTwits, Reddit, Finnhub) and a 15-minute group (FinViz,
  Google News), based on which sources can tolerate high-frequency polling
  without ToS/reliability risk. See `main.py --fast-only` / `--slow-only`.
- **"Graded" / "pending" / "HOLD (no call)"** — accuracy-log vocabulary.
  A signal is "graded" once enough time has passed to check the outcome;
  "pending" if not yet; HOLD signals are logged but deliberately never
  graded correct/incorrect since they aren't a directional bet.
- **"Baseline"** (accuracy log) — the fraction of ALL graded price windows
  where price simply rose, used to sanity-check whether the Signal beats
  random drift rather than just riding a rising market.

## Systems and services involved

- **GitHub Actions** — runs ingestion against Neon on a free staggered
  schedule (fast every 15 minutes, slow every 6 hours), so Calvin's PC can
  be off. The Windows tasks are retained only as a fallback while the cloud
  schedule is proven.
- **Neon** — free-tier hosted Postgres, used only when `DATABASE_URL` is
  set. Exists solely so the public Render-hosted dashboard has a database
  reachable from outside Calvin's PC.
- **Render** — free-tier hosting for the Flask dashboard (`webapp/server.py`
  via `gunicorn`), deployed from GitHub via a Blueprint (`render.yaml`).
  Sleeps after 15 minutes of no traffic (free tier).
- **GitHub** — `calvinpawlak/financial-sentiment-dashboard`, the single
  source of truth Render deploys from. Local git repo pushes here.
- **Reddit, StockTwits, FinViz, Finnhub, Google News** — the five upstream
  data sources. See `CONNECTORS.md` for details on each.

## Constraints

- **Free-tier only, by explicit decision.** No paid X/Twitter API, no
  Instagram, no paid Finnhub tier (the paid social-sentiment endpoint is
  known to exist but isn't used). This constraint came from Calvin
  directly and should not be silently violated by suggesting paid upgrades
  as the default fix to a data-quality problem — free-tier alternatives or
  workarounds should be tried first, or the tradeoff should be surfaced
  explicitly for Calvin to decide.
- **Small sample size, always.** 9 tickers, signals logged only on change.
  Any statistical claim about the Signal's accuracy needs to account for
  small-n effects (confidence intervals, low-sample warnings) rather than
  presenting a bare percentage as if it were reliable.
- **No paid infrastructure.** Neon and Render free tiers specifically
  (not just "cheap") — chosen after researching current 2026 free-tier
  terms, since several competitors (Railway, Fly.io) had quietly dropped or
  gutted their free tiers by the time this was built.
- **Ingestion is inherently tied to Calvin's own PC being on.** This is a
  known, accepted limitation, not a bug to silently "fix" by assuming
  cloud ingestion — moving ingestion to the cloud is a real, larger future
  project explicitly deferred, not something to casually bolt on.
- **This is not financial advice, and must keep saying so.** Every surface
  that shows a Signal or an accuracy percentage carries a disclaimer.
  Don't remove or soften this when redesigning the UI.

## Assumptions worth knowing about

- Calvin is comfortable with a technical, terminal-based workflow (running
  `pip install`, PowerShell scripts, `git` commands) but prefers the
  assistant to hand him copy-pasteable commands rather than assuming he'll
  figure out equivalents himself.
- The project assumes a single ingesting machine (no concurrency/locking
  design beyond SQLite's WAL mode) — it was never designed for multiple
  people or multiple machines writing to the same database simultaneously.
- Tickers are currently fixed at 9 (SPY, QQQ, MSFT, AAPL, GOOG, NVDA, NDAQ,
  VOO, SPCX) — adding more is possible (edit `config/settings.py`) but
  hasn't been asked for yet.

## Relevant history (see `DECISIONS.md` and `CONVERSATION_SUMMARIES/` for full detail)

Built in one continuous, multi-session effort starting 2026-07-12: layers
1-4 built and hardened, then extended with additional data sources
(Finnhub, Google News), a full UI rebuild from Streamlit to a custom Flask
app matching a visual mockup Calvin shared, a BUY/SELL/HOLD signal feature,
a prediction accuracy log, a 5/15-minute split ingestion cadence, public
hosting (Neon + Render), and finally a logic audit that fixed a real bug
(price/sentiment window mismatch) and added statistical rigor (baseline
comparison, confidence intervals, per-source attribution) to the accuracy
log. All of this happened under Claude in Cowork mode; this document set is
being created specifically to carry that context into ChatGPT/Codex.
