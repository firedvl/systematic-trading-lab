# Alpaca long-horizon momentum training v4

## Outcome

This training-only campaign completed all four recorded runs. The 252-session time-series momentum candidate and its predeclared 189- and 315-session neighbors lost money, had negative Sharpe ratios, and turned over more than the fixed-weight benchmark. The family is rejected before validation. No 2023–2026 bars or holdout metrics were read.

## Sealed input and boundary

- Dataset ID: `508c606884112c92402707c30b56fc9d8c07cfc1c01c64f8538a6494888eeeca`
- Normalized fingerprint: `4fe62ab615ae713e23926da940256b9a728db39c2bc60c028df6d1136be49494`
- Universe: `liquid-etfs-v1`, fingerprint `cb0827988973c61362f2014c3f20fde53081217a32fa70f04a5a9e1a48b01985`
- Campaign: `alpaca-long-horizon-training-20260803-v4`
- Campaign code commit: `1008f3b9ca41db77a2950cbfe25df7e5fda2029f`
- Split: training only, 2020-07-27 through 2022-12-30 inclusive
- Search budget: four; four records created and completed

The bounded cataloged runner used a Parquet predicate for the recorded training range. It did not load the rest of the dataset.

## Predeclared candidates

The campaign recorded one fixed-weight training benchmark, a 252-session time-series momentum candidate, and 189- and 315-session parameter neighbors. Both neighbors name the 252-session record as their parent. The long horizon was chosen before these runs; no result selected another lookback.

| Record | Lookback | Total return | Max drawdown | Sharpe | Average exposure | Turnover | Trades | Top-instrument share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `v4-fixed-weight-training` | — | -0.001359 | 0.257724 | 0.069103 | 0.994784 | 2.675129 | 557 | 0.436930 |
| `v4-momentum-189-training` | 189 | -0.059137 | 0.125870 | -0.431789 | 0.284913 | 9.761769 | 890 | 1.000000 |
| `v4-momentum-252-training` | 252 | -0.090712 | 0.137317 | -0.678432 | 0.196324 | 9.696135 | 626 | undefined |
| `v4-momentum-315-training` | 315 | -0.124912 | 0.150651 | -0.831934 | 0.171565 | 7.207932 | 544 | undefined |

The top-instrument share is undefined when no instrument has positive final profit. That missing value is adverse evidence, not zero concentration.

## Decision

Do not run this family on validation or holdout data. The 189-session neighbor lost less than the other momentum runs, but choosing it would not fix its negative return, negative Sharpe ratio, benchmark deficit, high turnover, or full concentration of positive instrument profit.

The next candidate should address portfolio allocation and turnover as design constraints before another training campaign. The current per-symbol strategy callback rejects cross-symbol targets, so a session-level portfolio target boundary needs its own reviewed implementation and no broker authority.

## Report fingerprints

- Fixed weight: `18637922c70e687e6a7382bb27be4c48e8a3377fdbb9107a1ccf44db0b7c2ea4`
- Momentum 189: `b0202169e80ae63163969aef1e50d6c9287f7c2a0245749df110d1c3bbcc7408`
- Momentum 252: `c11824bf6a665535a6b13a3c07a0ea34cfb6232db8de7572c24064a636aa27d8`
- Momentum 315: `68072a3ab1eca8cf9af6abfbdb995700079644f7549cb968a8db98809fd898ad`

The reports and registry remain in ignored local runtime storage. This document names every campaign record and preserves the result needed to reject the family without opening a later split.
