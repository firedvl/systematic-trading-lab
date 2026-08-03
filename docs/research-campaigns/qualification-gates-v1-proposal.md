# Qualification gates v1 proposal

## Status

`qualification-gates-v1` is proposed and unapproved. The machine-readable source is
`config/research/qualification-proposal.json`. Merging this proposal does not approve a gate,
qualify a strategy, authorize a holdout run, or enable execution.

The proposal uses campaign `alpaca-qualification-evidence-20260802-v3`. It sets each threshold
before a holdout review and does not use 2026 data. The thresholds are policy choices for human
review, not universal financial claims. They do not form a composite score: each failed gate stays
visible and disqualifying.

## Proposed gates

| Metric | Proposed gate | Reason |
| --- | ---: | --- |
| Validation fold count | >= 3 | Cover at least three chronological validation periods. |
| Positive validation fold rate | >= 1 | Reject a loss in any validation fold. |
| Fixed-weight benchmark win rate | >= 0.6666666666666666666666666667 | Beat the simple portfolio in at least two of three folds. |
| Worst validation return | >= 0 | Require nonnegative after-cost return in every fold. |
| Worst validation Sharpe | >= 0.5 | Require positive risk-adjusted return with margin above zero. |
| Maximum validation drawdown | <= 0.20 | Cap validation drawdown at twenty percent. |
| Maximum average gross exposure | <= 1 | Keep average exposure unlevered. |
| Maximum top-five-session profit share | <= 0.25 | Limit dependence on a few sessions. |
| Maximum top-instrument profit share | <= 0.50 | Limit dependence on one instrument. |
| Minimum doubled-cost return retention | >= 0.80 | Retain most base return under higher costs. |
| Minimum two-bar-delay return retention | >= 0.80 | Retain most base return under delayed fills. |
| Minimum parameter-neighbor return retention | >= 0.50 | Reject severe local parameter sensitivity. |
| Minimum up-regime sessions | >= 50 | Require a useful positive-market sample in every fold. |
| Minimum down-regime sessions | >= 50 | Require a useful negative-market sample in every fold. |
| Maximum turnover | <= 30 | Bound turnover before execution-capacity analysis. |
| Minimum trade count | >= 100 | Avoid evidence based on a few fills. |
| Campaign candidate count | <= 40 | Bound the search and retain all candidates. |

Every gate has `approved: false`. The loader rejects unknown or missing fields, non-finite
thresholds, duplicate gate names or metrics, unsupported comparisons or scopes, and any mismatch
between proposal status and gate approval flags.

## Evaluation against validation evidence

| Strategy | State | Failed proposed gates |
| --- | --- | --- |
| Moving average | `unapproved` | Fixed-weight benchmark wins; worst validation Sharpe; instrument profit concentration cap; turnover cap |
| Momentum | `unapproved` | Fixed-weight benchmark wins; instrument profit concentration cap; parameter-neighbor retention |

Fixed-weight beat both strategies in all three validation years. Moving average also had a worst
Sharpe of 0.102137, maximum top-instrument profit share of 0.596930, and maximum turnover of
31.823442. Momentum had a maximum top-instrument profit share of 0.501365 and minimum
parameter-neighbor return retention of 0.147412. These failures stay visible even though the
proposal's approval state already prevents qualification.

## Human review

A reviewer should assess each threshold and its rationale without changing strategy parameters or
viewing holdout data. Approval needs a later, separate change that sets the proposal and every gate
to `approved`, explains any revised threshold, and receives explicit human review. Current evidence
does not support such a change because neither candidate passes all proposed gates.
