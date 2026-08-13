# Intraday Campaign V2 postmortem

Status: closed immutable failed research evidence.

Campaign: `intraday-research-v2`

Plan fingerprint: `52db8a27fa4ff86865ab69b6bd7456899329ef3b861a582e59ab32904c03c122`

Reported diagnostic export SHA-256: `f02cbb3dbb65859e085a2a73f2f062d1a43031acef6862c8a42dd2e47791fdaf`

This postmortem does not change the V2 plan, source review, datasets, candidate reports,
qualification evidence, or execution semantics. V2 remains valid failed evidence under its frozen
contracts. It grants no protected holdout, paper, broker-write, or live authority.

## Evidence boundary

The campaign closeout supplied for this review reports 60 completed controlled historical
candidates, 60 execution-source bindings, one immutable source review, and 12 failed base
qualification groups. It reports no holdout access or authorization.

This repository checkout contains the frozen plan and the code that produced V2 semantics. It does
not contain the diagnostic export named above. This review therefore records the supplied digest and
metrics but did not rehash the export or recompute market-data results. The code mechanics and
existing tests were inspected independently.

## Observed facts

The following values are reported campaign evidence, not recomputed results.

| Strategy and period | Net return | Recorded costs | Turnover | Round trips | Fills |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1-bar momentum, Training | -0.9505837285 | 95,913.9270 | 1,598.5654 | 12,022 | 13,274 |
| 1-bar momentum, Validation A | -0.6104212908 | 60,027.0230 | 1,000.4504 | — | — |
| 1-bar momentum, Validation B | -0.6075123055 | 64,475.1888 | 1,074.5865 | — | — |
| 1-bar momentum, Validation C | -0.6199354954 | 62,034.5090 | 1,033.9085 | — | — |
| 12-bar MA trend, Training | -0.6333446542 | 63,290.1164 | 1,054.8353 | 6,900 | 7,462 |
| 12-bar MA trend, Validation A | -0.2395939571 | 25,290.1888 | 421.5031 | — | — |
| 12-bar MA trend, Validation B | -0.2427188349 | 26,665.2478 | 444.4208 | — | — |
| 12-bar MA trend, Validation C | -0.2748356942 | 26,316.0051 | 438.6001 | — | — |

Initial cash was 100,000. All 12 base strategy-period groups failed the unchanged
`intraday-qualification-policy-v1` research gates. No protected holdout was opened.

The V2 delay variants with two- and three-bar fill delays materially reduced turnover and improved
returns relative to their intended one-bar baseline stress. This is an observed relationship, not
evidence that slower execution improves the strategy.

## Derived diagnostics

Adding recorded transaction costs back to net P&L gives the following approximate returns:

| Strategy | Training | Validation A | Validation B | Validation C |
| --- | ---: | ---: | ---: | ---: |
| 1-bar momentum | +0.86% | -1.02% | +3.72% | +0.04% |
| 12-bar MA trend | -0.04% | +1.33% | +2.39% | -1.17% |

This arithmetic is not a zero-cost replay. Costs change cash, equity, and later target quantities, so
adding them back cannot reconstruct the counterfactual sizing path. It is diagnostic evidence that
the recorded losses are close in scale to recorded costs.

## Confirmed implementation mechanics

The code confirms the proposed mechanism:

1. `IntradayMomentumPortfolioStrategy` and
   `IntradayMovingAverageTrendPortfolioStrategy` return a complete SPY/QQQ target set after warm-up
   on every completed five-minute slice. Each symbol receives an exact weight of 0 or 0.5.
2. `BacktestEngine.run_portfolio` invokes the strategy and records a `SessionDecision` on every
   complete slice. When no order is pending, it schedules every returned target without comparing it
   with the prior desired state.
3. `BacktestEngine._execute` calculates the desired quantity from equity, the target weight, and the
   fill-time market price. A repeated 0.5 target can therefore buy or sell a small amount after price,
   equity, or the other symbol's value changes.
4. A pending order for either target symbol makes `_portfolio_rejection` reject the complete target
   set as `pending-order-exists`.
5. `execution_delay_bars` chooses a later same-symbol bar. A longer delay leaves an order pending for
   more completed slices, so the strategy is still evaluated but fewer target sets are accepted for
   scheduling.

The delay stress therefore changes both application latency and accepted target-application cadence.
It is not a clean latency-only stress under `deterministic-next-bar-open-v1`.

The V2 close controller remains causal and fail-closed. It cancels unsafe pending work, creates a
zero-weight target early enough to fill at the final validated session-bar open, rejects late positive
targets, requires complete XNYS sessions, and errors if exposure or a pending order survives a normal
or early close.

## Hypotheses and inferences

The strongest supported inference is that implicit exact-weight rebalancing and its transaction costs
were the dominant V2 failure mechanism. The very high turnover and fill counts, costs close to net
losses, and improvement when pending orders suppress more target applications all point in the same
direction.

This does not establish the exact fraction of loss caused by costs. It also does not establish a
profitable pre-cost signal. The approximate cost add-back ranges from negative to positive across
periods and does not preserve the actual counterfactual sizing path.

## Limitations

- The diagnostic export was not available in this checkout for independent hash or row-level review.
- V2 did not run an exact paired zero-cost counterfactual.
- The delayed variants confound latency with target-application cadence.
- Bar replay does not model quotes, queue position, spread paths, partial fills, market impact, halts,
  or network latency.
- Results cover the fixed SPY/QQQ five-minute data, dates, strategies, costs, and execution contracts.
  They do not establish behavior outside that scope.
- No holdout was inspected, so V2 provides no protected out-of-sample evidence.

## What V2 proved

V2 proved that the frozen candidates failed all 12 base research qualification groups under the
recorded V2 data, exact-weight target execution, costs, and gates. It also exposed a material design
defect in the interpretation of delay stress: longer delays suppressed accepted target applications.
The campaign preserved search accounting, source binding, immutable failure evidence, and the
holdout boundary.

## What V2 did not prove

V2 did not prove that either underlying signal has no predictive information, that slower execution
is beneficial, that a zero-cost version is profitable, or that a V3 strategy will pass. It did not
authorize threshold changes, parameter selection from the observed periods, protected holdout access,
paper execution, broker writes, or live trading.

## Disposition

Keep every V2 artifact and contract immutable. Reproduce V2 only from its exact reviewed source and
runtime evidence. New work uses separate V3 strategy, execution, experiment, report, queue, session,
and diagnostic IDs. All dates from 2025-07-01 through 2026-06-30 are exposed development evidence for
future period selection.
