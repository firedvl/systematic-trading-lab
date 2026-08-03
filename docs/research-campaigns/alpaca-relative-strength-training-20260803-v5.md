# Alpaca relative-strength portfolio training v5

## Outcome

This training-only campaign completed all four recorded runs. The 126-session base and
168-session neighbor beat the fixed-weight training return and reduced drawdown, but the
family produced weak risk-adjusted returns and too few trades to justify validation. The
84-session neighbor lost money. No 2023–2026 bars or holdout metrics were read.

## Sealed input and boundary

- Dataset ID: `508c606884112c92402707c30b56fc9d8c07cfc1c01c64f8538a6494888eeeca`
- Normalized fingerprint: `4fe62ab615ae713e23926da940256b9a728db39c2bc60c028df6d1136be49494`
- Universe: `liquid-etfs-v1`, fingerprint `cb0827988973c61362f2014c3f20fde53081217a32fa70f04a5a9e1a48b01985`
- Campaign: `m3-relative-strength-v1`
- Campaign code commit: `51e0f44689c89bbc400129e906189b358941d6e0`
- Split: training only, 2020-07-27 through 2022-12-30 inclusive
- Search budget: four; four records created and completed

The bounded cataloged runner used a Parquet predicate for the recorded training range. It
did not load the rest of the dataset.

## Predeclared candidates

The strategy ranks close-to-lookback returns once every 21 sessions, assigns one-third
weight to each of the top three assets with positive momentum, and leaves unused weight in
cash. The campaign recorded one fixed-weight benchmark, the 126-session base candidate,
and 84- and 168-session neighbors.

| Record | Lookback | Total return | Max drawdown | Sharpe | Average exposure | Turnover | Trades | Top-instrument share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `m3-rs-fixed-weight-training` | — | -0.001359 | 0.257724 | 0.069103 | 0.994784 | 2.675129 | 557 | 0.436930 |
| `m3-rs-lookback-84-training` | 84 | -0.019831 | 0.230577 | -0.005093 | 0.618058 | 10.846181 | 69 | 0.803545 |
| `m3-rs-lookback-126-training` | 126 | 0.017025 | 0.155378 | 0.119688 | 0.514689 | 5.499352 | 53 | 0.691146 |
| `m3-rs-lookback-168-training` | 168 | 0.025127 | 0.150061 | 0.161472 | 0.455599 | 3.653259 | 45 | 0.403788 |

## Decision

Do not run this family on validation or holdout data. The 168-session neighbor led the
family, but a 0.161472 training Sharpe ratio and 45 trades across the full period do not
support opening another data split. The 126-session base also exceeded the proposed 0.50
instrument-profit concentration cap. At campaign time the proposal was unapproved and was used
only as an adverse design check, not as qualification authority. Its later approval does not reopen
this family or create missing validation evidence.

The trade-count gate was reviewed separately and approved on a campaign-wide basis. Do not alter
it or any other gate to admit these results.

## Report fingerprints

- Comparison: `a13aff867fb3583ebc583a9d2f5f5aac9ebbbe93111e3797a3db02f4e09fb23b`
- Fixed weight: `4200053b1c94f8fcfac0ae0b9c8dcb1721c61d5e07e6a38607b3992a9e776f41`
- Relative strength 84: `e4927036416432804d24182fb6920dd9866c371d5175d521b5662f51170889ae`
- Relative strength 126: `339eb953482e80bd89fc61af7316d120d2de81bae4a867933323cf4adb53b9f7`
- Relative strength 168: `da1769d9f702c06cecf501558fa644a3645041572d7359e6ad76f8ece9630b4e`

The reports and registry remain in ignored local runtime storage. This document names every
campaign record and preserves the evidence used to stop before validation.
