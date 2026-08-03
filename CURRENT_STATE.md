# Current state

- Milestone: M1 market-data foundation, offline and read-only provider slice complete.
- Completed: persistent policies; fail-closed configuration; domain models; canonical fingerprints; atomic content-addressed datasets; raw JSONL snapshots; deterministic Parquet normalized artifacts; rebuildable SQLite catalog; XNYS session validation; deterministic five-symbol fixture provider; paginated read-only Alpaca historical-bars adapter; bar validation and quarantine evidence; doctor, status, fixture import, Alpaca import, describe, validate, and rebuild CLI; tests and CI.
- Work in progress: none.
- Known limitations: no provider correction lineage, corporate-action processor, point-in-time universe, backtester, qualification, broker, or execution system.
- Test status: 9 tests pass; ruff format and lint, strict mypy, and secret scan pass on Python 3.12.13. CLI smoke import produced 25 bars and stable fingerprint `1e4db1750dfc47a24def1b6e95f0ca76fde224fcf24b862fb7bf8fc7dcac746f`; re-import reused it; live mode and offline Alpaca import were rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: begin M2 with event/timestamp semantics, portfolio accounting, conservative costs, trade and decision ledgers, and the cash and buy-and-hold baselines.
- Branch: `codex/m1-market-data`; pull request pending.
