# Conversation Summary: Task Scheduler Fixes and Migration Prep

**Date:** 2026-07-12 (continuation of the same day's work)

## What happened

**Console-window-flash fix.** Calvin asked how to stop a command-prompt
window from opening and closing every time the scheduled ingestion ran.
Fixed by having `setup_task_scheduler.ps1` generate `run_hidden.vbs`, a
small VBScript launcher that Task Scheduler runs via `wscript.exe` instead
of calling `python.exe`/`cmd.exe` directly - this hides the console window
entirely while still running the same `python main.py --fast-only` /
`--slow-only` commands underneath.

**Task Scheduler registration failures, fixed in sequence:**
1. `Register-ScheduledTask : Cannot create a file when that file already
   exists` (0x800700b7) - Calvin's first re-run pasted output showing this
   error but the script's final message still printed "Tasks created,"
   which was misleading. Root-caused as likely a race condition where a
   task was mid-run when the script tried to replace it. Fixed two things:
   (a) the script now calls `Stop-ScheduledTask` and waits one second
   before `Register-ScheduledTask -Force -ErrorAction Stop`, wrapped in
   try/catch with explicit per-task success/failure tracking; (b) the
   final summary message is now conditional on both tasks actually
   succeeding, instead of printing unconditionally.
2. `FAILED to register ... Access is denied` on the next attempt - this is
   a real Windows permission requirement: `-Force` re-registration of an
   existing scheduled task needs PowerShell running as Administrator.
   Calvin was walked through re-running as Administrator, after which both
   tasks registered successfully (confirmed by Calvin: "It says registered
   for both now").

**MCP/local-execution misunderstanding, clarified.** Calvin asked how to
let Claude run commands on his PC and access GitHub directly, believing
that adding a local GitHub MCP server (`npx -y
@modelcontextprotocol/server-github` shown in a Claude Desktop "Local MCP
servers" panel) would grant this. Clarified this is an architectural
boundary, not a missing config step: no MCP server grants a Cowork session
local command execution on Calvin's machine; the "Local MCP servers" panel
shown is a separate Claude Desktop feature not exposed to Cowork sessions;
and even a correctly-connected GitHub MCP would only provide GitHub API
operations (create files, open PRs, etc. through GitHub's API), not local
`git`/PowerShell execution. All git operations in this project have been,
and will continue to need to be, run by Calvin himself in his own
terminal.

**Where to build future similar projects.** Calvin asked where to build a
similar project next time. Recommended Claude Code over Cowork web/desktop
for projects like this one, given the amount of local file/script/scheduler
work involved.

**Migration to ChatGPT/Codex.** Calvin decided to migrate this project from
Claude/Cowork to ChatGPT Desktop/Codex and requested a full documentation
set be created to support that: `README.md` updates, `PROJECT_CONTEXT.md`,
`CHATGPT_PROJECT_INSTRUCTIONS.md`, `MEMORY.md`, `DECISIONS.md`,
`CURRENT_STATUS.md` (with a "Migration Risks and Missing Information"
section), `WORKFLOWS.md`, `CONNECTORS.md`, `TASKS.md`, and this
`CONVERSATION_SUMMARIES/` directory - all written in this same
conversation. See `CURRENT_STATUS.md` for the current state of that effort
and what risks were identified.

**Correction, same day:** once Calvin actually opened the project in
Codex, it turned out there's no "Project Instructions" field to paste
`CHATGPT_PROJECT_INSTRUCTIONS.md` into - Codex instead auto-loads an
`AGENTS.md` file from the project root. The content was moved into a new
`AGENTS.md`, the old file was replaced with a short redirect, and every
other doc's references to it were updated to point at `AGENTS.md`
instead. Also clarified: what looked like a "Settings -> Apps" section
Calvin couldn't find was OpenAI's newer Plugin Directory (apps/skills
merged under "Plugins" as of July 2026), not a missing setting.

## Unresolved at the end of this phase

- Whether the old single (pre-split) Task Scheduler job was ever actually
  removed from Calvin's machine was never confirmed - flagged in
  `TASKS.md`.
- Whether ChatGPT/Codex's actual execution model can run local
  commands/scripts the way this project's workflows assume is genuinely
  unknown and needs to be verified fresh in the new environment - this is
  the central item in `CURRENT_STATUS.md`'s migration risks section.

See `DECISIONS.md` (entries 13 and 15) for the formal records.
