# Connectors, Integrations, and External Dependencies

Every external system this project touches. No secrets, tokens, or
passwords are included below by design - see each entry's ".env variable"
note for where the real value actually lives (never in this repo).
Written 2026-07-12.

---

## yfinance (price data)

- **Purpose:** live/delayed stock price quotes for the 9-ticker watchlist.
- **Type:** Python package (`yfinance`), unofficial Yahoo Finance wrapper -
  not a registered API/account, no key.
- **Permissions/auth:** none required.
- **Where used:** `ingestion/prices.py`.
- **Typical operation:** `t.history(period="5d", interval="1d")` per
  ticker, once per fast cycle (5 min).
- **How to test it works:** run `python main.py --fast-only` and check
  `logs/ingestion.log` for "Fetched N price quotes" with N close to 9; or
  run `python -c "import yfinance as yf; print(yf.Ticker('AAPL').history(period='5d'))"`
  directly.
- **Known fragility:** an earlier version had a bug where `fast_info`
  dict-style access returned no data for valid tickers (an upstream
  yfinance quirk) - fixed by switching to `.history()`. If prices stop
  resolving again, check yfinance's own GitHub issues first.

## StockTwits (social chatter - currently unavailable)

- **Purpose:** recent public posts mentioning each ticker.
- **Type:** free public HTTP endpoint, no account/key.
- **Permissions/auth:** the previously working unauthenticated legacy
  endpoint began returning HTTP 403 on 2026-07-15. StockTwits' official
  developer page currently says new API registrations are paused; approved
  API access is required for a durable integration.
- **Where used:** `ingestion/stocktwits.py`.
- **Typical operation:** one GET per ticker per fast cycle, capped at
  `STOCKTWITS_MESSAGE_LIMIT` messages (`config/settings.py`).
- **Current behavior:** the code stops after the first 403, logs one warning,
  and returns no StockTwits rows for that cycle. Prices and all news sources
  continue normally. Do not work around this by scraping the website.

## Bluesky (social chatter)

- **Purpose:** official-API replacement for StockTwits-style ticker chatter.
- **Type:** Bluesky/AT Protocol authenticated REST API.
- **Permissions/auth:** free Bluesky account plus `BLUESKY_HANDLE` and an
  app-specific `BLUESKY_APP_PASSWORD` in `.env`. Never use the primary
  account password.
- **Where used:** `ingestion/bluesky_source.py` and the Fast ingestion cycle.
- **Typical operation:** authenticate once per cycle, then search the latest
  public posts for each ticker cashtag; rows deduplicate by AT URI.
- **How to test it works:** run `.\.venv\Scripts\python.exe main.py
  --fast-only` and look for `Fetched N Bluesky posts`.
- **Graceful degradation:** missing credentials produce one warning and do
  not affect prices, Finnhub, or other sources.

## Reddit (PRAW)

- **Purpose:** posts mentioning the tickers from r/wallstreetbets,
  r/stocks, r/investing, r/StockMarket.
- **Type:** Reddit's official API via the `praw` Python package.
- **Permissions/auth:** requires a registered Reddit "script" app -
  `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` in `.env`. **As of this
  writing, Reddit gates all new API access behind a manual "Responsible
  Builder Policy" approval** - the old instant self-serve flow is gone.
  Calvin filed a request; approval status as of the last known state was
  still pending (see `MEMORY.md`'s uncertain-items list).
- **Where used:** `ingestion/reddit_source.py`.
- **Typical operation:** scans `SUBREDDITS` (config) for the last
  `REDDIT_POST_LIMIT` posts per subreddit, filters for ticker mentions.
- **How to test it works:** with real credentials in `.env`, run
  `python main.py --fast-only` and look for "Fetched N matching Reddit
  posts." Without credentials (or with the placeholder values still in
  `.env`), it should log a clear warning and skip cleanly - that's expected
  behavior, not a failure.
- **Graceful degradation:** the whole pipeline runs fine without this;
  StockTwits/FinViz/Finnhub/Google News are unaffected.

## FinViz (news scrape)

- **Purpose:** per-ticker news headlines.
- **Type:** HTML scrape via `requests` + `BeautifulSoup` (no official API).
- **Permissions/auth:** none, but FinViz's terms discourage
  high-frequency/commercial automated scraping - this is why it's in the
  slow (15-minute) ingestion group, roughly matching FinViz's own ~30-min
  update cadence.
- **Where used:** `ingestion/news.py`.
- **Typical operation:** parses the `table#news-table` element per ticker.
- **How to test it works:** run `python main.py --slow-only`; check for
  "Fetched N FinViz news headlines." If it returns 0 for everything,
  FinViz likely changed their page structure - this is the single most
  fragile part of the pipeline.

## Finnhub

- **Purpose:** (1) company news headlines (working, free), (2) aggregated
  Reddit/Twitter mention+sentiment rollup (confirmed **paid-only** as of
  2026-07-12, not used).
- **Type:** REST API, free-tier signup key.
- **Permissions/auth:** `FINNHUB_API_KEY` in `.env` (free tier, ~60
  calls/min as of when this was set up). Sign up at finnhub.io/register.
- **Where used:** `ingestion/finnhub_source.py`.
- **Typical operation:** `/company-news` per ticker per fast cycle (2-day
  lookback window, `FINNHUB_NEWS_DAYS_BACK`); `/stock/social-sentiment` is
  attempted once, hits a 403 on a free-tier key, and the code stops calling
  it for the rest of that cycle rather than repeating the failure per
  ticker.
- **How to test it works:** with a key in `.env`, run `python main.py
  --fast-only` and check for "Fetched N Finnhub news headlines" - a 403
  logged once for social-sentiment is expected/normal, not an error to
  chase.
- **Graceful degradation:** without a key (or with the placeholder value),
  Finnhub ingestion is skipped cleanly, same pattern as Reddit.

## Google News (unofficial RSS)

- **Purpose:** second, independent news headline source (so one source
  breaking doesn't take down news coverage entirely).
- **Type:** unofficial RSS feed (`news.google.com/rss/search`), no key.
- **Permissions/auth:** none.
- **Where used:** `ingestion/google_news_source.py`.
- **Typical operation:** one RSS fetch per ticker per slow cycle, capped
  at `GOOGLE_NEWS_HEADLINE_LIMIT`.
- **How to test it works:** run `python main.py --slow-only`; check for
  "Fetched N Google News headlines." If it ever returns nothing, manually
  check `https://news.google.com/rss/search?q=test` in a browser before
  assuming the code is broken.

## Neon (hosted Postgres)

- **Purpose:** the database the *hosted* Render dashboard reads from -
  needed because a public server can't read Calvin's local SQLite file.
- **Type:** managed Postgres, free tier (0.5GB storage, scale-to-zero after
  5 min idle).
- **Permissions/auth:** a `DATABASE_URL` Postgres connection string, set in
  two places: (1) Calvin's local `.env` (so local ingestion writes to Neon
  instead of local SQLite), and (2) Render's service Environment tab (so
  the hosted dashboard reads from the same database).
- **Where used:** `storage/db.py` (auto-detects `DATABASE_URL` and
  switches from SQLite to Postgres with no other code changes needed).
- **Important locations:** Neon web console → project → Tables view (to
  inspect data) or SQL Editor (to run ad hoc queries).
- **Typical operations:** none directly by the assistant - all writes
  happen through `main.py`/`storage/db.py`'s normal insert helpers.
- **How to test it works:** run `python main.py` locally with
  `DATABASE_URL` set, then check the Neon console's table view for new
  rows; or watch `logs/ingestion.log` for a clean run with no connection
  errors.

## Render (hosted dashboard)

- **Purpose:** public hosting for the Flask dashboard (`webapp/server.py`).
- **Type:** free-tier web service, deployed via a "Blueprint"
  (`render.yaml`) connected to the GitHub repo.
- **Permissions/auth:** Render account + GitHub connection (to pull the
  repo); `DATABASE_URL` set as an environment variable in Render's
  dashboard (Environment tab) - intentionally left blank in `render.yaml`
  since it's a secret.
- **Where used:** deploy target only - no code in this repo calls Render's
  API directly.
- **Important locations:** Render dashboard → service →
  Events/Deploys tab (deploy status/logs), Environment tab
  (`DATABASE_URL`), public URL:
  `https://financial-sentiment-dashboard.onrender.com`.
- **Typical operations:** auto-deploys on every push to the connected
  GitHub branch (default), or manually via "Manual Deploy → Deploy latest
  commit."
- **How to test it works:** push a commit, check the Events/Deploys tab
  for a new deploy reaching "Live," then open the public URL and confirm
  it loads and shows current data.
- **Known limitation:** free tier sleeps after 15 minutes of no traffic;
  first request after that takes ~30-60 seconds to wake up.

## GitHub (`calvinpawlak/financial-sentiment-dashboard`)

- **Purpose:** single source of truth for the codebase; what Render
  deploys from.
- **Type:** standard git remote + GitHub repo.
- **Permissions/auth:** Calvin's own GitHub account, authenticated locally
  via whatever git credential flow his machine already uses (browser-based
  sign-in was observed working during initial push).
- **Where used:** local `git` commands only - no MCP/API-based GitHub
  integration is wired into this project's actual code or automation.
- **Important locations:** the repo itself; local `.git/` folder in
  `financial-sentiment-dashboard/`.
- **Typical operations:** `git add`, `git commit`, `git push` from
  Calvin's own terminal.
- **How to test it works:** `git push` succeeds, and the pushed commit
  appears on github.com under the repo's commit history.
- **Migration note:** a Claude-Desktop-level "local MCP server" for GitHub
  was attempted during this project but was never actually wired into
  Cowork sessions or used for pushes - all git operations throughout this
  project's history were done by Calvin directly in his own terminal. See
  `CURRENT_STATUS.md` for what to check in ChatGPT/Codex here.

## Windows Task Scheduler

This is retained as a local fallback. The active always-available scheduler
is the free GitHub Actions workflow described below.

- **Purpose:** runs `main.py` on a recurring schedule so ingestion doesn't
  require Calvin to remember to run it manually.
- **Type:** OS-level scheduler, not a cloud service.
- **Permissions/auth:** local Windows account permissions; registering/
  replacing tasks with `-Force` requires PowerShell running as
  Administrator (a real issue hit during this project - regular PowerShell
  got "Access is denied").
- **Where used:** configured by `setup_task_scheduler.ps1`, which also
  generates `run_hidden.vbs` (the hidden-window launcher wrapper).
- **Important locations:** Windows Task Scheduler GUI (search "Task
  Scheduler" in Start menu) → look for
  `FinancialSentimentDashboard-Ingestion-Fast` and `-Slow`.
- **Typical operations:** `Get-ScheduledTask -TaskName '...' |
  Get-ScheduledTaskInfo` (check status), `Start-ScheduledTask -TaskName
  '...'` (run now), `Unregister-ScheduledTask -TaskName '...'` (remove).
- **How to test it works:** check `Get-ScheduledTaskInfo`'s "LastTaskResult"
  is 0 (success) and "LastRunTime" is recent; confirm no console window
  flashes when it fires.

## GitHub Actions cloud ingestion

- **Purpose:** runs ingestion while Calvin's PC is off without adding a paid
  service.
- **Where configured:** `.github/workflows/cloud-ingestion.yml`.
- **Schedule:** fast mode every 15 minutes at minutes 7/22/37/52; slow mode
  every 6 hours at minute 13; manual fast/slow/full runs are also supported.
- **Required repository secrets:** `DATABASE_URL`, `FINNHUB_API_KEY`,
  `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`, and `SEC_USER_AGENT`. Reddit
  credentials are optional while approval is pending.
- **Safety:** read-only repository permissions and a shared concurrency group
  that prevents fast, slow, and manual cycles from writing simultaneously.
- **How to test it works:** run both modes manually in GitHub Actions, confirm
  green completion, then verify Neon rows and dashboard timestamps advance.

## DB Browser for SQLite (optional local tool)

- **Purpose:** GUI for inspecting the local `data/sentiment_dashboard.db`
  file directly, mentioned in the README as an option.
- **Type:** standalone desktop application (sqlitebrowser.org), not
  integrated into the codebase.
- **Permissions/auth:** none - just opens the local file.
- **How to test it works:** open the app, open `data/sentiment_dashboard.db`,
  browse tables.

---

## Bluesky, SEC EDGAR, and Federal Reserve (added 2026-07-15)

- **Bluesky:** official authenticated AT Protocol search. Requires
  `BLUESKY_HANDLE` and a Bluesky app password in `.env`; verified live and
  writing scored social rows for all tracked tickers.
- **SEC EDGAR:** official submissions JSON API. No API key or paid account,
  but SEC fair-access rules require `SEC_USER_AGENT` to identify this app and
  provide a contact email. Filings are stored in `raw_events`, not sentiment.
- **Federal Reserve:** official press-release, monetary-policy, and speech RSS
  feeds. No key or account. Macro events are stored in `raw_events` with a
  null ticker and are not sentiment-scored.

## Not currently connected (mentioned for completeness)

- **A brokerage-style MCP connector** (equity quotes, watchlists, order
  placement tools) was available in Calvin's broader Cowork environment
  during this project, but was explicitly **not** used for this project's
  automated pipeline - MCP tools only work inside interactive AI sessions,
  not from a plain scheduled Python script, and this project has never
  placed or intends to place real trades. If a similar connector exists in
  ChatGPT/Codex, the same boundary should hold: research/read-only use at
  most, never order placement.
