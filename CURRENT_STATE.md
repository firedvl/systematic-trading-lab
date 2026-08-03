# Current state

- Milestone: M3 runner, walk-forward, and sensitivity slice complete.
- Completed: all M0-M2 capabilities plus durable SQLite campaigns and experiments; search-budget enforcement; pending/running/completed/failed lifecycle; heartbeats and stale-run recovery; immutable experiment specifications; training/validation/holdout classification; protected holdout metrics with logged access events; separate approved/unapproved disqualifying qualification gates; a registry-backed backtest runner; chronological walk-forward candidate generation; configurable delayed fills; cost and delay sensitivity candidates; score-free candidate comparison reports; experiment lifecycle CLI; tests and CI.
- Work in progress: none.
- Known limitations: no provider correction lineage, corporate-action processor, point-in-time universe, approved financial thresholds, controlled holdout runner, broker, or execution system. Walk-forward and sensitivity APIs exist, but no financial campaign has been run. Current reports remain fixture evidence, not financial qualification.
- Test status: 22 tests pass; ruff format and lint, strict mypy, secret scan, and diff checks pass on Python 3.12.13. Experiment lifecycle, failed-candidate evidence, delayed fills, split controls, and protected holdout paths pass; live and broker modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: finish M3 policy work by approving or explicitly deferring financial qualification thresholds, then run a reviewed walk-forward and sensitivity campaign before any holdout event.
- Branch: `codex/m3-runner`; draft pull request pending.
