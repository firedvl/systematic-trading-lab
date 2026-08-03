# Current state

- Milestone: M3 registry-backed qualification evidence in progress; no candidate qualified.
- Completed: all prior capabilities plus campaign `alpaca-qualification-evidence-20260802-v3`, the 17-gate `qualification-gates-v1` proposal, and a strict evidence manifest that assigns the campaign's base, benchmark, cost, delay, and parameter-neighbor records to reviewable roles. The aggregator verifies registry relationships and writes an immutable fingerprinted report without loading market data.
- Work in progress: registry-backed qualification evidence under review; every gate remains unapproved.
- Known limitations: every proposed threshold remains unapproved. Fixed-weight beat both trend baselines in every validation year. Moving average fails four proposed gates and momentum fails three. Alpaca IEX common coverage begins on 2020-07-27; the installed XNYS calendar begins on 2006-08-02. The 2026 data remains untouched. There is no controlled holdout runner, broker, or execution system.
- Test status: 40 tests pass; ruff format and lint, strict mypy, secret scan, and diff checks pass on Python 3.12.13. Evidence aggregation, relationship validation, immutable-write, and CLI checks pass; live and broker modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: replace the raw holdout-creation boolean with a stored authorization tied to approved, passing qualification evidence. Current candidates cannot receive that authorization.
- Branch: `codex/m3-qualification-evidence`; draft pull request: https://github.com/firedvl/systematic-trading-lab/pull/14.
