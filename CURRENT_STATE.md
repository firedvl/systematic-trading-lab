# Current state

- Milestone: M2 backtester and baseline slice complete.
- Completed: all M0/M1 capabilities plus explicit next-bar event timing; long-only cash and position accounting; configurable bps slippage and commission; decision, order, trade, and equity ledgers; total-return, drawdown, turnover, and trade-count metrics; cash and buy-and-hold target strategies; deterministic fixture backtest CLI; tests and CI.
- Work in progress: none.
- Known limitations: no provider correction lineage, corporate-action processor, point-in-time universe, fixed-weight portfolio, walk-forward backtester, benchmark reports, qualification, broker, or execution system. The current buy-and-hold CLI example uses SPY only; multi-instrument allocation is a later baseline.
- Test status: 12 tests pass; ruff format and lint, strict mypy, and secret scan pass on Python 3.12.13. Fixture backtest smoke produced deterministic cash and buy-and-hold fingerprints; offline broker/data modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: finish M2 with fixed-weight periodic rebalance, moving-average and momentum baselines, benchmark comparison, and deterministic report artifacts.
- Branch: `codex/m2-backtester`; pull request pending and will be a regular non-draft PR per user instruction.
