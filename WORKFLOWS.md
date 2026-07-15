# Workflows

Recurring processes for this project. Written 2026-07-12.

---

## 1. Run one ingestion cycle manually

**Trigger:** Testing a change, or Calvin wants fresh data right now without
waiting for the scheduled task.
**Inputs:** A working `.env` (or none, if only using free/no-key sources).
**Steps:**
1. `cd` into `financial-sentiment-dashboard/`.
2. `python main.py` (full cycle - all sources) or `python main.py --fast-only`
   / `--slow-only` (partial, matches the scheduled split).
3. Watch console output or `logs/ingestion.log` for a per-source fetch
   count and any warnings (skipped Reddit/Finnhub, etc.).
**Output:** New rows in `raw_prices`/`raw_social`/`raw_news`/
`scored_sentiment`, possibly a new `signal_log` row if any ticker's Signal
changed, possibly new `signal_evaluations` rows if any pending signal
crossed a grading horizon.
**Quality check:** No unhandled exceptions; source counts are non-zero for
at least prices/StockTwits (the two sources with no auth gate).
**Completion criteria:** Process exits with status 0.

## 2. Continuous ingestion (the normal steady state)

**Trigger:** Once set up, this runs forever without action needed.
**Inputs:** Windows Task Scheduler jobs registered via `setup_task_scheduler.ps1`.
**Steps:** Task Scheduler fires `wscript.exe run_hidden.vbs ... python main.py --fast-only`
every 5 minutes and the `--slow-only` equivalent every 15 minutes,
automatically, hidden (no visible window).
**Output:** A continuously growing local SQLite file (or Neon Postgres, if
`DATABASE_URL` is set locally).
**Quality check:** Periodically tail `logs/ingestion.log` to confirm cycles
are still succeeding; check `Get-ScheduledTask ... | Get-ScheduledTaskInfo`
for last run time/result.
**Completion criteria:** N/A - this is meant to run indefinitely while
Calvin's PC is on.

## 3. Re-registering / changing the scheduled tasks

**Trigger:** First-time setup, changing the interval, moving the project
folder, or picking up a script update (like the hidden-window fix).
**Inputs:** PowerShell, ideally run as Administrator (required for
`-Force` re-registration of an existing task).
**Steps:**
1. `cd` into the project folder.
2. `powershell -ExecutionPolicy Bypass -File .\setup_task_scheduler.ps1`
3. If it reports "Access is denied," re-run PowerShell as Administrator
   and repeat step 2.
**Output:** Two Task Scheduler jobs (Fast/Slow), plus a regenerated
`run_hidden.vbs`.
**Quality check:** Script prints "Registered '<name>'" for both tasks, not
"FAILED."
**Completion criteria:** Both tasks show as registered and enabled in Task
Scheduler.

## 4. View current sentiment/signal state without the web dashboard

**Trigger:** Quick check without opening a browser.
**Steps:** `python report.py` (last 24h) or `python report.py --hours 6`
(custom window).
**Output:** A per-ticker bullish/bearish/neutral count printed to the
console with a rough verdict.
**Completion criteria:** N/A, informational only.

## 5. Run the local web dashboard

**Trigger:** Want the full visual dashboard on `localhost` instead of (or
in addition to) the public Render URL.
**Steps:**
1. `python webapp/server.py`
2. Open `http://localhost:5000`.
3. Leave the terminal window running - closing it stops the server.
**Output:** Live dashboard reading the same database as ingestion.
**Completion criteria:** Page loads and shows current ticker data.

## 6. Make a code change and ship it

**Trigger:** Any bug fix, feature, or logic change.
**Steps:**
1. Read the relevant file(s) fully before editing - don't assume stale
   context from earlier in a conversation reflects current file content.
2. Make the change.
3. Run `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.
   Extend the persisted temporary-SQLite fixtures when behavior changes;
   do not use live network calls or Neon for logic regression testing.
4. Update `README.md` (and `MEMORY.md`/`DECISIONS.md` if the change is a
   new durable fact or decision) in the same pass.
5. Hand Calvin the exact commands to run locally: `git add .`, `git commit
   -m "..."`, `git push`.
6. If the change touches anything under `webapp/`, `storage/`, or any
   other file Render's deploy depends on, remind Calvin to check Render's
   Events/Deploys tab for a successful redeploy after the push.
7. If the change touches `storage/db.py`'s schema, remind Calvin to run
   `python main.py` once locally afterward so any new column/table
   migration is applied to whichever database is currently active
   (local SQLite or Neon, depending on whether `DATABASE_URL` is set).
**Quality check:** Offline tests pass; file syntax is valid; disclaimers
and conservative-signal behavior are unchanged unless the change was
specifically about that.
**Completion criteria:** Calvin confirms the pushed change deployed/ran
successfully (Render shows "Live," or the local script completed without
error).

## 7. Deploy config/schema changes to the hosted dashboard

**Trigger:** Any change affecting `webapp/`, `storage/`, `render.yaml`, or
`requirements.txt`.
**Steps:**
1. Commit and push to GitHub (`calvinpawlak/financial-sentiment-dashboard`).
2. Render auto-deploys from the connected branch (default: on, but check
   the Events/Deploys tab - if no deploy appears, use "Manual Deploy →
   Deploy latest commit").
3. If the change adds/alters a database column or table, run `python
   main.py` once locally (with `DATABASE_URL` pointed at Neon) so the
   migration in `init_db()` actually executes against the hosted database -
   Render's `webapp/server.py` does NOT call `init_db()` itself, so schema
   changes only apply via a local ingestion run.
**Quality check:** Render deploy log shows no traceback; opening the public
URL loads without errors.
**Completion criteria:** Public dashboard reflects the new code and schema.

## 8. Review the prediction accuracy log / decide if a data source needs revising

**Trigger:** Periodic check-in on whether the Signal is actually any good,
or investigating a specific bad call.
**Inputs:** Enough elapsed time for signals to have been graded (4h/24h
after they were logged).
**Steps:**
1. Open the dashboard's "Prediction Accuracy" panel.
2. Check `accuracy_pct` alongside its confidence interval and the
   `low_sample` flag - don't trust a bare percentage from a handful of
   graded calls.
3. Compare `accuracy_pct` to `baseline_up_pct` - if they're close, the
   Signal isn't beating simple market drift.
4. Check the BUY vs SELL split separately - a rule can be good at one and
   bad at the other.
5. Use the per-source tags in the signal log table to see which source(s)
   drove specific calls, once enough post-2026-07-12 history has
   accumulated (older rows won't have this).
**Output:** A judgment call about whether thresholds, sources, or the
Signal rule itself need revisiting - this is manual analysis, not an
automated recommendation.
**Completion criteria:** N/A - informational/analytical workflow.

## 9. Retention / cleanup (rarely needed)

**Trigger:** Database growing larger than desired.
**Steps:**
1. `python prune.py --days 90 --dry-run` (preview only).
2. If the preview looks right, `python prune.py --days 90` (actually
   deletes + reclaims disk space via `VACUUM`).
**Quality check:** Dry-run output reviewed before the real run.
**Completion criteria:** Database size reduced; `main.py` still runs
cleanly afterward.
