# Current state

- Milestone: M1 correction-lineage and corporate-action control slice complete.
- Completed: all prior capabilities plus immutable dataset version IDs that bind provider, request, adjustment policy, processing versions, and normalized-bar fingerprint; parent links for provider corrections; exact-repeat deduplication; cross-provider metadata isolation; provider adjustment declarations; and fail-closed rejection of unadjusted data. Alpaca requests `adjustment=all`; the deterministic fixture declares that it contains no actions.
- Work in progress: none.
- Known limitations: no local processor for unadjusted splits, dividends, symbol changes, or delistings; no point-in-time universe, approved financial thresholds, controlled holdout runner, broker, or execution system. Walk-forward and sensitivity APIs exist, but no reviewed financial campaign has been run. Current reports remain fixture evidence, not financial qualification.
- Test status: 25 tests pass; ruff format and lint, strict mypy, secret scan, and diff checks pass on Python 3.12.13. Lineage, adjustment-policy, catalog recovery and rebuild, Alpaca, and experiment CLI checks pass; live and broker modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: acquire and seal a reviewed provider-adjusted historical dataset for the first walk-forward and sensitivity campaign, then document proposed qualification thresholds for human review. Point-in-time universe work remains before research expands beyond the fixed ETF set.
- Branch: `codex/m1-lineage`; draft pull request pending.
