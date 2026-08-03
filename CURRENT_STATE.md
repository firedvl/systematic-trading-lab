# Current state

- Milestone: M3 approved qualification policy; no candidate qualified.
- Completed: all prior capabilities plus human approval of all 17 `qualification-gates-v1` thresholds. Registry-only reproduction under the approved policy formally rejects moving average on four gates and momentum on three; no holdout authorization exists.
- Work in progress: predeclared weekly risk-managed momentum candidate under implementation. Approved thresholds remain unchanged.
- Known limitations: the relative-strength family will not proceed to validation. Its best training result was the 168-session neighbor with 0.025127 total return, 0.161472 Sharpe, 0.150061 maximum drawdown, and 45 trades. The 126-session base returned 0.017025 with a 0.691146 top-instrument profit share. Fixed-weight beat both earlier short-horizon trend baselines in every validation year, and the rejected long-horizon momentum family lost money across all training parameters. Alpaca IEX common coverage begins on 2020-07-27; the installed XNYS calendar begins on 2006-08-02. The 2023–2026 data remains untouched by both training-only campaigns, and the 2026 segment remains untouched by all research. There is no qualified candidate, broker, or execution system.
- Test status: 61 tests pass; ruff format and lint, strict mypy, secret scan, and diff checks pass on Python 3.12.13. Approved passing evidence can authorize one exact holdout; approved failing evidence cannot. Relative-strength ranking, risk-managed allocation controls, complete-session portfolio controls, bounded research reads, evidence integrity, and one-time access checks pass; live and broker modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: complete and verify the risk-managed momentum implementation, commit its exact revision, then run only the four-record 2020–2022 training campaign.
- Branch: `codex/m3-risk-managed-momentum`.
