# Current state

- Milestone: M1 point-in-time fixed-universe slice complete.
- Completed: all prior capabilities plus issuer-sourced membership intervals for SPY, QQQ, IWM, TLT, and GLD; fail-closed full-range membership checks before provider access; and universe IDs and fingerprints bound into datasets, correction lineage, and experiment records. Manual experiment creation now reads dataset and universe provenance from the catalog instead of accepting a caller-supplied fingerprint.
- Work in progress: point-in-time universe slice under review in draft pull request #10.
- Known limitations: no local processor for unadjusted splits, dividends, symbol changes, or delistings; approved financial thresholds, reviewed provider dataset, controlled holdout runner, broker, or execution system. The first universe version supports one membership interval per symbol. Walk-forward and sensitivity APIs exist, but no reviewed financial campaign has been run. Current reports remain fixture evidence, not financial qualification.
- Test status: 28 tests pass; ruff format and lint, strict mypy, secret scan, and diff checks pass on Python 3.12.13. Universe, lineage, adjustment-policy, catalog recovery and rebuild, Alpaca, and experiment CLI checks pass; live and broker modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: acquire and seal a reviewed provider-adjusted historical dataset for the first walk-forward and sensitivity campaign, then document proposed qualification thresholds for human review. Alpaca acquisition requires research credentials that are not present in the current environment.
- Branch: `codex/m1-universe`; draft pull request: https://github.com/firedvl/systematic-trading-lab/pull/10.
