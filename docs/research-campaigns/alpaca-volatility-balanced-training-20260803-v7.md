# Alpaca volatility-balanced allocation training v7

## Predeclared design

This training-only campaign tests allocation from trailing volatility without a return signal,
ranking rule, or momentum cash filter. All five ETFs remain eligible after warm-up. The strategy
rebalances every five sessions, assigns inverse sample-volatility weights, redistributes weights
above a fixed 30% per-ETF cap, and targets full unlevered exposure.

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
top-five-session profit share, 50% top-instrument profit share, 30 turnover, and full unlevered
average gross exposure, and records at least 100 fills. Both neighbors must remain nonnegative and
retain at least 50% of base return. Invalid or undefined required metrics fail the screen. No gate
changes, validation reads, holdout access, or execution authority belong in this campaign.
