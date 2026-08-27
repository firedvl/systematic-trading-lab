# Program 002 prospective missing-data disposition

Status: proposed and frozen for independent review. This is not acquisition authority.

## Evidence and cause

Program 002 stopped before an exposed dataset, quote calibration, cost model, campaign binding, or
strategy run existed. The attempted five-minute source omitted nine MDY coordinates across five
full XNYS sessions: two on 2020-12-04 and seven across 2021-02-03, 2021-02-05, 2021-02-10, and
2021-02-22. The February segment had 19,259 of 19,266 expected rows.

The February request drained terminal pagination. Four later full-session MDY one-minute requests
returned 1,168 rows. Their five-minute aggregation matched all 305 existing controls exactly, while
the same seven target buckets remained empty. This proves provider-payload absence, not why the
observations are absent. Persisted evidence does not establish no eligible market activity, a
provider coverage gap, a corporate action, an instrument-history boundary, or another external
cause. It does rule out transport, pagination, duplicate, parsing, normalization, and calendar-bound
errors as causes of the seven February coordinates.

## Disposition

The unit of disposition is the whole session. An eligible full session must contain every expected
five-minute bar for all twelve ranking ETFs plus SPY: 13 symbols, 78 bars each. A scheduled early
close remains flat and may supply context only when all 13 symbols have all 42 expected bars. Any
missing bar excludes the session from every family, configuration, scenario, benchmark, and future
context use. No symbol may be dropped from the rank. No missing price or volume may be filled,
including the two earlier December predecessor-close rows; their bytes remain historical evidence,
but 2020-12-04 is incomplete under this rule.

Every complete thirty-minute feature bucket still needs six bars. Eligible full sessions must have
all entry bars at 11:35, 11:40, and 11:45 New York and all exit bars at 13:35, 13:40, 13:45, 15:35,
15:40, and 15:45. Admission happens before any candidate runs, so the rule cannot depend on which
symbol or hold a candidate would later use.

The fixed exposed context range must retain all twenty sessions. Controlled A's first twenty
scheduled sessions and the final twenty Block A sessions used by Controlled B must also be complete;
they cannot be replaced. Later rolling contexts use only strictly prior complete sessions inside the
fixed chronology. An excluded session never generates a no-trade candidate result.

Quote calibration keeps its existing conservative rule: every one of 73 sessions by nine clocks by
13 symbols needs at least 57 of 60 eligible causal grid observations. An absent or failed window
fails the entire calibration. No other window may compensate, and no quote or cost fallback exists.

## Loss and bias ceilings

Each fixed discovery block, exposed test fold, and controlled evaluation block may lose at most one
trade-eligible session and at most one percent of its scheduled trade sessions. Any rolling twenty-
session window may contain at most one incomplete session and at most one incomplete session caused
by the same symbol. More than one contiguous incomplete session also fails admission. Within-session
bar contiguity remains a reported diagnostic; any missing bar already excludes that whole session.
Required context allows no loss.

The admission report is structural. It records dataset identity, eligible and excluded sessions,
missing coordinates and reasons, per-period loss, symbol/month/clock concentration, rolling and
contiguous gaps, quote coverage, pass or fail, and a fingerprint. It cannot contain a fill, P&L,
return, Sharpe, candidate rank, or strategy gate.

The exposed entry point accepts observed coverage, not an expected schedule or policy. It loads the
reviewed plans and disposition, verifies the frozen 1,531-session XNYS table and 657-window quote-grid
fingerprints, and applies fixed thresholds. The generic evaluator is private and exists only for
synthetic mechanics tests; its output cannot stand in for real dataset admission. A later controlled
authority must bind reviewed calendar tables without changing this rule or either block's dates.

## Scientific assessment

Whole-session exclusion preserves the fixed cross-section and does not alter either hypothesis,
configuration grid, tie rule, chronology, or search budget. The low ceiling limits the sample change
and prevents the disposition from becoming a performance-dependent salvage mechanism.

The already-known source evidence does not fit that ceiling. Four February exclusions occur in one
fixed discovery period and within one twenty-session horizon, all are caused by MDY, and one recorded
gap is two consecutive bars. Missingness may therefore be related to the same activity dimension
used by the strategy. Raising the limits to retain these sessions would be a post-hoc source
accommodation.
The disposition mechanics are scientifically acceptable, but the attempted source is not admissible
under them. A different source is the next scientifically cleaner path.

No chronology or search budget changed. The same rule applies to Controlled A and B without reading
either block. All acquisition, admission, strategy, qualification, controlled, protected, PAPER,
broker-write, and live flags remain false.
