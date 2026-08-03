# Current state

- Milestone: M3 controlled holdout authorization in progress; no candidate qualified.
- Completed: all prior capabilities plus registry-backed qualification evidence and one-time stored holdout-run authorization. The raw holdout-creation boolean is gone. Authorization rebuilds evidence, requires an approved proposal and all passing gates, binds the exact candidate and provenance, and is consumed atomically by one matching post-validation holdout record. Completed holdout metrics allow one logged read event.
- Work in progress: controlled holdout authorization under review; every current gate remains unapproved.
- Known limitations: every proposed threshold remains unapproved. Fixed-weight beat both trend baselines in every validation year. Moving average fails four proposed gates and momentum fails three. Alpaca IEX common coverage begins on 2020-07-27; the installed XNYS calendar begins on 2006-08-02. The 2026 data remains untouched. There is no controlled holdout runner, broker, or execution system.
- Test status: 41 tests pass; ruff format and lint, strict mypy, secret scan, and diff checks pass on Python 3.12.13. Evidence-integrity, authorization-refusal, exact-binding, atomic-consumption, and one-time-read checks pass; live and broker modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: add a controlled holdout executor that loads only the authorized time range after consuming a valid authorization. Current candidates cannot reach that path.
- Branch: `codex/m3-holdout-authorization`; draft pull request: https://github.com/firedvl/systematic-trading-lab/pull/15.
