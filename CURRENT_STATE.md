# Current state

- Milestone: M3 qualification-threshold proposal in progress; no candidate qualified.
- Completed: all prior capabilities plus campaign `alpaca-qualification-evidence-20260802-v3`, which records 34 completed candidates across three chronological validation years, cost and delay variants, and 15/20/25-session parameter neighborhoods. `qualification-gates-v1` now proposes 17 separate benchmark, risk, exposure, concentration, sensitivity, regime-coverage, activity, and search-volume gates. A strict loader rejects malformed or inconsistently approved proposal files.
- Work in progress: unapproved qualification gates under review; merging the proposal does not approve them.
- Known limitations: every proposed threshold remains unapproved. Fixed-weight beat both trend baselines in every validation year. Moving average fails four proposed gates and momentum fails three. Alpaca IEX common coverage begins on 2020-07-27; the installed XNYS calendar begins on 2006-08-02. The 2026 data remains untouched. There is no controlled holdout runner, broker, or execution system.
- Test status: 37 tests pass; ruff format and lint, strict mypy, secret scan, and diff checks pass on Python 3.12.13. Proposal-shape, approval-state, duplicate-gate, finite-threshold, and unapproved-evaluation checks pass; live and broker modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: complete human review of the proposed gates. Current candidates do not pass all gates, so approval and controlled holdout evaluation remain blocked.
- Branch: `codex/m3-threshold-proposal`; draft pull request: https://github.com/firedvl/systematic-trading-lab/pull/13.
