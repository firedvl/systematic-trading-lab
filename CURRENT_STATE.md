# Current state

- Milestone: M3 qualification-metric and parameter-neighborhood evidence complete; no candidate qualified.
- Completed: all prior capabilities plus report schema v2 metrics for complete-session drawdown, annualized volatility, zero-rate Sharpe ratio, gross exposure, profitable-session rate, top-five-session profit share, top-instrument profit share, and SPY up/down regimes. Campaign `alpaca-qualification-evidence-20260802-v3` records 34 completed candidates across three chronological validation years, cost and delay variants, and 15/20/25-session parameter neighborhoods.
- Work in progress: qualification-metric slice under review in draft pull request #12.
- Known limitations: financial thresholds remain unapproved, fixed-weight beat both trend baselines in every validation year, and parameter neighbors show material variation. Alpaca IEX common coverage begins on 2020-07-27; the installed XNYS calendar begins on 2006-08-02. The 2026 data remains untouched. There is no controlled holdout runner, broker, or execution system.
- Test status: 32 tests pass; ruff format and lint, strict mypy, secret scan, and diff checks pass on Python 3.12.13. Complete-session metrics, risk and concentration evidence, parameter neighborhoods, provider data, experiment controls, and prior gates pass; live and broker modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: submit explicit benchmark, risk, concentration, sensitivity, and search-volume thresholds for human review before any controlled holdout evaluation.
- Branch: `codex/m3-qualification-metrics`; draft pull request: https://github.com/firedvl/systematic-trading-lab/pull/12.
