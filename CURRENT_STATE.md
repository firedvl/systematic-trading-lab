# Current state

- Milestone: M3 experiment registry and qualification-control slice complete.
- Completed: all M0-M2 capabilities plus durable SQLite campaigns and experiments; search-budget enforcement; pending/running/completed/failed lifecycle; heartbeats and stale-run recovery; immutable experiment specifications; training/validation/holdout classification; protected holdout metrics with logged access events; separate approved/unapproved disqualifying qualification gates; experiment lifecycle CLI; tests and CI.
- Work in progress: none.
- Known limitations: no provider correction lineage, corporate-action processor, point-in-time universe, automated experiment runner, walk-forward evaluation, robustness/cost-sensitivity campaign, approved financial thresholds, broker, or execution system. Current reports remain fixture evidence, not financial qualification.
- Test status: 18 tests pass; ruff format and lint, strict mypy, and secret scan pass on Python 3.12.13. Experiment CLI lifecycle and protected holdout paths pass; live and broker modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: continue M3 with a registry-backed experiment runner, walk-forward splits, robustness and cost-sensitivity runs, and candidate comparison reports.
- Branch: `codex/m3-experiments`; draft pull request pending.
