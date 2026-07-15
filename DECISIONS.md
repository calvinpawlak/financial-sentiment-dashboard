# Decisions Log

Every significant decision made on this project, in roughly chronological
order. All dates are 2026-07-12 because the entire project (to date) was
built in one continuous multi-session effort on that day. "Permanent"
means revisiting it would require a real reason, not just preference drift;
"Revisitable" means it was a reasonable-for-now call that could change
without much friction.

---

**Decision: Free-tier data sources only - no paid X/Twitter API, no Instagram.**
- Rationale: keep the project genuinely free to run indefinitely; Instagram
  has no practical public API for post/comment sentiment at any price, and
  X's API only gives useful volume on a paid tier.
- Rejected alternatives: paid X API tier; Instagram scraping (no viable API).
- Status: **Permanent** unless Calvin explicitly decides he wants to pay for
  broader coverage.

**Decision: Ticker universe is SPY, QQQ, MSFT, AAPL, GOOG, NVDA, NDAQ, VOO, SPCX (9 fixed tickers).**
- Rationale: initial watchlist, refined after discovering INX doesn't
  resolve on any data source ("possibly delisted" per Yahoo) and ^GSPC
  (the real index symbol) only gets price coverage, not social/news
  coverage from StockTwits/FinViz - so both were dropped rather than kept
  as partial-coverage entries. SPCX was initially miscategorized as
  possibly-invalid but confirmed to be a real, newly-IPO'd ticker
  (Space Exploration Technologies Corp / SpaceX, IPO'd 2026-06-12).
- Rejected alternatives: keeping INX/^GSPC as partial-coverage (price-only)
  entries.
- Status: **Revisitable** - adding more tickers is a config change
  (`config/settings.py`), not an architecture change.

**Decision: VADER (not TextBlob, not an LLM) for sentiment scoring, with a small custom finance-slang lexicon patch.**
- Rationale: VADER is tuned for short, informal social-media-style text
  (slang, emphasis, punctuation), matching Reddit/StockTwits content well;
  one reference open-source project used it successfully. A custom lexicon
  patch was added after testing revealed VADER misreads unambiguous finance
  terms (e.g. "crushes" read as violent, not "beat big").
- Rejected alternatives: TextBlob (used by one reference project, but
  weaker on slang); ambiguous slang like "dip" was deliberately left
  unpatched (context-dependent, guessing wrong would be worse than VADER's
  default).
- Status: **Permanent** for the core engine choice; the lexicon patch list
  is revisitable/extensible as new misreads are found.

**Decision: SQLite as the primary local database, with Postgres added later as an alternate backend (not a replacement).**
- Rationale: SQLite is sufficient at this data volume/scale and needs zero
  setup; Postgres was added later specifically to support public hosting
  (a file on a hosted server's disk isn't reliably persistent or reachable
  from Calvin's local machine).
- Rejected alternatives: migrating fully to Postgres and dropping SQLite
  support; a dedicated ORM (kept to raw SQL + a thin dual-dialect adapter
  instead, `storage/db.py`'s `_PGConnAdapter`).
- Status: **Permanent** for local use (SQLite); Postgres/Neon is
  **Permanent** for the hosted deployment specifically.

**Decision: `prune.py` (data retention) is opt-in only, never runs automatically from `main.py`.**
- Rationale: nothing should ever be silently deleted from the working
  database without an explicit, separate action.
- Rejected alternatives: automatic retention enforcement inside the normal
  ingestion cycle.
- Status: **Permanent.**

**Decision: Custom Flask web app as the primary dashboard, replacing an initial Streamlit dashboard (kept as a fallback).**
- Rationale: Calvin shared a specific visual mockup (dark fintech theme,
  card-grid KPIs, gradient chart, sparkline table) that Streamlit's layout
  engine couldn't replicate. Offered three options (reskinned Streamlit,
  regenerated static HTML, local Flask/FastAPI app); Calvin picked Flask.
- Rejected alternatives: reskinning Streamlit; a static-HTML-file
  regenerated each ingestion cycle with no server process.
- Status: **Permanent** for Flask-as-primary; Streamlit fallback kept
  because it was cheap to leave in place, not because it's expected to be
  used regularly.

**Decision: BUY/SELL/HOLD Signal is a conservative rule - HOLD unless sentiment verdict and price direction agree.**
- Rationale: two independently weak, noisy signals combined; forcing a
  confident call when they disagree would be least justified exactly when
  disagreement happens.
- Rejected alternatives: a more decisive rule that picks a side on
  disagreement; using sentiment alone without the price-direction check.
- Status: **Permanent** design philosophy - the exact thresholds
  (percentage-point gap in `verdict_for()`, VADER's ±0.05) are
  **Revisitable** once enough graded history exists to tune them
  empirically rather than by guesswork.

**Decision: Added Finnhub and Google News as additional layer-1 sources; rejected Alpha Vantage and NewsAPI.org.**
- Rationale: wanted broader news coverage and a Reddit/Twitter-adjacent
  signal without needing Reddit's own gated API. Alpha Vantage's free tier
  (25 req/day) would exhaust in under an hour against 9 tickers on a
  15-minute cycle; NewsAPI.org's free tier is explicitly localhost/dev-only,
  blocked in any real running app.
- Rejected alternatives: Alpha Vantage News Sentiment; NewsAPI.org.
- Status: **Permanent** for Finnhub/Google News as sources; the decision
  NOT to upgrade to Finnhub's paid social-sentiment tier is **Revisitable**
  if Calvin decides the aggregated Reddit/Twitter signal is worth paying
  for later.

**Decision: Prediction accuracy log logs on signal CHANGE only (not every cycle), grades at two fixed horizons (4h and 24h), and never scores HOLD as correct/incorrect.**
- Rationale: logging every 5-minute cycle would produce thousands of
  near-duplicate "still HOLD" rows/day once the fast cadence was running,
  drowning out real signal changes. Two horizons (rather than one) were
  chosen via an explicit multiple-choice question to Calvin. HOLD isn't a
  directional bet, so grading it correct/incorrect would overstate the
  tool's rigor.
- Rejected alternatives: logging every cycle; a single grading horizon;
  scoring HOLD as correct when price stayed flat.
- Status: **Permanent** for log-on-change and not-grading-HOLD; the
  specific horizons (4h/24h) are **Revisitable** with evidence from
  accumulated history.

**Decision: Split ingestion cadence - fast sources every 5 minutes, slow/scraped sources every 15 minutes - rather than 5 minutes for everything.**
- Rationale: Calvin initially asked for 5-minute scanning across the
  board, but FinViz (own ~30 min update cadence, ToS discourages
  high-frequency scraping) and Google News RSS (unofficial, no documented
  rate limit) don't benefit from faster polling and carry more risk at
  higher frequency. Presented as a multiple-choice tradeoff; Calvin chose
  the split.
- Rejected alternatives: uniform 5-minute polling for all sources.
- Status: **Permanent** unless FinViz/Google News's own update behavior
  changes materially.

**Decision: Public hosting via Render (web app) + Neon (Postgres) - rejected Railway, Fly.io, and Render's own Postgres.**
- Rationale: researched current (2026) free-tier terms rather than
  assuming older reputations still held. Railway's free tier had become a
  ~$1/month credit (not enough for continuous use); Fly.io had no free
  tier since 2024; Render's own free Postgres expires after 30 days, so
  Neon (no such expiry, scale-to-zero instead) was used for the database.
- Rejected alternatives: Railway, Fly.io, Render's built-in Postgres,
  Supabase (pauses entirely after 7 days of inactivity, needs manual
  unpause).
- Status: **Revisitable** - explicitly contingent on current free-tier
  terms, which are known to change without much notice. Re-verify before
  assuming these terms still hold if much time has passed.

**Decision: Ingestion stays local (Calvin's PC + Task Scheduler); only the dashboard itself is hosted publicly.**
- Rationale: matches what was actually asked for (a public dashboard) and
  avoids the added complexity/cost of cloud-based ingestion at this stage.
- Rejected alternatives: moving ingestion to a cloud scheduled job too.
- Status: **Revisitable** - explicitly flagged as a reasonable future
  project, not ruled out.

**Decision update 2026-07-15: Move ingestion to free GitHub Actions.**
- Rationale: Calvin requires updates while his PC is off and does not want
  any paid service. Actions works with the public repository and Neon.
- Schedule: fast sources every 15 minutes at staggered minutes; slow sources
  every 6 hours. One concurrency group serializes all writers, and manual
  fast/slow/full recovery runs are supported.
- Tradeoff accepted: scheduled runs can be delayed, and public-repository
  schedules can be disabled after 60 days without repository activity.
- Status: **Current.** Keep local Windows tasks as a fallback until
  successful cloud runs are observed.

**Decision: Task Scheduler console-window flash fixed via a generated VBScript launcher (`run_hidden.vbs` + `wscript.exe`), not `pythonw.exe` or "run whether logged on or not."**
- Rationale: `pythonw.exe` can crash logging that writes to `sys.stdout`
  (which becomes `None`-like without a console); "run whether logged on or
  not" requires storing Calvin's Windows password in Task Scheduler, an
  unnecessary credential-storage tradeoff for a cosmetic fix.
- Rejected alternatives: `pythonw.exe`; storing credentials for a
  non-interactive scheduled run.
- Status: **Permanent** unless a cleaner OS-level fix becomes available.

**Decision: Logic audit (2026-07-12, at Calvin's request) - fixed the price/sentiment window mismatch; added baseline comparison, Wilson confidence intervals, and BUY/SELL split to the accuracy log; added per-source attribution logging.**
- Rationale: Calvin asked for a genuine review of whether the tool's logic
  was sound and whether data sources needed revising - review surfaced one
  real bug (price direction always used a fixed day-change regardless of
  the selected sentiment window) and several statistical presentation gaps
  (no baseline/CI, no per-source breakdown) that risked misleading
  conclusions once real accuracy history accumulated.
- Rejected alternatives: leaving the accuracy percentage as a bare number;
  building full per-source-specific grading horizons immediately (deferred
  as future work pending more history - flat 4h/24h horizons are used for
  all sources for now, even though research suggests different platforms
  may have different natural prediction horizons).
- Status: **Permanent** for the bug fix and the statistical additions;
  source-specific grading horizons remain an open, deferred idea (see
  `CURRENT_STATUS.md`).

**Decision: Preserve multi-ticker source associations and make accuracy tracking concurrency/time safe (2026-07-15).**
- Rationale: a live audit confirmed that globally unique post/article IDs
  discarded secondary ticker associations, overlapping fast/slow cycles
  produced duplicate Signal changes, and delayed grading could use a price
  much later than the intended horizon.
- Implementation: social identity is `(source, external_id, ticker)`, news
  identity is `(link, ticker)`, Signal check-and-insert is serialized by the
  active database, and grading selects the first stored price at or after the
  exact 4h/24h target.
- Status: **Permanent** data-integrity behavior. Existing rows are preserved;
  future cycles can restore secondary ticker associations as sources refetch
  overlapping data.

**Decision: Migrate the project from Claude (Cowork) to ChatGPT/Codex (2026-07-12).**
- Rationale: Calvin's own choice; specific motivation not stated in the
  handoff request beyond wanting to continue development there.
- Rejected alternatives: n/a - user-directed platform change.
- Status: this document set exists specifically to make this decision
  land cleanly; see `CURRENT_STATUS.md`'s "Migration Risks and Missing
  Information" section for what may not transfer automatically.

**Decision: Standardize local and hosted execution on Python 3.12 with a project virtual environment (2026-07-15).**
- Rationale: Render already targeted Python 3.12 while the local scheduled
  jobs used an unpinned global Python 3.14 installation. A repo-local
  `.venv`, exact direct dependency pins, centralized `.env` loading, and a
  persistent offline test suite make local, scheduled, and hosted behavior
  substantially more reproducible.
- Rejected alternatives: continuing to use the Microsoft Store Python shim
  and globally installed packages; relying only on discarded ad hoc test
  scripts.
- Status: **Permanent** unless the supported Render Python version is
  deliberately upgraded and validated through the offline suite.
