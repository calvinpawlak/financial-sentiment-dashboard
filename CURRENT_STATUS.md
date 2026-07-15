# Current Status

Written 2026-07-12, at the point of migrating this project from Claude
(Cowork) to ChatGPT Desktop/Codex. Read this after `README.md`,
`PROJECT_CONTEXT.md`, `MEMORY.md`, and `DECISIONS.md`.

## What's completed

- **Post-audit data-integrity fixes (2026-07-15):** multi-ticker posts and
  articles now preserve every ticker association; overlapping scheduled
  cycles serialize Signal-change logging; and 4h/24h grading uses the first
  stored price at or after the exact horizon rather than a delayed latest
  snapshot. SQLite and Postgres migrate in place without deleting existing
  rows.

- **New sources (2026-07-15):** Bluesky authenticated ticker search is live
  for all 9 tickers. Federal Reserve official RSS is live. SEC EDGAR support
  is implemented but awaits the required fair-access contact identifier.
  Official events use `raw_events` and are excluded from sentiment scoring.

- **Codex recovery validation (2026-07-15):** Python 3.12 virtual
  environment installed, direct dependencies pinned, `.env` loading
  centralized for every entry point, local SQLite backed up and migrated,
  persistent offline tests added, and Task Scheduler changed to use the
  project `.venv`. CLI, SQLite/Neon Flask APIs, scheduled ingestion, and
  the public Render endpoints were verified.

- **Layer 1 (ingestion):** yfinance (prices), StockTwits, Reddit (PRAW,
  pending approval), FinViz (news scrape), Finnhub (company news), Google
  News (RSS) - all working except Reddit, which degrades cleanly while
  waiting on API approval.
- **Layer 2 (processing):** VADER sentiment scoring with a custom
  finance-slang lexicon patch.
- **Layer 3 (storage):** hardened SQLite (indexes, WAL mode, shared query
  layer, opt-in `prune.py`), plus a Postgres backend (via `DATABASE_URL`)
  for the hosted deployment.
- **Layer 4 (dashboard):** custom Flask app (primary), Streamlit app
  (fallback).
- **BUY/SELL/HOLD Signal** feature with a conservative HOLD-on-disagreement
  rule and a persistent not-financial-advice disclaimer.
- **Prediction accuracy log:** log-on-Signal-change, graded at 4h/24h,
  HOLD never graded, plus (added during the logic audit) baseline
  comparison, Wilson confidence intervals, a low-sample warning, a
  BUY/SELL split, and per-source attribution.
- **Split ingestion cadence:** 5-minute fast group, 15-minute slow group,
  via two separate Windows Task Scheduler jobs.
- **Public hosting:** Neon (Postgres) + Render (Flask app), confirmed live
  by Calvin from a screenshot of the deployed page.
- **Logic audit:** found and fixed a real price/sentiment window-mismatch
  bug; added the statistical rigor items above.
- **Task Scheduler hidden-window fix:** ingestion runs via a generated
  `run_hidden.vbs` + `wscript.exe` so no console window flashes; the
  registration script itself was hardened (stop-before-replace,
  try/catch, conditional success message) after two real registration
  failures during setup.
- **This migration document set:** `README.md` updates,
  `PROJECT_CONTEXT.md`, `AGENTS.md`, `MEMORY.md`,
  `DECISIONS.md`, this file, `WORKFLOWS.md`, `CONNECTORS.md`, `TASKS.md`,
  `CONVERSATION_SUMMARIES/01` through `05`. (`AGENTS.md` was originally
  written as `CHATGPT_PROJECT_INSTRUCTIONS.md`, meant to be pasted into a
  ChatGPT "Project Instructions" field; once it was confirmed Codex
  instead auto-loads an `AGENTS.md` file from the project root, the
  content was moved there and the old file replaced with a short
  redirect.)

## In progress / not yet done

- Not enough real signal history has accumulated yet to actually use the
  new baseline/CI/BUY-SELL-split machinery to decide whether any source or
  threshold needs revising - that was the whole point of the logic audit,
  but it requires time passing, not more code.
- Source-specific grading horizons (different natural prediction windows
  for fast chatter vs. slower news) were researched and explicitly
  deferred pending more history.

## Current blockers

- **SEC EDGAR identification resolved (2026-07-15):** `SEC_USER_AGENT` is
  configured locally and a complete slow cycle stored 58 filing events.

- **Reddit API access** - gated behind Reddit's "Responsible Builder
  Policy" manual approval; status as of this writing is still pending, no
  fixed timeline. Not a blocker to the rest of the pipeline, which runs
  fine without it.
- **StockTwits API access** - the legacy unauthenticated symbol endpoint
  began returning HTTP 403 on 2026-07-15. StockTwits' official developer
  page says new API registrations are paused. The pipeline now stops after
  the first denial each cycle and continues with prices/news; do not replace
  it with scraping, which StockTwits' current terms prohibit without
  authorization.
- **Bluesky replacement:** implementation completed 2026-07-15 and covered
  by offline authentication/search-shape tests. Live activation is complete;
  an observed fast cycle fetched 260 posts on 2026-07-15.

## Unresolved questions

- Whether the Render deploy is currently green on the latest commit should
  still be checked fresh rather than assumed. Git itself was verified clean
  and synchronized with `origin/main` on 2026-07-15.
- Whether Calvin still wants the old Streamlit dashboard kept around at
  all, now that the Flask app has been the primary interface for a while.

## Recommended next steps

1. Confirm Render shows "Live" on the current commit (see `TASKS.md` "Now").
2. Let real signal history accumulate, then run Workflow 8 in
   `WORKFLOWS.md` (review the accuracy log) for real.
3. Re-check Reddit approval status periodically.

---

## Migration Risks and Missing Information

Things that may not transfer cleanly from Claude/Cowork to ChatGPT/Codex,
or that depend on facts only confirmable in the new environment.

**Execution model was verified in Codex Desktop on 2026-07-15.**
Codex can read/edit files, run local PowerShell/Python/git, and reach the
network in this workspace. It cannot elevate its own Windows permissions;
Calvin must run Task Scheduler registration from Administrator PowerShell.
Commits, pushes, deploys, destructive operations, and credential changes
still require explicit user authorization.

**The GitHub MCP server confusion may resurface in a different form.**
During this project, Calvin briefly believed that adding a local GitHub
MCP server would let the assistant run commands on his PC - it wouldn't
have, even if configured correctly, because MCP servers (when they work)
grant API-level access to a specific service, not local shell execution.
If ChatGPT/Codex has its own equivalent of connectors/plugins/tools, the
same distinction applies: a "GitHub connected" state does not imply "can
run git/PowerShell on this machine," and a "can run code" state doesn't
automatically mean it can reach GitHub, Render, or Neon without separate
credentials. Confirm each capability independently rather than assuming
one implies the other.

**Sandbox/tooling quirks specific to Claude/Cowork are not documented here
because they're expected to be irrelevant - but that's an assumption.**
Claude's Cowork environment ran code in an isolated Linux sandbox with the
project folder mounted in, and occasionally showed a heavily-edited file
as if it had a stale/cached syntax error until re-read directly (a sandbox
artifact, not a real bug - see `AGENTS.md`'s "verify, don't assume" rule,
which was written partly because of this).
Nothing in this document set assumes ChatGPT/Codex has an analogous
quirk, but if something looks broken that the edit history says shouldn't
be, re-reading the actual current file before reporting an error is good
practice regardless of platform.

**Credential and secret handling was never actually done by the
assistant.** All API keys and connection strings live in `.env` (local)
and Render's Environment tab (hosted) - the assistant never saw or
handled real secret values at any point in this project's history, by
design. Whatever the new environment's file access looks like, this
project's `.gitignore` already excludes `.env` and the local database/log
files; this exclusion should be re-verified as still in effect after
migration, not assumed to have transferred.

**Task Scheduler and other Windows-specific automation remain local to
Calvin's machine.** Codex Desktop can inspect the live task definitions and
run-state from this workspace, as verified on 2026-07-15, but cannot elevate
its own permissions. Replacing task definitions may still require Calvin to
run the setup script from an Administrator PowerShell.

**Free-tier terms (Neon, Render, Finnhub, Reddit's approval policy) are
time-sensitive facts, not stable architecture.** These were all researched
as of 2026-07-12 and are flagged **[unverified/may be stale]** in
`MEMORY.md`. A new assistant picking this project up - on any platform -
should re-verify current terms before making a recommendation that
depends on them, rather than trusting this snapshot indefinitely.

**A formal offline smoke suite now exists.** Run
`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`. It uses a
temporary SQLite database and covers schema migration, Signal behavior,
dual-horizon grading, and Flask read endpoints without network or Neon
writes. Historical test claims before 2026-07-15 still refer to discarded
ad hoc fixtures.
