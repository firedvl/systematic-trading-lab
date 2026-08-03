# Alpaca volatility-balanced allocation training v7

## Outcome

The four-record campaign completed under code commit
`94524806b731f5bf79bfba55bb6cc3d89ce13f2e`. The 63-session base lost 3.41%, trailed
fixed-weight, had a negative Sharpe ratio, exceeded the drawdown and instrument-concentration
limits, and failed both parameter-neighbor conditions. The family stops before validation.

| Record | Window | Return | Sharpe | Max drawdown | Top-instrument profit share | Turnover | Fills |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `m3-vb-fixed-weight-training` | — | -0.001359 | 0.069103 | 0.257724 | 0.436930 | 2.675129 | 557 |
| `m3-vb-window-42-training` | 42 | 0.004374 | 0.077359 | 0.238267 | 0.478282 | 5.781357 | 575 |
| `m3-vb-window-63-training` | 63 | -0.034052 | -0.050968 | 0.239707 | 0.636804 | 4.275324 | 548 |
| `m3-vb-window-84-training` | 84 | -0.069507 | -0.180266 | 0.243084 | 0.830707 | 3.377449 | 529 |

The comparison report fingerprint is
`d6ea86ce78398ddf81ab6a3a9dcf5796135f2927f80f8b59f79d5466c11a8ce9`. No 2023–2026
bars, validation data, holdout results, or execution systems were accessed. The immutable local
registry retains every record.

## Predeclared design

This training-only campaign tests allocation from trailing volatility without a return signal,
ranking rule, or momentum cash filter. All five ETFs remain eligible after warm-up. The strategy
rebalances every five sessions, assigns inverse sample-volatility weights, redistributes weights
above a fixed 30% per-ETF cap, and targets full unlevered exposure after warm-up.

The cap is a diversification invariant: it is 1.5 times the five-asset equal weight and requires at
least four holdings for full exposure. It is not a searched parameter. An asset with zero measured
volatility, incomplete history, or an incomplete session fails the run.

## Sealed plan

- Campaign: `m3-volatility-balanced-v1`
- Dataset ID: `508c606884112c92402707c30b56fc9d8c07cfc1c01c64f8538a6494888eeeca`
- Normalized fingerprint: `4fe62ab615ae713e23926da940256b9a728db39c2bc60c028df6d1136be49494`
- Universe: `liquid-etfs-v1`, fingerprint `cb0827988973c61362f2014c3f20fde53081217a32fa70f04a5a9e1a48b01985`
- Split: training only, 2020-07-27 through 2022-12-30 inclusive
- Search budget: four records; no replacement runs
- Benchmark: fixed weight, five-session rebalance
- Base: volatility window 63, rebalance interval 5, fixed cap 30%
- Neighbors: volatility windows 42 and 84; all other values fixed
- Costs and fills: `conservative-bps-v1` and `next-bar-v1`

The campaign stops before validation unless the base has positive after-cost return, beats fixed
weight, reaches a Sharpe ratio of at least 0.5, stays at or below 20% maximum drawdown, 25%
top-five-session profit share, 50% top-instrument profit share, 30 turnover, and average gross
exposure of one, and records at least 100 fills. Both neighbors must remain nonnegative and retain at least
50% of base return. Invalid or undefined required metrics fail the screen. No gate changes,
validation reads, holdout access, or execution authority belong in this campaign.
