# Qualification gates v1

## Status

`qualification-gates-v1` is approved. The machine-readable source is
`config/research/qualification-proposal.json`. Approval does not qualify a strategy, authorize a
holdout run, or enable execution.

The policy uses campaign `alpaca-qualification-evidence-20260802-v3`. Each threshold was set and
reviewed before a holdout review without using 2026 data. The thresholds are project policy
choices, not universal financial claims. They do not form a composite score: each failed gate
stays visible and disqualifying.

## Approved gates

| Metric | Approved gate | Reason |
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
| Total base-validation trade count | >= 100 | Require operational fill evidence across the full predeclared validation campaign. |
| Campaign candidate count | <= 40 | Bound the search and retain all candidates. |

Every gate has `approved: true`. The loader rejects unknown or missing fields, non-finite
thresholds, duplicate gate names or metrics, unsupported comparisons or scopes, and any mismatch
between proposal status and gate approval flags.

The trade-count gate sums fills across the three base-validation folds. The earlier per-fold
minimum conflated execution count with independent return observations and structurally excluded
monthly portfolio strategies that cannot produce 100 fills in one year. Per-fold return, Sharpe,
drawdown, regime, and concentration gates still reject thin or concentrated evidence. The revised
gate retains the approved threshold of 100 campaign-wide fills and does not change any strategy
result.

## Evaluation against validation evidence

| Strategy | State | Failed approved gates |
| --- | --- | --- |
| Moving average | `rejected` | Fixed-weight benchmark wins; worst validation Sharpe; instrument profit concentration cap; turnover cap |
| Momentum | `rejected` | Fixed-weight benchmark wins; instrument profit concentration cap; parameter-neighbor retention |

Fixed-weight beat both strategies in all three validation years. Moving average also had a worst
Sharpe of 0.102137, maximum top-instrument profit share of 0.596930, and maximum turnover of
31.823442. Momentum had a maximum top-instrument profit share of 0.501365 and minimum
parameter-neighbor return retention of 0.147412. These failures prevent qualification and stay
visible in the approved report.

## Approval

The user approved all 17 thresholds on 2026-08-03 after reviewing their purpose. This approval-only
change does not alter strategy parameters or inspect holdout data. Neither current candidate passes
all gates, so both are rejected and no holdout authorization can be stored.
