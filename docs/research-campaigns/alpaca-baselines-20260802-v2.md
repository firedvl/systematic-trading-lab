# Alpaca baseline walk-forward v2

## Outcome

This campaign collected provider-data evidence. It did not qualify a strategy. The fixed-weight baseline earned a higher total return than both trend baselines in each validation year. No holdout data was accessed, and the 2026 dataset segment remains untouched.

## Sealed input

- Dataset ID: `508c606884112c92402707c30b56fc9d8c07cfc1c01c64f8538a6494888eeeca`
- Normalized fingerprint: `4fe62ab615ae713e23926da940256b9a728db39c2bc60c028df6d1136be49494`
- Provider: `alpaca-historical-v2`, IEX feed, `provider-adjusted-all-v1`
- Universe: `liquid-etfs-v1`, fingerprint `cb0827988973c61362f2014c3f20fde53081217a32fa70f04a5a9e1a48b01985`
- Range: 2020-07-27 through 2026-07-31
- Bars: 7,555; raw, normalized, manifest, and catalog checks passed
- Campaign code commit: `fec8b68e92abed6eceaeb5021f1f89bb8dd229c0`

The installed XNYS calendar rejects dates before 2006-08-02. The available IEX history did not provide complete common coverage before 2020-07-27. Both broader requests failed closed and created quarantine evidence; neither published a dataset.

## Method

The campaign used the default 20-session moving-average and momentum baselines. It did not search parameters. Each strategy split active exposure equally across the five dataset symbols. The campaign recorded 22 candidates against a budget of 25; all completed.

| Fold | Training range | Validation range |
| --- | --- | --- |
| 1 | 2020-07-27 to 2022-12-30 | 2023-01-03 to 2023-12-29 |
| 2 | 2021-01-04 to 2023-12-29 | 2024-01-02 to 2024-12-31 |
| 3 | 2022-01-03 to 2024-12-31 | 2025-01-02 to 2025-12-31 |

## Validation evidence

Returns and drawdowns are decimal fractions after the versioned five-basis-point slippage and one-basis-point commission assumptions.

| Fold | Candidate | Total return | Max drawdown | Trades |
| --- | --- | ---: | ---: | ---: |
| 1 | Cash | 0 | 0 | 0 |
| 1 | Fixed weight | 0.205883 | 0.108566 | 233 |
| 1 | Moving average | 0.084334 | 0.053631 | 702 |
| 1 | Momentum | 0.054175 | 0.066335 | 675 |
| 2 | Cash | 0 | 0 | 0 |
| 2 | Fixed weight | 0.177296 | 0.063820 | 245 |
| 2 | Moving average | 0.004977 | 0.046217 | 821 |
| 2 | Momentum | 0.072648 | 0.065949 | 832 |
| 3 | Cash | 0 | 0 | 0 |
| 3 | Fixed weight | 0.224596 | 0.128706 | 220 |
| 3 | Moving average | 0.104700 | 0.053130 | 826 |
| 3 | Momentum | 0.156053 | 0.038928 | 810 |

The doubled-cost variants reduced the fold-three moving-average return from 0.104700 to 0.085149 and momentum from 0.156053 to 0.142569. The two-bar-delay variants returned 0.124388 and 0.159301, respectively. A favorable delay result is not evidence of execution benefit; it remains a separate sensitivity outcome.

## Superseded campaign

`alpaca-baselines-20260802-v1` also retains 22 completed records. Its trend strategies emitted a full-portfolio target for each symbol, which caused symbol-order cash contention. The campaign is invalid for financial comparison and remains in the registry as failed-method evidence. It was not deleted or relabeled as qualification evidence.

## Remaining gates

At campaign time, the metrics did not cover risk-adjusted return, exposure, profit concentration, market regimes, or parameter neighborhoods, and financial thresholds were unapproved. Those historical gaps blocked qualification and controlled holdout evaluation. Later campaigns added the metrics, and the policy was approved without qualifying these candidates.
