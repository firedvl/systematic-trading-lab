# Rapid-003 bounded strategy program

## Status

`rapid-003-bounded-strategy-discovery` is open for non-authoritative daily research. The machine
ledger is `config/research/rapid-003-strategy-ledger-v1.json`. It starts from main
`26686b3dad56fe0dc327f3fadf8a63b3c0e21348` after the Rapid-002 rejection merged.

Rapid-002 remains closed rejected evidence. This program will not retry it, tune from its controlled
result, or open its proposed 2018–2019 independent range.

## Data and exposure

- Dataset: `508c606884112c92402707c30b56fc9d8c07cfc1c01c64f8538a6494888eeeca`.
- Dataset fingerprint:
  `4fe62ab615ae713e23926da940256b9a728db39c2bc60c028df6d1136be49494`.
- Universe: SPY, QQQ, IWM, TLT, and GLD adjusted daily bars.
- Exposed research range: 2020-07-27 through 2026-07-31.
- Sealed independent range: 2018-01-02 through 2019-12-31. No access is allowed.
- Sealed V3 range: 2026-10-01 through 2027-04-15. No access is allowed.

This program may use only the named catalog dataset and must pass the exposed start and end dates to
every research command. It will not run data acquisition or local-data import. The final audit will
derive every observed range from the initially empty Rapid store. This is the program's operator
boundary; it does not claim that the generic data CLI reserves the 2018–2019 dates for every future
caller.

Rapid state remains non-authoritative. This program cannot create paper, broker-write, live,
protected-holdout, V3, or automatic-promotion authority. It must not mutate
`strategic-allocation-21`.

## Search contract

The program may run at most 2,000 Rapid parent configurations. It will use coarse, economically
sensible grids, reject weak regions early, and test only bounded neighbors around survivors. Normal
execution is 5/1 bps with a one-bar delay. Stress A is 10/2 bps with a two-bar delay. Stress B is
20/5 bps with a three-bar delay.

The program starts with zero Rapid runs. Before each batch, the operator will count every non-fold,
non-stress row in `rapid_runs` and will not start a batch that would cross 2,000. Fold
and stress rows remain separately counted. This avoids adding an orchestration subsystem for one
bounded local campaign while leaving every attempted run in the existing durable store.

The four new state-transition strategies use reevaluation cadences of at least five sessions. Their
next evaluation therefore occurs after the longest declared three-bar Stress B fill delay.

Every family below must end as tested or explicitly infeasible. The machine ledger records the
hypothesis, implementation, parameter dimensions, configurations, result, and reason.

| ID | Family | Initial implementation |
| --- | --- | --- |
| A | Absolute momentum | Existing momentum and risk-managed momentum plus multi-horizon agreement |
| B | Relative strength | Existing positive-filtered top-N rotation |
| C | Dual momentum | Role-aware risk rotation with single-asset and diversified defensive fallback |
| D | Trend following | Existing moving-average state transitions |
| E | Breakout | Existing entry/exit channel state transitions |
| F | Pullback / mean reversion | Existing trend pullback and moving-average reversal |
| G | Volatility management | Existing volatility target, balance, and risk-managed momentum |
| H | Risk parity / diversification | Existing capped inverse-volatility allocation |
| I | Risk-on / risk-off regimes | SPY trend-plus-volatility regime allocation |
| J | Defensive rotation | Covered by single-asset and diversified dual-momentum fallback |
| K | Tactical asset allocation | Covered by dual and multi-horizon active subsets |
| L | Multi-horizon signals | Two-horizon positive agreement and ranking |
| M | Signal + regime combinations | Test only combinations with independent economic meaning |
| N | Drawdown-aware exposure | SPY trailing-drawdown state rule |
| O | Cash / defensive filters | Existing positive filters plus dual-momentum fallback |
| P | Diversification-constrained momentum | Equal-weight top-N signals by construction |

The new rules are the smallest missing behavior. Existing implementations cover the other families.
No optimizer, opaque score, genetic search, Bayesian search, or giant Cartesian grid is planned.

## Freeze and qualification

Broad Rapid research must finish before the final cohort is selected. All cohort definitions,
parameters, source, data, ranges, and execution assumptions must freeze together before any
controlled result is inspected. Each frozen candidate then receives one controlled qualification
attempt under unchanged gates. A failure is final for this program.

The program stops after the frozen cohort completes. Passing candidates remain frozen for a later
user-authorized independent evaluation; failed candidates do not start another adaptive loop.
