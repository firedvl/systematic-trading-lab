# Current state

- Milestone: M0 foundation plus safe offline M1 fixture slice complete.
- Completed: persistent policies; typed package; fail-closed configuration; domain models; canonical fingerprints; atomic content-addressed datasets; SQLite catalog and reconstruction; deterministic five-symbol fixture provider; bar validation and quarantine evidence; doctor, status, import, describe, validate, and rebuild CLI; tests and CI.
- Work in progress: none.
- Known limitations: no network provider, exchange calendar, Parquet storage, corporate-action processor, backtester, qualification, broker, or execution system.
- Test status: 6 tests pass; ruff format and lint, strict mypy, and secret scan pass on Python 3.12.13. CLI smoke import produced 25 bars and stable fingerprint `1e4db1750dfc47a24def1b6e95f0ca76fde224fcf24b862fb7bf8fc7dcac746f`; re-import reused it; live mode exited 2.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: implement the next M1 slice: exchange-calendar validation, immutable raw snapshots, Parquet normalized artifacts, and a read-only Alpaca historical-data adapter with mocked integration tests.
- Branch: `codex/m0-foundation`; draft pull request: https://github.com/firedvl/systematic-trading-lab/pull/1.
