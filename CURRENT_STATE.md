# Current state

- Milestone: M2 backtester and baseline/report slice complete.
- Completed: all M0/M1 capabilities plus explicit next-bar event timing; long-only cash and position accounting; configurable bps slippage and commission; decision, order, trade, and equity ledgers; total-return, drawdown, turnover, and trade-count metrics; cash, buy-and-hold, fixed-weight periodic rebalance, moving-average trend, and time-series momentum target strategies; cash-relative benchmark comparisons; deterministic immutable JSON report output; fixture backtest CLI; tests and CI.
- Work in progress: none.
- Known limitations: no provider correction lineage, corporate-action processor, point-in-time universe, walk-forward evaluation, qualification, experiment registry, broker, or execution system. The current report baselines run on deterministic fixtures, not validated financial evidence.
- Test status: 14 tests pass; ruff format and lint, strict mypy, and secret scan pass on Python 3.12.13. Fixture report output is deterministic; live and broker/data modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: begin M3 with durable experiment records, campaign/restart state, training-validation-holdout controls, and qualification gates.
- Branch: `codex/m2-baselines`; draft pull request: https://github.com/firedvl/systematic-trading-lab/pull/5.
