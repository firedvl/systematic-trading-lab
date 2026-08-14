# Rapid-002 risk-managed momentum promotion design

## Status and authority

This document freezes the proposed controlled path for Rapid export
`rr-a480ff073a90e448c8b2`. It does not create an experiment, qualification,
holdout authorization, paper authorization, activation, process opt-in, broker request, or V3
record.

The candidate fingerprint is
`1efe7aa4043fd6dcab7e34025e70b1a45c03a5d2ca6e15f520af3ef9a4742bf9`.
Every authority field in the Rapid export remains false.

The executable control path was merged and run from exact main
`b7bf03786373ba92cf5e2741b744051dcff46833`. Campaign
`rapid-002-rmm-40-40-10-controlled-v1` sealed plan fingerprint
`dd1fe1a313ddd74b34405cb1d5d7d284157e3372180646f63862cebc0e8afd0e` and completed
all 28 reservations once. Controlled qualification rejected the candidate. This result grants no
independent-evaluation, holdout, paper, broker, live, or V3 authority.

## Frozen candidate

- Strategy: `risk-managed-momentum-portfolio`, version `1`.
- Parameters: `lookback=40`, `volatility_window=40`, `rebalance_every=10`.
- Symbols: SPY, QQQ, IWM, TLT, GLD.
- Initial cash: `100000`.
- Random seed: `0`.
- Rapid source base: `07fc39e542c468cd3592f41bf13a9e1cb08ea276`.
- Rapid working-tree fingerprint:
  `fc927594a1ac7efb5cf7dadd9667c5d00b17d2cb3c380841fb22f7e0fb336d16`.
- Source-preservation commit: `3025987959057642639fed313424497217c45f44`.
- `src/systematic_trading_lab/strategies.py` SHA-256:
  `4be05a18badf460f60016f9401206d5dcf3c89ea270835991f11aae3754085af`.

Controlled records must name the reviewed main commit whose source tree includes the exact change
preserved by `3025987959057642639fed313424497217c45f44`. Before any run, that checkout must be clean,
its source diff from the Rapid base must reproduce the working-tree fingerprint above, and the
strategy file hash must still match. A changed strategy, parameter, registry mapping, simulator, cost
model, or execution model requires a new reviewed plan. Validation results cannot select a replacement
parameter.

## Controlled validation data

The validation campaign replays exposed evidence through the controlled runner. It is not the
independent evaluation.

- Dataset ID: `508c606884112c92402707c30b56fc9d8c07cfc1c01c64f8538a6494888eeeca`.
- Dataset fingerprint:
  `4fe62ab615ae713e23926da940256b9a728db39c2bc60c028df6d1136be49494`.
- Universe ID: `liquid-etfs-v1`.
- Universe fingerprint:
  `cb0827988973c61362f2014c3f20fde53081217a32fa70f04a5a9e1a48b01985`.
- Timeframe and adjustment: adjusted daily bars.
- Fold 2023: `2023-01-03T00:00:00Z` through `2023-12-29T00:00:00Z`.
- Fold 2024: `2024-01-02T00:00:00Z` through `2024-12-31T00:00:00Z`.
- Fold 2025: `2025-01-02T00:00:00Z` through `2025-12-31T00:00:00Z`.

The folds are chronological and non-overlapping. Each run loads only its declared range. The strategy
uses the first 40 sessions of each range as its deterministic warmup. No controlled result may alter
the candidate or this ledger.

## Models and benchmark

- Benchmark: `fixed-weight`, version `1`, on the same dataset and folds.
- Normal: 5 bps slippage, 1 bps commission, one-bar delay;
  `conservative-bps-v1` and `next-bar-v1`.
- Cost-isolation gate: 10 bps slippage, 2 bps commission, one-bar delay;
  `bps-10-2-v1` and `next-bar-v1`.
- Delay-isolation gate: 5 bps slippage, 1 bps commission, two-bar delay;
  `conservative-bps-v1` and `delayed-2-bars-v1`.
- Stress A: 10 bps slippage, 2 bps commission, two-bar delay;
  `bps-10-2-v1` and `delayed-2-bars-v1`.
- Stress B: 20 bps slippage, 5 bps commission, three-bar delay;
  `bps-20-5-v1` and `delayed-3-bars-v1`.

Cost and delay change the fill path. A higher stressed return is not evidence that worse execution
helps.

## Exact controlled ledger

Campaign ID: `rapid-002-rmm-40-40-10-controlled-v1`.

| Role | Experiment IDs | Count |
| --- | --- | ---: |
| Normal base | `r2-rmm-base-2023`, `r2-rmm-base-2024`, `r2-rmm-base-2025` | 3 |
| Fixed-weight benchmark | `r2-fixed-weight-2023`, `r2-fixed-weight-2024`, `r2-fixed-weight-2025` | 3 |
| Parameter neighbors | `r2-rmm-{lookback30,lookback50,volatility30,volatility50,cadence5,cadence15}-{2023,2024,2025}` | 18 |
| Isolated approved sensitivities | `r2-rmm-cost2x-2025`, `r2-rmm-delay2-2025` | 2 |
| Exact Rapid stresses | `r2-rmm-stress-a-2025`, `r2-rmm-stress-b-2025` | 2 |
| Total |  | 28 |

The brace notation denotes the full Cartesian product of the listed tags and years. No other
experiment ID belongs to the campaign.

Neighbor parameters are exact:

- `lookback30`: 30/40/10.
- `lookback50`: 50/40/10.
- `volatility30`: 40/30/10.
- `volatility50`: 40/50/10.
- `cadence5`: 40/40/5.
- `cadence15`: 40/40/15.

The notation is lookback/volatility window/rebalance cadence. Every neighbor is linked to its same-fold
base. The isolated sensitivities and exact stresses are linked to `r2-rmm-base-2025`. All 28 records,
including failures, count against the campaign budget. No rerun or replacement is allowed under the
same ID.

The candidate-specific manifest
`config/research/qualification-evidence-rapid-002-rmm-v1.json` extends the daily evidence format with
exactly two combined-stress roles. Each role must name its 2025 base parent, preserve source, strategy,
data, universe, parameters, and seed, and change both the cost and execution model to the versions
listed above. The manifest freezes all 28 experiment IDs and has fingerprint
`b997afb53fdf05ef26be72934fb3318cb582ba503f4527fa9ca96f88f7b72693`.

The existing gate engine compares one metric per gate. The two compound stress requirements below
therefore use four visible machine gates: positive return and return retention for Stress A, then the
same two checks for Stress B. All four must pass. The existing 17 gates and historical manifest
fingerprints remain unchanged. A manual summary cannot substitute for registry-backed evidence.

## Executable sealing and running

The campaign was sealed once from a clean, fetched, fast-forwarded `main` with:

```console
uv run trading-lab experiment plan-rapid-002 \
  --candidate-export .trading-lab/rapid-research/candidates/rr-a480ff073a90e448c8b2.json \
  --evidence-manifest config/research/qualification-evidence-rapid-002-rmm-v1.json \
  --proposal config/research/qualification-proposal-rapid-002-rmm-v1.json
```

The command verifies the exact candidate bytes and fingerprint, full dataset integrity and identity,
preserved source, strategy hash, manifest, and proposal before one transaction stores the plan and all
28 pending reservations. It prints the executable plan fingerprint. Run a reservation only as
`uv run trading-lab experiment run-planned EXPERIMENT_ID`; the command accepts no execution inputs.
Completion or failure is terminal. All reservations are now completed and must not be rerun.
Qualification required all 28 records and the same stored plan fingerprint.

## Controlled outcome

- Evidence fingerprint:
  `ea2ef03fd8385379442ca7e81ee512c1e8bd140ab4d6fafb2cf37ad156acaf0a`.
- Qualification report fingerprint:
  `352d105aba2a87abb19a8db06ae4fc87c3e7f45c629f75e296d36d4ebeb2adcc`.
- State: `rejected`.
- Fixed-weight benchmark wins: `0` of `3`; required at least `2` of `3`.
- Maximum base-fold instrument profit concentration:
  `0.5481303845862676475938417604`; cap `0.5`.
- Remaining machine gates: `19` passed, including both Stress A/B return and retention gates.

The independent range remains unopened. Do not retry, retune, reselect, or continue this promotion.

## Pass/fail gates

All source records must be controlled-run completions with one canonical report and one matching
SHA-256 fingerprint. Any missing, failed, substituted, or mismatched record rejects the campaign.
There is no composite score.

The existing 17 approved daily gates remain unchanged:

1. At least three validation folds.
2. Every base fold has positive return.
3. The candidate beats fixed weight in at least two of three folds.
4. Worst fold return is at least zero.
5. Worst fold Sharpe is at least 0.5.
6. Maximum fold drawdown is at most 20%.
7. Maximum average gross exposure is at most 1.
8. Maximum top-five-session profit share is at most 25%.
9. Maximum top-instrument profit share is at most 50%.
10. The isolated doubled-cost run retains at least 80% of its base return.
11. The isolated two-bar-delay run retains at least 80% of its base return.
12. Every parameter neighbor retains at least 50% of its same-fold base return.
13. Every fold contains at least 50 positive-SPY sessions.
14. Every fold contains at least 50 negative-SPY sessions.
15. Maximum fold turnover is at most 30.
16. The three base folds contain at least 100 fills in total.
17. The campaign contains at most 40 candidates.

Two candidate-specific compound stress requirements also apply:

18. Stress A return is positive and at least 80% of the 2025 normal-base return.
19. Stress B return is positive and at least 80% of the 2025 normal-base return.

`config/research/qualification-proposal-rapid-002-rmm-v1.json` records each return and retention
condition as its own approved, disqualifying gate. A zero stress return fails the strict positive
return gate.

Any failed gate rejects the candidate. Do not retune, omit a record, weaken a threshold, or use the
independent range after a controlled failure.

## One independent evaluation

Only a passing controlled campaign may request one one-use evaluation authorization. The target range
is `2018-01-02T00:00:00Z` through `2019-12-31T00:00:00Z`. It is outside the exposed daily period that
begins on 2020-07-27 and outside every V3 period. The first 40 sessions remain deterministic warmup.

Before acquiring or binding the dataset, an independent reviewer must confirm from the exposure
inventory and human records that no candidate result from this range informed the strategy or this
plan. The data must come from a read-only provider with complete adjusted daily bars for the exact
five-symbol universe. Import and full-integrity validation may record metadata and content hashes but
must not run the strategy or expose evaluation metrics.

The dataset ID, dataset fingerprint, provider/feed/adjustment identity, universe identity, exact source
commit, parameters, normal execution assumptions, range, and parent candidate must be frozen in the
one-use authorization before the runner loads bars. A dataset ID cannot be written into this design
before that artifact exists. If the exact range lacks complete data or the reviewer cannot establish
independence, stop; do not choose a favorable replacement range.

Run only 40/40/10 under Normal assumptions. Review its metrics once through a candidate-specific
approved copy of the seven existing daily holdout gates: nonnegative return, Sharpe at least 0.5,
drawdown at most 20%, average gross exposure at most 1, top-five-session profit share at most 25%,
top-instrument profit share at most 50%, and turnover at most 30. Any failure ends promotion.

Expected execution count: 28 controlled validation runs, followed by exactly one independent run only
after qualification passes; 29 maximum.

## Shortest paper path

After the one-time evaluation passes:

1. Record its reviewed qualification without changing the source, parameters, gates, or evidence.
2. Use a separate Alpaca PAPER account and candidate-specific risk configuration. Do not share or
   reinterpret the `strategic-allocation-21` account state.
3. Add one candidate-specific broker-free planner, not a new framework. It must reuse
   `RiskManagedMomentumPortfolioStrategy`, bind complete daily history and a fixed XNYS cadence epoch,
   and convert its long-only weights to whole shares with fresh attested asks.
4. Review a maximum-24-hour paper authorization that binds the qualified candidate, exact source,
   data, account, capital allocation, limits, and evidence. This step is separate from this design.
5. Build and verify the main-attested wheel, establish a fresh flat baseline on the separate account,
   collect account/position/order/bar/quote/clock evidence, and require exact replay/shadow plan
   equivalence.
6. Create a short activation and exact process opt-in only after all read-only checks pass. Obtain
   explicit user approval immediately before the first broker mutation.
7. Run one bounded paper session, then require fill lookup, settlement, reconciliation, and capacity
   release through the existing guarded path.

No prospective waiting period is added. No automatic promotion or live path exists.
