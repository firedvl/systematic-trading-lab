# Alpaca qualification evidence v3

## Outcome

This campaign completed 34 of 34 recorded candidates under backtest report schema v2. It did not qualify a strategy. Fixed-weight earned a higher total return than the base moving-average and momentum strategies in each validation year. No holdout data was accessed, and the 2026 dataset segment remains untouched.

The campaign uses dataset `508c606884112c92402707c30b56fc9d8c07cfc1c01c64f8538a6494888eeeca`, normalized fingerprint `4fe62ab615ae713e23926da940256b9a728db39c2bc60c028df6d1136be49494`, and code commit `d0799ac9d8229d5929348e42dfba594cc30e6bba`.

## Base validation evidence

| Year | Candidate | Total return | Max drawdown | Sharpe | Average exposure | Top-five-session share | Top-instrument share |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2023 | Fixed weight | 0.205883 | 0.106320 | 1.752441 | 0.993124 | 0.130645 | 0.464620 |
| 2023 | Moving average | 0.084334 | 0.052912 | 1.123689 | 0.527838 | 0.187639 | 0.596930 |
| 2023 | Momentum | 0.054175 | 0.064304 | 0.760667 | 0.520681 | 0.184524 | 0.501365 |
| 2024 | Fixed weight | 0.177296 | 0.063820 | 1.514513 | 0.993290 | 0.102352 | 0.292066 |
| 2024 | Moving average | 0.004977 | 0.045882 | 0.102137 | 0.605247 | 0.151694 | 0.433805 |
| 2024 | Momentum | 0.072648 | 0.065849 | 0.849787 | 0.638558 | 0.120090 | 0.349187 |
| 2025 | Fixed weight | 0.224596 | 0.126865 | 1.577437 | 0.993417 | 0.159111 | 0.472880 |
| 2025 | Moving average | 0.104700 | 0.051770 | 1.418001 | 0.628449 | 0.144956 | 0.390083 |
| 2025 | Momentum | 0.156053 | 0.038560 | 1.992722 | 0.636266 | 0.153963 | 0.391232 |

Positive SPY sessions and negative SPY sessions both occurred in every fold. The reports retain separate compounded strategy returns for those regimes. A negative down-regime return is descriptive evidence, not an approved failure threshold.

## Parameter neighborhoods

The 20-session base parameters were not changed. The campaign ran 15- and 25-session neighbors as linked validation sensitivity candidates.

| Year | Moving-average return range | Momentum return range |
| --- | ---: | ---: |
| 2023 | 0.056811 to 0.102188 | 0.054175 to 0.102043 |
| 2024 | 0.004977 to 0.030305 | 0.010709 to 0.072648 |
| 2025 | 0.086581 to 0.128745 | 0.092597 to 0.156053 |

All neighbors remained positive, but the ranges show material parameter dependence. In 2024, 15-session momentum returned 0.010709 versus 0.072648 for the base. Validation results cannot select a replacement parameter.

## Cost and delay evidence

For the 2025 fold, doubled costs reduced moving-average return from 0.104700 to 0.085149 and momentum from 0.156053 to 0.142569. Two-bar delay returned 0.124388 and 0.159301, respectively. Favorable delay outcomes remain separate evidence and do not prove an execution advantage.

## Remaining decision

Financial gates remain unapproved. A reviewer must approve explicit benchmark, drawdown, Sharpe, exposure, concentration, cost, delay, parameter-neighborhood, regime-coverage, trade-count, turnover, and search-volume thresholds before any controlled holdout run.

## Registry-backed reproduction

`config/research/qualification-evidence-v3.json` now names every registry record used by the gate evaluation. The evaluator reproduced the documented aggregate values without loading market data. It wrote local content-addressed report `qualification-00042a45089801dc5c5b64aa7540028244537692150a253b184e3d67732968d6.json` with candidate evidence fingerprints `4dec55fa1f83f13b253c7327e4ad33c579baf2503e26f16dbd8b1cf0ad1ce8ec` for moving average and `e2646c4aa03c4afa93892f8f744541a84977981718aac207ccf04d24eb28fe2f` for momentum. Both states remain `unapproved`, with the same four and three failed gates listed above. The report stays in ignored runtime storage; the committed manifest and registry records reproduce it.
