# Rapid-003 bounded strategy program final report

## Outcome

**AUTONOMOUS RESEARCH COMPLETE — bounded strategy universe exhausted with no
controlled-qualified candidate.**

The exposed research program is closed. A read-only disposition query classified all 1,219 parent
configurations and uniformly screened all 84 identities with three complete fixed-block rows. Five
passed the base gates; all five failed the one-parameter neighbor screen. The final cohort therefore
froze empty at research source commit `d45934bc8696a9bfc03764042d38a4872cca7267`. No controlled plan
was created, no controlled result was inspected, and no candidate may be selected from this program
for the sealed 2018–2019 independent evaluation.

This is historical simulated evidence, not a claim of future profitability.

## Identity and execution ledger

- Program: `rapid-003-bounded-strategy-discovery`.
- Starting main: `26686b3dad56fe0dc327f3fadf8a63b3c0e21348`.
- Final research source main: `d45934bc8696a9bfc03764042d38a4872cca7267`.
- Dataset: `508c606884112c92402707c30b56fc9d8c07cfc1c01c64f8538a6494888eeeca`.
- Dataset fingerprint:
  `4fe62ab615ae713e23926da940256b9a728db39c2bc60c028df6d1136be49494`.
- Allowed and observed range: `2020-07-27` through `2026-07-31`, inclusive.
- Universe: SPY, QQQ, IWM, TLT, GLD adjusted daily bars.
- Normal execution: 5/1 bps, one-bar delay.
- Stress A: 10/2 bps, two-bar delay.
- Stress B: 20/5 bps, three-bar delay.
- Parent configurations: 1,219 of the 2,000 ceiling.
- Walk-forward folds: 162.
- Stress runs: 14.
- Total Rapid rows: 1,395: 269 backtests, 932 sweeps, 18 walk-forward parents, 162 folds,
  and 14 stresses.
- Completion: 1,395 completed, zero failed, zero pending.
- Local Rapid imports: zero.

The machine-readable final ledger is
`config/research/rapid-003-strategy-ledger-v1.json`. The exact exposed screen is
`config/research/rapid-003-exposed-screen-v1.json`, SHA-256
`971e8cbb381180245b8a7660ee8bb5c908538bed1417c239707eadf415fee69b`. Its read-only parent
disposition query is `config/research/rapid-003-parent-dispositions-v1.sql`, SHA-256
`11d18522eefd4a05fffedb87654d07a71d3c77857af035ac30bf26c2a9d67a7e`.

## Git delivery

| PR | Merge commit | Purpose |
| --- | --- | --- |
| #129 | `f912621678127c1cd08996f9b92e93b26db7b9d4` | Open the bounded program and strategy ledger |
| #130 | `308d16792e8aeb97a7181f1e417cb55dd9af0a60` | Add the missing strategy families |
| #131 | `d45934bc8696a9bfc03764042d38a4872cca7267` | Add diversified defensive dual momentum |

The annotated Git tag `rapid-003-closeout-v1` is the canonical post-merge attestation. It points to
the exact merged closeout main and records the closeout PR and merge SHA, final report, ledger,
screen, disposition query, and Rapid database SHA-256 values, exact open-PR and local/remote branch
counts, and the protected-state confirmations. A tag avoids the recursive requirement for a committed file to
contain the hash of the commit that contains that file. All merged Rapid branches are deleted from
the remote.

## Benchmarks

Full exposed-range Normal results:

| Benchmark | Return | Sharpe | Drawdown |
| --- | ---: | ---: | ---: |
| Cash | 0.00% | — | 0.0% |
| QQQ buy and hold | 174.97% | 0.858 | 35.0% |
| SPY buy and hold | 151.26% | 1.010 | 24.5% |
| Strategic allocation, 21 sessions | 145.20% | 0.975 | 25.7% |
| Fixed weight | 85.25% | 0.835 | 25.8% |

Nine-fold rolling walk-forward baselines, using 252 training, 126 test, and 126 step sessions:

| Benchmark | Compounded out-of-sample return |
| --- | ---: |
| QQQ buy and hold | 58.83% |
| SPY buy and hold | 56.35% |
| Strategic allocation | 53.67% |
| Fixed weight | 46.93% |

The fixed prospective exposed blocks were selected before candidate block results:

1. `2020-07-27..2022-07-25`, 503 sessions.
2. `2022-07-26..2024-07-26`, 504 sessions.
3. `2024-07-29..2026-07-31`, 504 sessions.

Fixed-weight returns were 4.67%, 28.58%, and 36.96%. Strategic-allocation returns were 18.32%,
42.52%, and 45.82%.

## Family dispositions

| ID | Family | Evidence | Disposition |
| --- | --- | --- | --- |
| A | Absolute momentum | Momentum and multi-horizon grids; 2 multi-horizon walk-forward parents | Rejected: benchmark-inferior or unstable; Rapid-002 remains closed rejected |
| B | Relative strength | 67 parents, 9 folds | Rejected: 49.95% walk-forward return, losing folds, and concentration weakness |
| C | Dual momentum | 671 parents across original and diversified defense; 54 folds; 8 stresses | Rejected: fill, concentration, benchmark, or neighbor failures |
| D | Trend following | 14 moving-average parents | Rejected: benchmark-inferior |
| E | Breakout | 12 channel parents | Rejected: weak and cost-sensitive |
| F | Pullback / mean reversion | 23 parents | Rejected: weak or cost-dominated |
| G | Volatility management | 24 volatility parents plus closed Rapid-002 evidence | Rejected: inadequate benchmark-relative value |
| H | Risk parity / diversification | 18 inverse-volatility parents | Rejected: benchmark-inferior; optimizer complexity unjustified |
| I | Risk-on / risk-off regimes | 247 parents, 36 folds, 6 stresses | Rejected: strongest points failed activity, Sharpe, or benchmark gates |
| J | Defensive rotation | Original and diversified dual-momentum fallback | Rejected: diversification reduced concentration but not parameter fragility |
| K | Tactical asset allocation | Dual and multi-horizon active subsets | Rejected: no complete gate pass |
| L | Multi-horizon signals | 78 multi-horizon parents plus dual-family evidence | Rejected: weak standalone walk-forward; dual variants failed later gates |
| M | Signal + regime combinations | Dual, regime, and trend-pullback rules | Rejected: no interpretable combination cleared all gates |
| N | Drawdown-aware exposure | 48 parents | Rejected: materially benchmark-inferior |
| O | Cash / defensive filters | Positive filters across momentum, relative strength, and dual families | Rejected: drawdown gains did not clear the complete gate set |
| P | Diversification-constrained momentum | Equal-weight top-2/top-3 variants | Rejected: visible-base survivors failed neighbor retention |

No additional family was added after diversified defense. Remaining failures were tradeoffs among
activity, concentration, benchmark wins, and parameter stability—not evidence of a missing distinct
economic hypothesis.

## Strongest representative by family

These are research rows, not controlled results. Families can share a row when one strategy tests
more than one listed hypothesis.

| ID | Representative configuration | Source run | Key evidence | Rejection |
| --- | --- | --- | --- | --- |
| A | Multi-horizon `63/126/top-2/21` | `rr-f159d5240ce8e0634471` | 109.54% full-range return | Below SPY and QQQ; no stable benchmark edge |
| B | Relative strength `126/top-2/10` | `rr-9bd14fbe260564f6c9f4` | 49.95% walk-forward return | Worst fold -8.28%; below SPY walk-forward |
| C | Dual `63/126/top-2/21` | `rr-0f927ace28d67a69e39c` | 81.19% walk-forward return | Worst fold -2.36%; 49 walk-forward fills |
| D | Moving average `40` | `rr-2b4be9364690ff17a6a5` | 41.53% full-range return | Below 85.25% fixed weight |
| E | Channel breakout `40/20` | `rr-30b0f53e10a75d212c02` | 31.34% return; 0.650 Sharpe | Below fixed weight; turnover 30.44 |
| F | Mean reversion `15` | `rr-9ff1f819dfd167b605dd` | 34.00% full-range return | Turnover 255.72; below fixed weight |
| G | Volatility targeted `40` | `rr-4643881bb34f20783883` | 87.08% return; 0.854 Sharpe | Drawdown 25.38% exceeded 20% screen cap |
| H | Volatility balanced `40/21` | `rr-a5827cbdc29a7b4bb0d7` | 81.19% return; 0.884 Sharpe | Below fixed weight; drawdown 24.89% |
| I | Regime `84/30/15/21` | `rr-26499bcd7ae3777beb6e` | 94.26% walk-forward; all folds positive | 63 walk-forward fills; fixed-block activity gate failed |
| J | Diversified dual `25/63/top-3/21` | `rr-ab32f7bb4c5849aab945`, `rr-9dea989badde7c24af83` | Best minimum neighbor retention: 39.07% | Below 50% neighbor threshold |
| K | Dual `63/126/top-2/21` | `rr-0f927ace28d67a69e39c` | 81.19% walk-forward return | Negative worst fold and inadequate activity |
| L | Multi-horizon `63/126/top-2/21` | `rr-f159d5240ce8e0634471` | 109.54% return; 0.994 Sharpe | Below SPY and QQQ; turnover 39.89 |
| M | Regime `84/30/15/21` | `rr-26499bcd7ae3777beb6e` | 94.26% walk-forward return | Fixed-block worst Sharpe 0.415 and 67 fills |
| N | Drawdown-aware `63/15/10` | `rr-4ef483dded345156cbe8` | 130.26% full-range return | Drawdown 28.45%; only 9 fills |
| O | Dual `5/50/top-3/21` | `rr-42051424928fc8745008`, `rr-1b0081473d7868a8596e` | Uniform minimum neighbor retention: 29.37% | Below 50% neighbor threshold |
| P | Diversified dual `25/63/top-3/21` | `rr-ab32f7bb4c5849aab945`, `rr-9dea989badde7c24af83` | Best minimum neighbor retention: 39.07% | Below 50% neighbor threshold |

## Strongest evidence and failed gates

The strongest research results were not qualification results.

| Candidate | Full return / Sharpe / drawdown | Walk-forward | Stress finding | Final rejection |
| --- | --- | --- | --- | --- |
| Dual `5/63/top-1/21` | 182.84% / 1.190 / 17.7% | 78.59% | Stress B 159.86%, positive | Fixed wins 1/3, worst Sharpe 0.472, max instrument concentration 91.5%, 68 fills |
| Dual `63/126/top-2/21` | 123.53% / 1.007 / 12.4% | 81.19% | Stress B 116.07%, 94.0% retention | Max instrument concentration 58.6%; 50 fills |
| Regime `84/30/15/21` | 103.07% / 1.031 / 10.2% | 94.26%; all 9 folds positive | Stress A 94.26%, Stress B 106.97% | Worst fixed-block Sharpe 0.415; 67 fills |
| Regime `63/20/20/21` | 114.50% / 0.967 / 16.7% | 74.95% | Stress A 102.36%, Stress B 102.74% | 62 fills; every other visible base gate passed |
| Dual `5/50/top-3/21` | 81.97% / 0.828 / 18.4% | Not advanced | Not advanced | Visible base passed; long-55 retained 47.2% full range and the uniform fixed-block minimum was 29.4% |
| Regime `40/20/20/21` | Screened in fixed blocks | Not advanced | Not advanced | 96 fills; the 100-fill floor remained unchanged |

The uniform closeout screen found five visible-base passes across all 84 complete identities:

| Candidate | Visible base | Minimum fixed-fold neighbor retention | Disposition |
| --- | --- | ---: | --- |
| Dual `5/50/top-3/21` | Passed | 29.4% | Rejected |
| Diversified dual `20/84/top-2/15` | Passed | -43.4% | Rejected |
| Diversified dual `20/63/top-3/21` | Passed | 12.9% | Rejected |
| Diversified dual `25/63/top-3/21` | Passed | 39.1% | Rejected |
| Diversified dual `10/63/top-2/21` | Passed | -9.9% | Rejected |

The fixed parameter grids and source rows existed before closeout. The uniform query selects every
complete same-strategy, same-commit identity that differs from a base pass in exactly one parameter;
it cannot narrow or substitute a neighbor after seeing results. The versioned screen records every
comparison and threshold, and the query emits every parent disposition and source run ID.

## Turnover, cost, concentration, and robustness

- Slow strategic allocation remained difficult to beat: 145.20% full-range return with turnover
  3.05.
- The strongest dual point returned more, but full-range turnover was 137.99 and its fixed evidence
  was too concentrated and inactive.
- All seven dual/regime stress pairs remained profitable under Stress A and Stress B. Stress
  resilience therefore did not rescue candidates that failed base or neighbor gates.
- Diversified TLT/GLD fallback materially lowered many full-range concentration readings into the
  30%–45% range. It did not create a parameter plateau.
- The strongest regime points had low drawdown and favorable stress behavior, but their state-change
  design could not reach the unchanged 100-fill gate without post-hoc redesign.
- No gate was weakened and no parameter was retuned to force a threshold pass.

## Frozen cohort and controlled qualification

- Final cohort: empty.
- Frozen candidates and parameters: none.
- Controlled plan IDs or fingerprints: none.
- Controlled qualification attempts: zero.
- Controlled results inspected: false.
- Successful qualification fingerprints: none.
- Qualified-survivor ranking: none.
- Recommended candidate for independent evaluation: none.
- Runner-up for independent evaluation: none.

An empty cohort is deliberate. Every otherwise plausible candidate had a known disqualifying exposed
gate. Building a controlled bridge and replaying a known failure would add infrastructure and
evidence volume without creating a deserving promotion candidate.

## Protected-state audit

The final Rapid database audit found:

- one dataset ID and one dataset fingerprint, both exactly the allowed values;
- minimum start `2020-07-27T00:00:00Z` and maximum end `2026-07-31T00:00:00Z`;
- zero out-of-bounds rows;
- zero rows overlapping `2018-01-02..2019-12-31`;
- zero rows overlapping V3 `2026-10-01..2027-04-15`;
- zero local Rapid imports;
- an audited operator command record with no acquisition, local-import, or data-validation command;
- a Git-scope audit with no controlled, PAPER, broker, live, V3, or `strategic-allocation-21`
  mutation.

The 2018–2019 range remains unopened. V3 remains untouched. PAPER, broker, and live state remain
untouched. The existing `strategic-allocation-21` position remains untouched. The Rapid database
proves the row-level range and dataset claims. The broader no-command and no-mutation claims rest on
the operational and Git audits. The generic public CLI does not itself enforce the Rapid-003
2018–2019 seal; the operator therefore used only exact catalog-bound commands for the named dataset
and allowed range.

## Stop condition

Rapid-003 is closed. Do not reopen it from these results, narrow failed neighbor sets, retry
Rapid-002, or access the independent range. A future program requires a separately reviewed new
hypothesis and cannot reinterpret this closed evidence.
