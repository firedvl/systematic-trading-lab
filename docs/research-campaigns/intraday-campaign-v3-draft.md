# Intraday Campaign V3 draft

Status: development-only draft; not preregistered, sealed, bound, source-reviewed, or executable as a
campaign.

Draft ID: `intraday-research-v3`

Draft contract: `config/research/intraday-campaign-v3-draft.json`

This draft grants no research qualification, protected holdout, paper, broker-write, or live
authority. Do not run historical V3 candidates from it.

## Execution contracts

V3 uses new IDs and does not change `deterministic-next-bar-open-v1`,
`completed-bar-next-bar-open-v1`, `intraday-experiment-v1`, or
`intraday-backtest-report-v1`.

- experiment: `intraday-experiment-v2`;
- report: `intraday-backtest-report-v2`;
- execution: `state-transition-delayed-fifo-v1`;
- earliest fill: `completed-bar-nth-later-open-v1`;
- queue: `fifo-no-supersession-session-close-override-v1`;
- session: `XNYS-regular-session-state-transition-flat-v2`;
- periodic rebalance: `none-v1`;
- diagnostic: `paired-exact-zero-cost-counterfactual-v1`;
- initial cash: `100000`.

Each completed five-minute SPY/QQQ slice produces one full desired-state evaluation. A symbol state is
cash or 0.5 weight. The engine compares that state with the prior desired state for the same session.
An unchanged state creates no order. A changed state enters a FIFO queue and applies at the Nth later
same-session bar open. Later changes create later queue entries; an earlier pending transition never
suppresses evaluation or discards them. If a queued target is already realized when applied, the
engine records a deterministic no-op.

At the session-close cutoff, the close controller records and cancels remaining queued transitions,
records later strategy changes as rejected, and schedules any required zero-state transition for the
final validated session-bar open. It then fails if a position, logical long state, or queued transition
survives the final normal or early-close bar. This close override is the only supersession rule.

Entries calculate the 0.5 quantity once at their fill. Exits close the held quantity. Price drift in
an unchanged long state does not rebalance it. V3 supports no periodic rebalance. Adding one requires a
new reviewed policy ID, interval, deterministic schedule, provenance field, and separate report count.

## Fixed strategies

All strategies are long-only, unlevered, SPY/QQQ, and fixed before any V3 validation selection.

1. `intraday-event-driven-ma-trend` version 1 uses the V2 12-bar rule unchanged: a symbol is long when
   its current completed close is strictly above the average of the latest 12 completed closes. It
   uses V3 state-transition execution.
2. `intraday-30-minute-momentum` version 1 is long when the current completed close is strictly above
   the completed close six five-minute bars earlier. History can cross the prior session, as in the V2
   history contract, but every new session starts from an enforced cash state.
3. `intraday-30-minute-opening-range-breakout` version 1 defines the range from the high and low of the
   first six completed regular-session bars. It cannot enter on those six bars. On a later completed
   bar, a close strictly above the opening-range high changes the desired state to 0.5. That state is
   held until mandatory close flattening. Each symbol can therefore enter at most once per session and
   never re-enters. A qualifying decision fills at the configured Nth later regular-session bar open;
   a late decision that cannot meet close safety is recorded and rejected.

No parameter search or neighbor is authorized.

## Diagnostic decomposition

The V3 diagnostic runs two exact replays on identical bars with identical desired-state decisions,
FIFO delay, and close semantics:

- the realistic reviewed cost model; and
- `zero-cost-counterfactual-v1`, with zero slippage and commission.

The report checks that both semantic traces match and fingerprints the pair. It reports realistic net
return, zero-cost diagnostic return, their signed difference, paid costs, turnover and turnover per
session, fills and round trips per session, desired-state evaluations and changes, executed
transitions, canceled/rejected/no-op transitions, and periodic rebalances. The zero-cost result is a
diagnostic only. It cannot replace realistic-cost qualification evidence. Report construction
rechecks the exact experiment timestamp range, full ordered-bar content fingerprint, both result
fingerprints, and paired semantic-trace fingerprint before writing immutable evidence. A future
controlled runner must also resolve the declared dataset and universe identities through the catalog.

`intraday-qualification-policy-v1` thresholds remain unchanged. The existing v1 evaluator rejects the
V3 report schema. A separate reviewed V3 qualification contract must bind the unchanged thresholds to
realistic V3 metrics before preregistration. No turnover gate is active or proposed in this draft.

## Draft candidate matrix

The draft contains three active strategies, four roles, and five variants per strategy-role pair:

| Variant | Slippage bps | Commission bps | FIFO delay |
| --- | ---: | ---: | ---: |
| base | 5 | 1 | 1 bar |
| increased-cost | 10 | 2 | 1 bar |
| harsher-cost | 20 | 5 | 1 bar |
| plus-1-bar | 5 | 1 | 2 bars |
| plus-2-bars | 5 | 1 | 3 bars |

The fixed budget is `3 × 4 × 5 = 60`. Cash remains a non-budget software sanity test. The period roles
are Training and Validation A/B/C, but every date is intentionally unselected.

## Period selection

All V2 dates from 2025-07-01 through 2026-06-30 are exposed development evidence. The draft parser
requires that declaration. The candidate-period validator checks exact XNYS bounds, chronological
non-overlap, and rejects a validation period that overlaps any declared exposed range. It returns
`candidate-selection-requires-independent-review`; passing the check does not certify that a period is
unobserved.

Before selecting dates, review all campaign records, reports, notebooks, local exports, issue and PR
discussion, and any other human-observed intraday results. Update the exposure declaration with every
discovered window. Prefer forward validation. Then obtain independent human review of the exposure
inventory and proposed dates. Do not infer freshness from a date being absent from this file.

## Source and dataset prerequisites

The V2 49-module manifest stays immutable and excludes V3. A future V3 manifest must cover the whole
application package by exact bytes and must include `systematic_trading_lab/intraday_v3.py`. Before
candidate 1, V3 still requires merged reviewed source, a main-attested wheel, exact dependency and
runtime closure, source assessment, explicit human review, an immutable source review, independently
acquired and validated period datasets, and atomic binding of all 60 reservations.

Remaining blockers before preregistration:

1. independently reviewed exposed-window inventory and exact Training/Validation dates;
2. reviewed V3 qualification/report binding that retains the v1 thresholds and excludes zero-cost
   metrics from gates;
3. reviewed final source commit and whole-package source manifest;
4. main-attested wheel and exact locked runtime plan;
5. independently acquired and validated datasets for the selected periods;
6. sealed V3 campaign and candidate-spec machinery, atomic dataset binding, and source review;
7. explicit human approval of the final plan, source, runtime, data, and authority boundary.

Protected holdout policy and all paper, broker-write, and live controls remain absent.
