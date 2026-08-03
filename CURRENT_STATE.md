# Current state

- Milestone: M3 first provider-data campaign evidence complete; no candidate qualified.
- Completed: all prior capabilities plus strict ignored `.env` loading, inclusive-to-exclusive Alpaca daily request mapping, a sealed 7,555-bar provider-adjusted dataset for 2020-07-27 through 2026-07-31, equal portfolio allocation for multi-asset trend targets, and two durable 22-candidate campaigns. The first campaign remains failed-method evidence; the corrected campaign covers three chronological validation years plus doubled-cost and two-bar-delay variants.
- Work in progress: first provider-data campaign slice under review in draft pull request #11.
- Known limitations: Alpaca IEX credentials returned complete common coverage only from 2020-07-27; the installed XNYS calendar begins on 2006-08-02. Qualification still lacks approved financial thresholds, risk-adjusted return, exposure, concentration, regime, and parameter-neighborhood metrics. Fixed-weight beat both trend baselines in every validation year. The 2026 data remains untouched. There is no controlled holdout runner, broker, or execution system.
- Test status: 31 tests pass; ruff format and lint, strict mypy, secret scan, and diff checks pass on Python 3.12.13. Local environment loading, Alpaca range mapping, multi-asset allocation, universe, lineage, catalog recovery and rebuild, and experiment checks pass; live and broker modes remain rejected.
- Safety: defaults offline; live execution and broker submission are absent.
- Next task: add the missing qualification metrics, then submit explicit financial thresholds for human review before any controlled holdout evaluation.
- Branch: `codex/m3-provider-campaign`; draft pull request: https://github.com/firedvl/systematic-trading-lab/pull/11.
