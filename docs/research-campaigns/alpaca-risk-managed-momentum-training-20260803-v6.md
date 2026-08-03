# Alpaca risk-managed momentum training v6

## Outcome

The four-record training campaign completed under code commit
`e561c60c8928c310aa31a7149665be97e4abdb57`. The 126-session base lost 6.34%, trailed
fixed-weight, had a negative Sharpe ratio, and assigned all net instrument profit to one ETF. The
168-session neighbor also lost money. The family fails the predeclared advancement screen and
stops before validation.

| Record | Lookback | Return | Sharpe | Max drawdown | Top-instrument profit share | Fills |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `m3-rmm-fixed-weight-training` | — | -0.001359 | 0.069103 | 0.257724 | 0.436930 | 557 |
| `m3-rmm-lookback-84-training` | 84 | 0.062350 | 0.283304 | 0.189912 | 0.454073 | 278 |
| `m3-rmm-lookback-126-training` | 126 | -0.063431 | -0.229125 | 0.187283 | 1.000000 | 239 |
| `m3-rmm-lookback-168-training` | 168 | -0.037064 | -0.144726 | 0.174520 | 0.618685 | 195 |

No 2023–2026 bars, validation data, or holdout results were read. The local immutable registry and
content-addressed reports retain all four records.

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
