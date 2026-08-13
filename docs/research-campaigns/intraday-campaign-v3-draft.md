# Intraday Campaign V3 draft

Status: development-only draft; not preregistered, sealed, bound, source-reviewed, or executable as a
campaign.

Draft ID: `intraday-research-v3`

Draft contract: `config/research/intraday-campaign-v3-draft.json`

Exposure inventory: `config/research/intraday-known-exposures-v1.json`, fingerprint
`0666996faabb50abce0b8959c49980e36a655ea290618bc1463342d2ab5122f9`.

Candidate period selection: `config/research/intraday-v3-period-selection-v1.json`, fingerprint
`d371488a56a1b960ebb54c9d5a1cfe46e043523e21c99a49da392e69cc75d0b1`.

Qualification binding: `config/research/intraday-v3-qualification-binding-v1.json`, fingerprint
`11ce501cafc2ad0078d5750e185470dccbbf17a8b01b4ecfd95159c615b45cc3`.

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
V3 report schema. The separate V3 qualification binding accepts only exact
`intraday-backtest-report-v2` evidence, reads gate inputs only from `realistic.metrics`, verifies the
paired realistic and zero-cost fingerprints and semantic trace, and requires exact five-role lineage
plus all 60 campaign records. Zero-cost fields cannot satisfy a gate. Unbound diagnostics fail the
controlled-registry gate, and every output authority remains false. No turnover gate is active or
proposed. No controlled V3 report exists, so no V3 qualification has passed.

## Draft candidate matrix

The draft contains three active strategies, four roles, and five variants per strategy-role pair:

| Variant | Slippage bps | Commission bps | FIFO delay |
| --- | ---: | ---: | ---: |
| base | 5 | 1 | 1 bar |
| increased-cost | 10 | 2 | 1 bar |
| harsher-cost | 20 | 5 | 1 bar |
| plus-1-bar | 5 | 1 | 2 bars |
| plus-2-bars | 5 | 1 | 3 bars |

The fixed design budget is `3 × 4 × 5 = 60`. Cash remains a non-budget software sanity test. No
candidate reservation exists because freshness has not approved a sealable plan.

## Period selection

The repository and Git-history audit classifies acquired data, observed results, synthetic fixtures,
date-only references, and unresolved external evidence. It treats all V2 dates from 2025-07-01 through
2026-06-30 as exposed and proposes them only for Training. Calendar code produced these candidate
periods without reading prices or bars:

| Role | Dates | First and last UTC bar opens | Sessions | Opens per symbol | Review state |
| --- | --- | --- | ---: | ---: | --- |
| Training | 2025-07-01–2026-06-30 | `2025-07-01T13:30:00Z`–`2026-06-30T19:55:00Z` | 251 | 19,470 | explicitly exposed training only |
| Validation A | 2026-08-14–2026-10-16 | `2026-08-14T13:30:00Z`–`2026-10-16T19:55:00Z` | 45 | 3,510 | known-overlap safe; external attestation pending |
| Validation B | 2026-10-19–2026-12-18 | `2026-10-19T13:30:00Z`–`2026-12-18T20:55:00Z` | 44 | 3,396 | known-overlap safe; external attestation pending |
| Validation C | 2026-12-21–2027-02-26 | `2026-12-21T14:30:00Z`–`2027-02-26T20:55:00Z` | 46 | 3,552 | known-overlap safe; external attestation pending |

Each validation block exceeds the policy's 20-session coverage floor and is chronological and
non-overlapping. Session count does not prove activity, returns, or freshness. The review found no
overlap with repository-known dated real-data or result evidence, but ignored runtime state, provider
records, other clones, and human memory remain unresolved. Therefore every
`approved_for_v3_validation` flag is false. The draft contract keeps its dates unset and cannot be
sealed. A separate attestation must approve or reject each validation block before preregistration.

## Source and dataset prerequisites

The V2 49-module manifest stays immutable and excludes V3. The V3 build workflow now creates a
canonical exact-byte manifest for every source file in `systematic_trading_lab`, including
`intraday_v3.py` and package data, and binds the source commit, V3 foundation commit, and `uv.lock`
hash. GitHub will attest that manifest with
the wheel and runtime build manifest only from the post-merge main workflow. This pull request does
not manufacture that attestation. The non-authoritative preassessment can later require exact
manifest/wheel package equality, the same trusted `gh` identity and source commit for all three
attestations, exact installed package bytes, the fixed lock and dependency wheels, and isolated
CPython 3.12 runtime closure. It cannot create or stand in for a plan, human source review, campaign
review, candidate binding, dataset, runner, or authority. Before candidate 1, V3 still requires the
merged reviewed source, main-attested application wheel and manifests, explicit human review,
immutable campaign source review, independently acquired and validated period datasets, atomic
binding of all 60 reservations, and a per-candidate execution-source binding.

Remaining blockers before preregistration:

1. external freshness attestation for every candidate validation period;
2. reviewed final V3 campaign contract, reserved namespace, stored-spec-only runner contract, and
   plan fingerprint created only after that attestation;
3. merged final source commit and main-attested wheel, build manifest, and whole-package manifest;
4. passing non-authoritative artifact preassessment plus explicit human source and runtime review;
5. independently acquired and validated datasets for all four approved periods;
6. exactly 60 pending reservations, atomic four-dataset binding, immutable source review, and stored
   V3-only runner specs;
7. explicit human approval of the final plan, source, runtime, data, and authority boundary.

Protected holdout policy and all paper, broker-write, and live controls remain absent.
