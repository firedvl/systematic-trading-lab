# Alpaca risk-managed momentum training v6

## Predeclared design

This training-only campaign tests one allocation change on the existing complete-session
portfolio boundary. Eligible ETFs have a positive close-to-126-session return. The strategy
rebalances every five sessions, weights eligible ETFs by inverse 63-session sample volatility,
caps each target at 40%, and leaves unused weight in cash.

The fixed cap is a diversification invariant, not an estimated parameter. It is twice the
five-asset equal weight and requires at least three eligible assets for full investment. An
eligible asset with zero measured volatility fails the run instead of receiving an undefined
weight.

## Sealed plan

- Dataset ID: `508c606884112c92402707c30b56fc9d8c07cfc1c01c64f8538a6494888eeeca`
- Normalized fingerprint: `4fe62ab615ae713e23926da940256b9a728db39c2bc60c028df6d1136be49494`
- Universe: `liquid-etfs-v1`, fingerprint `cb0827988973c61362f2014c3f20fde53081217a32fa70f04a5a9e1a48b01985`
- Split: training only, 2020-07-27 through 2022-12-30 inclusive
- Search budget: four records
- Benchmark: fixed weight
- Base: lookback 126, volatility window 63, rebalance interval 5
- Neighbors: lookback 84 and 168; all other values fixed

The campaign stops before validation unless the base has positive after-cost return, beats fixed
weight, reaches a Sharpe ratio of at least 0.5, stays below 20% maximum drawdown and 50%
top-instrument profit share, records at least 100 fills, and both neighbors remain nonnegative with
at least 50% base-return retention. No gate changes, validation reads, holdout access, or execution
authority belong in this campaign.
