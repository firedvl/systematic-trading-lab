# Current state

- Milestone: M3 catalog-backed campaign execution slice complete.
- Completed: all prior capabilities plus verified loading of immutable cataloged bars; a bounded CLI for training and validation runs with versioned costs, delayed fills, and strategy parameter validation; and CLI candidate comparisons. The registry records every accepted run before simulation, retains failures, enforces campaign budgets, and keeps holdout paths inaccessible to ordinary commands.
- Work in progress: none.
- Known limitations: no provider correction lineage, corporate-action processor, point-in-time universe, approved financial thresholds, controlled holdout runner, broker, or execution system. Walk-forward and sensitivity APIs exist, but no reviewed financial campaign has been run. Current reports remain fixture evidence, not financial qualification.
- Test status: 23 tests pass; ruff format and lint, strict mypy, secret scan, and diff checks pass on Python 3.12.13. Catalog integrity, bounded CLI runs, experiment lifecycle, failed-candidate evidence, delayed fills, split controls, and protected holdout paths pass; live and broker modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: add provider correction lineage and corporate-action handling before acquiring a reviewed historical dataset for the first walk-forward and sensitivity campaign. Financial qualification thresholds remain explicitly deferred pending human review.
- Branch: `codex/m3-campaign`; draft pull request: https://github.com/firedvl/systematic-trading-lab/pull/8.
