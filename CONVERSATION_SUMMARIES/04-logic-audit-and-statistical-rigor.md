# Conversation Summary: Logic Audit and Statistical Rigor Fixes

**Date:** 2026-07-12 (continuation of the same day's work)

## What happened

Calvin asked for a full check that the dashboard's logic correctly points
users toward buy/sell, that the accuracy-tracking approach would actually
reveal if a data source or threshold needs revising, and for research on
best-practice ways to display all of this - including whether the UI itself
should change.

Did online research on standard practices for evaluating trading-signal
accuracy (confusion-matrix-style splits, baseline/naive-comparison
requirements, confidence intervals for small samples) before proposing
changes, rather than guessing at what "rigorous" should mean.

**Found and fixed one real bug:** a price/sentiment window mismatch - the
Signal computation was comparing sentiment collected over one window against
a price move measured over a differently-aligned window, which could produce
a misleading Signal even when each input was individually correct. Fixed by
aligning both windows to the same reference points.

**Added statistical rigor to the accuracy log** (none of this existed
before this phase):
- **Baseline comparison** (`baseline_up_pct`) - what fraction of the time
  the ticker simply moved up regardless of any Signal, so accuracy_pct can
  be judged against market drift instead of a bare percentage.
- **Wilson score confidence intervals** on accuracy_pct - chosen over a
  normal approximation because it stays well-behaved at the small sample
  sizes this project will have for a long time.
- **`low_sample` flag** and `MIN_GRADED_FOR_CONFIDENCE = 20` threshold - so
  the dashboard visibly warns against over-trusting an accuracy number
  computed from a handful of graded calls.
- **BUY/SELL split** - accuracy computed separately for BUY calls and SELL
  calls, since a rule can systematically favor one direction.
- **Per-source attribution** (`source_breakdown` column) - which source(s)
  contributed to the sentiment that drove a given Signal, added via a
  backward-compatible in-place migration (existing rows are left with no
  breakdown rather than being backfilled/guessed at).

Source-specific grading horizons (the idea that fast chatter and slower news
might have meaningfully different natural prediction horizons) came up in
research but was explicitly deferred - not enough historical data yet to
tune this against.

## Errors hit and fixed in this phase

- A test-harness-only bug (not a product bug): a test double for
  `config/settings.py` resolved `DB_PATH` one directory level wrong
  (`config/test.db` instead of `test.db`) due to a missing
  `os.path.dirname` call, which caused stale data to leak between test
  runs. Fixed in the test harness only.

## Unresolved at the end of this phase

- Not enough real graded signal_log history existed yet at the time of this
  audit to actually apply the new baseline/CI/BUY-SELL-split machinery to a
  real decision about revising a source or threshold - that's a `Next`
  item in `TASKS.md`, to be done once time has passed.

See `DECISIONS.md` (entry 14) for the formal record.
