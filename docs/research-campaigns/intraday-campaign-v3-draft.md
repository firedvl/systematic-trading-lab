# Intraday Campaign V3 preregistration

Status: final static plan; not runtime-materialized, dataset-bound, source-reviewed, or executed.

Campaign ID: `intraday-research-v3`

Final contract: `config/research/intraday-campaign-v3.json`, fingerprint
`5e81cf8f0db1143f293a0f93900f1e797718443a559c1caaaa2e986851d5241a`.

The earlier foundation draft remains at `config/research/intraday-campaign-v3-draft.json` for its
original design evidence. It cannot become campaign evidence.

Exposure inventory: `config/research/intraday-known-exposures-v1.json`, fingerprint
`0666996faabb50abce0b8959c49980e36a655ea290618bc1463342d2ab5122f9`.

Period selection: `config/research/intraday-v3-period-selection-v2.json`, fingerprint
`c2718c3871bb95e22d4647e119f6bfb54cd51ec7b1b2cc472cfa1a7dfbcfc5d0`.

The superseded V1 period selection remains at
`config/research/intraday-v3-period-selection-v1.json` as historical evidence. It does not bind this
plan.

Qualification binding: `config/research/intraday-v3-qualification-binding-v1.json`, fingerprint
`11ce501cafc2ad0078d5750e185470dccbbf17a8b01b4ecfd95159c615b45cc3`.

This plan grants no research qualification, protected holdout, paper, broker-write, or live
authority. Committing it creates no SQLite state. Do not run a V3 candidate before every later gate
in this document passes.

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
V3 report schema. The separate V3 qualification binding accepts only exact
`intraday-backtest-report-v2` evidence, reads gate inputs only from `realistic.metrics`, verifies the
paired realistic and zero-cost fingerprints and semantic trace, and requires exact five-role lineage
plus all 60 campaign records. Zero-cost fields cannot satisfy a gate. Unbound diagnostics fail the
controlled-registry gate, and every output authority remains false. No turnover gate is active or
proposed. No controlled V3 report exists, so no V3 qualification has passed.

## Fixed candidate matrix

The draft contains three active strategies, four roles, and five variants per strategy-role pair:

| Variant | Slippage bps | Commission bps | FIFO delay |
| --- | ---: | ---: | ---: |
| base | 5 | 1 | 1 bar |
| increased-cost | 10 | 2 | 1 bar |
| harsher-cost | 20 | 5 | 1 bar |
| plus-1-bar | 5 | 1 | 2 bars |
| plus-2-bars | 5 | 1 | 3 bars |

The fixed design budget is `3 × 4 × 5 = 60`. Cash remains a non-budget software sanity test. The plan
lists all 60 IDs and ordinals in strategy-major, period, then variant order. Each non-base role points
to its matching strategy-period base. Runtime reservations do not exist until verified
materialization.

## Period selection

The repository and Git-history audit classifies acquired data, observed results, synthetic fixtures,
date-only references, and unresolved external evidence. It treats all V2 dates from 2025-07-01 through
2026-06-30 as exposed and proposes them only for Training. Calendar code produced these candidate
periods without reading prices or bars:

| Role | Dates | First and last UTC bar opens | Sessions | Opens per symbol | Review state |
| --- | --- | --- | ---: | ---: | --- |
| Training | 2025-07-01–2026-06-30 | `2025-07-01T13:30:00Z`–`2026-06-30T19:55:00Z` | 251 | 19,470 | explicitly exposed training only |
| Validation A | 2026-10-01–2026-12-03 | `2026-10-01T13:30:00Z`–`2026-12-03T20:55:00Z` | 45 | 3,474 | eligible; approval awaits pre-bar main seal |
| Validation B | 2026-12-04–2027-02-09 | `2026-12-04T14:30:00Z`–`2027-02-09T20:55:00Z` | 45 | 3,474 | eligible; approval awaits pre-bar main seal |
| Validation C | 2027-02-10–2027-04-15 | `2027-02-10T14:30:00Z`–`2027-04-15T19:55:00Z` | 45 | 3,510 | eligible; approval awaits pre-bar main seal |

Each validation block exceeds the 20-session coverage floor and is chronological and non-overlapping.
The periods moved forward rather than rushing an August 14 cutoff. Selection used only the exposure
inventory and XNYS calendar. Universal freshness remains unproved because unknown historical and
external state remains unresolved. Independent review established eligibility for prospective
market-data freshness: no known dated exposure overlaps the blocks, each began in the future at
review, and no selected-period bars or results informed the design. The selection artifact keeps
`prospective_market_data_freshness` and every validation approval false. Its `selection_date` is an
author-recorded description, not a trusted cutoff. The verified Sigstore transparency-log timestamp
for the exact GitHub/main seal is the only effective selection cutoff. It establishes the prospective
property only when it precedes Validation A's first bar.

## Source and dataset prerequisites

The V2 49-module manifest stays byte-exact and excludes V3. On main, the build workflow creates and
attests the V3 whole-package surface, wheel, runtime manifest, and preregistration seal. The seal
binds the exact inventory, selection, final plan, qualification binding, source commit, foundation
commit, first validation bar, and false authority set. Verification requires the exact repository,
signer workflow, `refs/heads/main`, source commit, seal subject digest, protected `gh` identity, and a
verified Sigstore transparency-log timestamp strictly before `2026-10-01T13:30:00Z`. Local clocks,
Git author or committer dates, filesystem times, workflow predicate times, and caller `verified_at`
cannot establish freshness. Seal creation and verification pass all four bound artifacts through
their strict shared parsers. A newly recorded selected-period acquisition rejects the selection even
if its inventory and selection fingerprints are recomputed.

The registry's materialization boundary invokes the seal verifier itself, stores the exact attested
seal bytes with the verified evidence, and then writes the plan and 60 pending reservations in one
transaction. A caller-constructed publication object cannot materialize the campaign. The committed
JSON file alone writes nothing. Dataset binding accepts four role-to-dataset-ID assignments, resolves
them through the shared catalog, validates normalized and raw integrity for all four, checks each
manifest and retrieval-after-period condition, and writes no dataset or stored-spec row unless the
whole bind passes. Human source review reruns the fixed artifact assessment and accepts only the
explicitly reviewed assessment fingerprint. Each claim derives that sole review, stores a
per-candidate binding, and moves the stored candidate to running atomically.

The controlled runner accepts only a candidate ID, storage layout, and fixed source-artifact paths.
It has no caller route for strategy, parameter, period, costs, delay, cash, dataset, review ID,
report path, or authority. It validates full dataset integrity before the exact range read, runs the
stored spec, and reverifies source before computation and before immutable report publication. A
post-claim failure is terminal; a rejected pre-claim invocation cannot fail a pending reservation or
another runner's claim. Each claim has a private lease token required by its heartbeats, source
checks, failure, and publication. The registry first commits an immutable intent containing the
canonical report, then create-only publishes and directory-syncs the exact final bytes before
committing completion. Stale recovery atomically takes publication ownership and finishes that intent;
completed-intent reconciliation can restore a missing file. A running mismatched path records terminal
failure; substituted completed bytes create immutable integrity-conflict evidence that qualification
rejects. Registered qualification derives the exact five-role group from the immutable registry plan
and fingerprints evidence for all 60 terminal records.

Remaining blockers before candidate 1:

1. merge the reviewed change to main and obtain the pre-bar GitHub/Sigstore seal attestation;
2. verify that seal, establish prospective freshness, and explicitly materialize the 60 reservations;
3. wait for Validation C's final bar to complete at `2027-04-15T20:00:00Z`;
4. independently acquire and validate all four datasets, then bind them atomically;
5. pass the exact source/runtime preassessment and record the human campaign review;
6. approve the later run under the unchanged no-authority boundary.

Protected holdout policy and all paper, broker-write, and live controls remain absent.
