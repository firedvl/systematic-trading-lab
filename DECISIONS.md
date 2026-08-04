# Architecture decisions

## 2026-08-02 — Standalone typed Python package

- Decision: use Python 3.12+, a `src` layout, uv, ruff, mypy, and pytest.
- Context: the repository starts empty and needs a small inspectable base.
- Alternatives: a large trading framework or notebook-first layout.
- Reasoning: explicit modules keep system assumptions testable without adopting a framework's hidden semantics.
- Consequences: the project owns its core behavior; more code arrives only with a milestone need.
- Revisit when: a component has a measured need that a mature library meets without becoming authoritative.

## 2026-08-02 — Standard-library boundaries first

- Decision: use frozen dataclasses, `Decimal`, canonical JSON, argparse, and SQLite. Store the initial fixture dataset as canonical JSON Lines.
- Context: M0 and the safe M1 slice need deterministic evidence without a large runtime dependency.
- Alternatives: Pydantic, Click, SQLAlchemy, and Parquet/PyArrow immediately.
- Reasoning: standard-library types cover the current validated boundaries and make bootstrap setup smaller.
- Consequences: JSON Lines is not the long-term columnar research format; manifests isolate storage format and schema versions.
- Revisit when: real market-data volume makes columnar scans material; adopt Parquet/PyArrow before the Alpaca archive grows.

## 2026-08-02 — Content-addressed immutable datasets

- Decision: derive dataset directories from a SHA-256 fingerprint of the immutable version envelope: provider, request, adjustment policy, processing versions, raw artifact hash, and canonical normalized-bar fingerprint. Write artifacts atomically; an exact re-import returns the existing version.
- Context: evidence must not be silently overwritten and identical inputs must reproduce.
- Alternatives: mutable named files or database blobs.
- Reasoning: content addressing makes deduplication, integrity checks, and catalog reconstruction direct. Binding stable metadata prevents identical bars from different providers or requests from sharing one manifest.
- Consequences: corrected data becomes a linked version; the normalized-bar fingerprint remains separate so experiments can verify exact inputs. Retrieval time does not change the version identity.
- Revisit when: remote object storage requires a different atomic publication protocol.

## 2026-08-03 — XNYS calendar for session completeness

- Decision: use `exchange-calendars` with the XNYS calendar for expected daily sessions.
- Context: weekday checks accept U.S. market holidays as valid bars.
- Alternatives: a weekday-only rule or a hand-maintained holiday list.
- Reasoning: the maintained calendar captures holidays and shortened-session schedules without duplicating dates in this repository.
- Consequences: calendar version is part of the locked environment; missing expected sessions reject a dataset.
- Revisit when: a point-in-time calendar policy or multi-venue universe requires explicit calendar ownership.

## 2026-08-03 — Read-only Alpaca HTTP boundary

- Decision: use a small stdlib `urllib` adapter for historical bars and keep credentials at the CLI environment boundary.
- Context: M1 needs provider access but must not introduce broker authority or make an SDK authoritative.
- Alternatives: `alpaca-py` or direct broker integration.
- Reasoning: the endpoint is narrow, pagination is explicit, and the adapter is easy to mock and keep read-only.
- Consequences: endpoint response mapping is owned and tested here; later broker execution remains a separate module.
- Revisit when: paper execution needs broker functionality that cannot be isolated behind the same provider boundary.

## 2026-08-03 — Next-bar fill semantics for M2

- Decision: signals generated after a completed bar can first fill on the next available bar for that symbol, using its open plus conservative basis-point costs.
- Context: using the signal bar's close creates an optimistic execution assumption and can hide lookahead.
- Alternatives: same-bar close fills or a third-party backtesting engine.
- Reasoning: the rule is explicit, deterministic, and keeps core assumptions owned by this repository.
- Consequences: the final signal can be rejected for lack of a future fill; event, order, trade, and equity ledgers retain the timestamps.
- Revisit when: intraday data and a reviewed latency/session model support more detailed event scheduling.

## 2026-08-04 — Reports expose benchmarks without a hidden score

- Decision: reports list each baseline and expose excess return versus cash; they do not collapse results into a qualification score.
- Context: benchmark context is needed before interpreting a backtest, while aggregate scores can hide catastrophic weaknesses.
- Alternatives: a single composite rank or a report containing only the selected strategy.
- Reasoning: visible per-baseline metrics preserve the evidence needed for later qualification gates.
- Consequences: report consumers must compare multiple fields; qualification remains a separate M3 authority.
- Revisit when: a reviewed qualification policy defines explicit disqualifying gates and report schema requirements.

## 2026-08-04 — SQLite experiment lifecycle is authoritative

- Decision: record every campaign candidate in SQLite before execution and move it through guarded pending, running, completed, or failed states.
- Context: files alone cannot distinguish a crash from completion or enforce search-volume accounting.
- Alternatives: report-directory discovery or an in-memory job queue.
- Reasoning: SQLite transactions provide a small durable registry, explicit search budgets, and restart-safe state without a service dependency.
- Consequences: stale running experiments become failed evidence; completion cannot overwrite a failed or completed record. Each walk-forward fold and cost or delay variant consumes its own candidate, links to its parent, and remains visible in comparison reports even when it fails.
- Revisit when: concurrent distributed workers exceed SQLite's measured write capacity.

## 2026-08-04 — Holdout access requires a logged event

- Decision: ordinary reads hide holdout metrics; completed holdouts require a unique reviewer/reason event before metrics can be read or qualification recorded.
- Context: repeated holdout inspection turns the holdout into development data.
- Alternatives: filesystem naming conventions or an honor-system command flag.
- Reasoning: registry-enforced access makes the protected transition explicit and auditable.
- Consequences: holdout creation and evaluation use a separate controlled code path; routine experiment CLI excludes holdout creation.
- Revisit when: remote authorization and immutable external audit storage replace the local registry.

## 2026-08-02 — Universe provenance is part of dataset identity

- Decision: define fixed-universe membership as sourced time intervals and bind the universe ID and content fingerprint into dataset versions, correction lineage, and experiment records.
- Context: a symbol list alone cannot show whether every instrument was available for the full research range, and a mutable universe name cannot reproduce the exact membership rule.
- Alternatives: keep one unsourced symbol list, infer membership from available bars, or record only the universe name.
- Reasoning: an explicit interval check rejects incomplete or inception-crossing requests before acquisition, while the fingerprint preserves the exact reviewed definition used by a sealed dataset.
- Consequences: imports must include exactly the full-range members; changing membership creates a separate dataset lineage even when the bars match. The first format permits one interval per symbol.
- Revisit when: exits, re-entry, symbol changes, or a larger universe require multiple intervals or a dedicated membership source.

## 2026-08-02 — Qualification metrics use complete sessions

- Decision: calculate drawdown and qualification metrics from the last equity point in each daily session while retaining every per-symbol ledger point.
- Context: processing five same-timestamp ETF bars creates intermediate equity states that depend on symbol order and can report a false intraday drawdown.
- Alternatives: treat every symbol event as a return period or discard the detailed equity ledger.
- Reasoning: daily strategies need daily qualification periods, while the full ledger remains useful for accounting and debugging.
- Consequences: report schema v2 adds 252-session zero-rate Sharpe and volatility, gross exposure, session and instrument profit concentration, and SPY up/down-regime returns. Earlier campaign metrics remain immutable evidence under their original schema.
- Revisit when: intraday data requires an explicit event-time return and benchmark policy or a reviewed nonzero reference-rate series.

## 2026-08-03 — Qualification evidence uses explicit registry roles

- Decision: commit a strict evidence manifest that names each base, benchmark, cost, delay, and parameter-neighbor experiment used for qualification aggregation.
- Context: the first campaign summary derived gate metrics by hand, which could explain results but could not safely authorize holdout access.
- Alternatives: infer roles from experiment names or accept caller-supplied aggregate metrics.
- Reasoning: explicit IDs make the evidence set reviewable, while registry checks bind every value to a completed validation record, its parent, period, strategy, dataset, universe, parameters, cost model, and execution model.
- Consequences: qualification evaluation writes a content-addressed report and stops on missing or inconsistent records. Adding a candidate or sensitivity role requires a reviewed manifest change.
- Revisit when: a typed campaign planner records these roles at candidate creation and can generate the same manifest without weakening review.

## 2026-08-03 — Holdout creation consumes stored qualification authority

- Decision: replace caller-supplied holdout approval with a stored, one-time authorization built from approved and passing registry evidence.
- Context: `create_experiment` accepted a boolean that could bypass the intended qualification boundary.
- Alternatives: keep the boolean behind a CLI flag or trust a report file supplied by the caller.
- Reasoning: rebuilding evidence before authorization binds the decision to current registry records. Storing the candidate specification lets one SQLite transaction verify the holdout and consume its authority.
- Consequences: a holdout must match the qualified strategy, parameters, models, dataset, universe, parent candidate, and post-validation period. One candidate, manifest, proposal, and source experiment set authorizes one holdout even when later bookkeeping changes the report fingerprint. One completed holdout permits one logged metrics read.
- Revisit when: authorization moves to a remote reviewer service with independent identity and immutable audit storage.

## 2026-08-03 — Holdout data reads follow authorization consumption

- Decision: create and claim the exact holdout record before reading market data, then use a Parquet predicate to load only its inclusive timestamp range. Store metrics only in the registry and do not write a holdout report.
- Context: stored authorization blocked ordinary holdout creation, but the full-dataset loader would expose earlier and later rows and ordinary runner outputs would bypass the logged metrics-read event.
- Alternatives: validate the full dataset before consuming authorization, pass preloaded bars to the runner, or write a hidden report file.
- Reasoning: authorization-first range loading keeps unauthorized code from seeing holdout rows and keeps completed metrics behind one audited read boundary.
- Consequences: catalog and manifest metadata can be checked before consumption, but Parquet and simulation errors consume the authorization and remain failed evidence. Range validation checks identity, bounds, symbols, and complete XNYS sessions without recomputing the full dataset fingerprint.
- Revisit when: encrypted remote storage or an external execution service can enforce the same boundary and retain an independent audit log.

## 2026-08-03 — Cataloged research reads only its experiment range

- Decision: make the cataloged training and validation runner load only the inclusive period recorded in its experiment specification.
- Context: the earlier CLI loaded and fingerprinted the full normalized dataset before filtering bars for simulation. A dataset that extended past validation could therefore expose later data to an ordinary research process.
- Alternatives: keep the full read as an integrity check, split each date range into a separate dataset, or rely on callers not to inspect the extra rows.
- Reasoning: a Parquet predicate enforces the experiment boundary while the catalog and stored manifest still bind dataset and universe provenance. Range checks reject missing symbols or XNYS sessions.
- Consequences: the runner cannot recompute the normalized fingerprint for the full dataset without violating the read boundary. Full artifact validation remains a separate data-management operation, and direct in-memory tests may still supply a complete fingerprinted bar set.
- Revisit when: manifests include independently verifiable partition fingerprints or storage enforces row-level authorization.

## 2026-08-03 — Portfolio strategies decide after complete sessions

- Decision: give multi-symbol strategies a separate backtest method that receives one complete session and immutable per-symbol history through that close. Validate the full long-only target set atomically and fill accepted targets no earlier than the next configured bar for each symbol.
- Context: the per-symbol callback rejects cross-symbol targets and would make a portfolio rank depend on which symbol happened to run last. The failed long-horizon training campaign also showed a need to design allocation and turnover across the full portfolio.
- Alternatives: permit cross-symbol targets from one bar callback, choose one symbol as the session trigger, or let each target pass validation on its own.
- Reasoning: an explicit session boundary removes symbol-order lookahead, while atomic validation prevents part of an invalid allocation from trading. A total weight cap preserves the existing unlevered long-only model.
- Consequences: portfolio backtests reject incomplete symbol sessions and nonempty target sets that do not cover the full session universe. They canonicalize target order, execute reductions before buys, keep one decision record per session, and use the existing cost, order, trade, equity, and metrics model. This adds no paper or live execution authority.
- Revisit when: intraday event time, multiple venues, shorting, leverage, or partial portfolio acceptance has a reviewed data and risk model.

## 2026-08-03 — Validation trade evidence spans the campaign

- Decision: sum executed fills across all predeclared base-validation folds for the proposed trade-count gate instead of requiring the threshold in every fold.
- Context: the original 100-fill minimum in each annual fold structurally excluded monthly portfolio strategies and treated fills as if they were independent return observations.
- Alternatives: keep the per-fold floor, lower it for selected strategy families, or add a new backtest metric that requires rerunning immutable evidence.
- Reasoning: one campaign-wide rule applies to every strategy family and reuses recorded fill counts. Existing return, Sharpe, drawdown, regime, and concentration gates retain per-fold evidence checks.
- Consequences: the proposed threshold remains 100, but its aggregate metric and proposal fingerprint change. Existing immutable reports remain historical evidence; reevaluation creates new content-addressed reports. This decision does not approve any gate or revive a rejected candidate.
- Revisit when: execution-capacity analysis or a reviewed effective-sample-size metric can replace raw fill count.

## 2026-08-03 — Qualification gates v1 approved

- Decision: approve all 17 thresholds in `qualification-gates-v1` without changing their values or rationales.
- Context: the user reviewed the gates' role and explicitly approved them after the trade-count aggregation received its separate review.
- Alternatives: leave the policy unapproved or revise one or more thresholds before approval.
- Reasoning: the visible disqualifying gates cover validation stability, benchmark performance, risk, concentration, execution sensitivity, parameter sensitivity, regime coverage, activity, and search volume. Approval locks the rules before another candidate campaign.
- Consequences: passing evidence can authorize one exact holdout run. Existing moving-average and momentum evidence becomes formally rejected, relative strength remains stopped before validation, and no holdout is authorized. Future gate changes require a separate human-reviewed change and cannot accompany strategy changes.
- Revisit when: new evidence exposes a gate defect or the research, data, or execution model changes materially.

## 2026-08-03 — Sealed training plans preregister exact candidates

- Decision: load future official training campaigns from strict, fingerprinted plan files and atomically preregister every candidate before execution.
- Context: numeric campaign budgets preserved search count but did not bind the claimed predeclared IDs, parameters, dates, provenance, parents, or models.
- Alternatives: continue using Markdown plans and CLI flags, or build full automated candidate generation.
- Reasoning: a stored canonical plan makes the current manual workflow enforceable without expanding into M6 automation.
- Consequences: `training-campaign-plan-v1` is training-only, requires explicit parameters, exact budget use, default conservative costs, and next-bar fills. Planned runs accept only a stored candidate ID. Historical campaigns remain legacy evidence and are not rewritten.
- Revisit when: a candidate passes training and needs a reviewed validation-plan schema or sensitivity models.

## 2026-08-03 — Qualification accepts only controlled runner evidence

- Decision: mark runner-owned research completions as `controlled-run` and require each qualification source to carry that provenance plus exactly one report location and SHA-256 report fingerprint.
- Context: manual completion accepted caller-entered metrics and optional artifacts, while qualification trusted any completed validation record with matching relationships.
- Alternatives: remove manual lifecycle commands, trust sealed-plan membership alone, or re-run every source during qualification.
- Reasoning: a registry provenance field closes the shared evidence path without deleting operational history or coupling qualification to market-data reads.
- Consequences: manual and migrated legacy records remain readable but cannot qualify or authorize holdout access. Existing historical rows keep null provenance. Qualification gates and strategy behavior do not change.
- Revisit when: reports move to remote immutable storage or artifact attestations replace local registry trust.

## 2026-08-03 — Complete the bootstrap baseline set without search

- Decision: define mean reversion as long exposure when the close is below its trailing moving average, and define volatility-targeted exposure as a long-only weight capped at one and scaled inversely to trailing annualized volatility.
- Context: the bootstrap required both baselines, but the implemented suite omitted them while later portfolio families were evaluated.
- Alternatives: treat later volatility-balanced allocation as the same baseline, add threshold or band searches, or defer both to automated research.
- Reasoning: two fixed, inspectable rules complete the requested system checks without parameter optimization or a new backtest boundary.
- Consequences: both strategies use existing next-bar fills, split exposure across multi-symbol datasets, fail on zero realized volatility, and remain unqualified. No campaign or protected control changes.
- Revisit when: a reviewed research plan justifies bands, volatility forecasts, cash-rate assumptions, or portfolio-level volatility targeting.

## 2026-08-03 — Paper execution uses one transactional authority

- Decision: store M4 paper authorization, intent, risk, order, broker-event, reconciliation, emergency, and hash-chain journal state in one SQLite database. Reserve pending risk capacity, a deterministic client order ID, and one submitter atomically, then recheck all external guards immediately before a paper-only network call.
- Context: retries, crashes, stale snapshots, and broker drift can turn a valid strategy target into duplicate or unsafe orders when authorities use separate mutable state.
- Alternatives: separate databases per component, broker state as the local source of truth, or direct strategy-to-adapter calls.
- Reasoning: one transaction closes the risk-to-order race while explicit component interfaces preserve authority separation. Reconciliation and client-ID lookup handle uncertain submissions without blind retries.
- Consequences: no broker writer can operate without an exact immutable paper authorization, paper mode and endpoint, active reviewed limits, fresh snapshots, clean reconciliation, and clear emergency state. Broker evidence stores only sanitized normalized fields. Unknown submit or cancel results require lookup and reconciliation before retry. Paper results remain simulation evidence, not live-execution validation.
- Revisit when: measured concurrency, remote durability, or independent service deployment requires a database-backed event service without weakening atomic guards.
## 2026-08-03 — Stable reconciliation is a three-sample reviewed interval

- Decision: emergency-clear readiness uses the latest three distinct clean adapter-attested reconciliation records for one baseline, with each comparison and completed observation separated by the explicit positive stability interval in `RiskLimits`.
- Context: one clean read can capture a transient broker state and must not enable paper authority.
- Alternatives: one sample, two samples, a fixed global delay, or an operator-supplied delay outside the reviewed risk fingerprint.
- Reasoning: three consecutive samples expose a repeated state without adding a scheduler, while binding the interval into reviewed limits prevents a caller from shortening it at clear time.
- Consequences: any dirty record among the latest three resets readiness; the latest state must remain fresh at assessment. Readiness is read-only and does not clear emergency state.
- Revisit when: measured paper polling cadence or broker consistency data supports a stricter reviewed rule.

## 2026-08-03 — Approved risk decisions reserve capacity atomically

- Decision: an approved risk decision creates one immutable reservation for cash, gross exposure, order notional, and order count in the same SQLite transaction; active reservations are included in later evaluations until their bound expiry.
- Context: a risk approval without durable pending capacity can be duplicated across workers or restarts before an order lifecycle exists.
- Consequences: rejected decisions remain evidence, approved decisions cannot exist without a matching reservation, and reservation release waits for the reviewed forward-only order lifecycle slice.
- Revisit when: order submission, fill, cancellation, and reservation-release states are implemented and independently reconciled.

## 2026-08-03 — Filled orders retain capacity until reconciliation

- Decision: cancellation or rejection with zero cumulative fill releases reserved capacity atomically with the terminal local order transition. Any positive fill retains its reservation until reconciliation proves the resulting position.
- Context: releasing a filled order immediately would allow another decision to reuse capacity while portfolio snapshots may still show the pre-fill state.
- Consequences: zero-fill cancellation and rejection free capacity without a broker-position change. Partial or full fills retain capacity until normalized broker events and reconciliation can replace the reservation with verified position exposure.
- Revisit when: later complete reconciliation can bind a verified expected-position generation to settled broker state.

## 2026-08-03 — Broker evidence applies state or disables execution

- Decision: one normalized broker event and its forward local order transition share a transaction; identity, quantity, sequence, or local-state conflicts restore persistent emergency disable and reject the event.
- Context: storing valid evidence without applying it leaves local state stale, while applying an invalid or out-of-order event can hide drift or free capacity incorrectly.
- Consequences: accepted events are exact-idempotent, zero-fill cancellation and rejection release capacity, positive fills remain reserved for reconciliation, and raw broker responses never enter the execution database.
- Revisit when: polling and streaming event sources both exist and need one reviewed precedence rule.

## 2026-08-03 — A missing exact lookup is evidence, not retry authority

- Decision: persist a sanitized Alpaca-paper 404 only from the production exact-client-order lookup path and only for a local `submission-unknown` order. The record does not change order state or release capacity.
- Context: a broker can return a transient or stale negative lookup after an unknown submission outcome.
- Consequences: the result remains immutable historical evidence. Any future retry assessment must bind it to later full clean reconciliation; no retry or broker writer exists.
- Revisit when: observed paper behavior supports a stricter negative-confirmation rule.

## 2026-08-03 — Fill evidence keeps cumulative economics

- Decision: normalized broker events with positive cumulative filled quantity must include a positive finite cumulative average fill price. Later events cannot change price at the same quantity or reduce cumulative gross notional.
- Context: quantity alone cannot support deterministic incremental expected-position and cash-impact calculations.
- Consequences: exact lookups retain enough gross fill economics for the next expected-state slice. Fees and account-wide equity or buying power remain unknown, so filled capacity is not released.
- Revisit when: authoritative fee evidence or a reviewed post-fill accounting model exists.

## 2026-08-03 — Expected positions advance from accepted fills

- Decision: an explicit reconciliation baseline can bind accepted cumulative fill increments to immutable sorted position checkpoints in the same transaction as broker evidence and local order state. Each checkpoint links its prior fingerprint and uses the immutable local order for symbol and side.
- Context: broker events can prove signed whole-share changes but cannot derive account-wide cash, equity, buying power, or fees.
- Consequences: expected position lineage is replayable and read-only. Bare broker evidence does not gain lineage later, negative positions fail closed, and any positive fill keeps its capacity reservation. Full portfolio reconciliation and filled-capacity release remain separate.
- Revisit when: a later complete adapter-attested snapshot can prove the expected position generation and settled open-order state.

## 2026-08-03 — Position settlement is separate from account accounting

- Decision: immutable position-settlement evidence binds the current expected-position lineage head to one later complete production-attested paper snapshot with exact positions, no open or nonterminal local orders, fresh observations, and clear emergency state.
- Context: a fill lineage can predict shares but cannot derive fees, marks, cash, equity, or buying-power treatment.
- Consequences: the proof records the observed snapshot and its adapter attestation but compares only position and order settlement. It does not create a local portfolio snapshot, change full reconciliation, or release capacity.
- Revisit when: a reviewed rule can replace pending reservations with fresh adapter-observed risk context without double counting or early reuse.

## 2026-08-03 — Settlement alone cannot release risk capacity

- Decision: settlement-capacity assessment is read-only and always blocks mutation while risk decisions accept caller-supplied context without durable adapter provenance.
- Context: releasing a positive-fill reservation against stale or fabricated cash, buying power, exposure, quote, or clock values could reuse capacity twice.
- Consequences: the assessment identifies exact positive-fill reservations and binds observed account values, but reports `context-provenance-missing` and changes no journal or release row. Filled capacity remains held.
- Revisit when: a production-attested snapshot-derived risk context also binds durable quote, clock, session, exposure, PnL, drawdown, limits, emergency generation, and settlement evidence.

## 2026-08-03 — Risk quotes and clock are separate attested inputs

- Decision: the production-only risk-input reader stores immutable normalized IEX latest quotes for the complete reviewed symbol set and the current NYSE `/v3/clock` response, bound to one fresh production-attested paper portfolio snapshot, paper authorization, and exact risk configuration.
- Context: caller-supplied quote and clock values cannot support safe reservation reuse or later paper admission.
- Consequences: fixed-origin GET-only evidence keeps bid, ask, sizes, provider times, observations, session phase, adapter version, and portfolio authority. It grants no risk approval and changes no capacity.
- Revisit when: durable strategy PnL, drawdown, quote-pricing policy, and reservation-set evidence can derive the full `RiskContext` without caller financial inputs.

## 2026-08-03 — Long-only risk exposure uses the IEX ask

- Decision: derive current symbol notional and gross long exposure from the complete attested IEX quote set using each symbol's ask price.
- Context: the conservative basis avoids understating long exposure without trusting caller prices.
- Consequences: the deterministic valuation can overstate liquidation value. It does not supply a side-aware execution quote or replace broker equity, cash, buying power, or strategy performance evidence.
- Revisit when: the execution envelope permits shorts or an approved risk model requires separate liquidation and acquisition prices.

## 2026-08-03 — Execution-price risk checks are side-aware

- Decision: `RiskContext` carries the current whole-share quantity and both bid and ask. Risk evaluation uses the ask for increases and the bid for reductions; long target exposure remains ask-valued.
- Context: one quote field could let a sell pass its price-deviation gate on a favorable ask even when the executable bid was materially worse.
- Consequences: crossed quotes fail construction. Quantity-target order notional uses the selected side, while projected long exposure uses the conservative ask.
- Revisit when: a later execution envelope adds short sales, limit-price placement, or fractional shares.

## 2026-08-03 — Daily loss uses attested account equity change

- Decision: Alpaca paper snapshot attestation v2 retains the positive `last_equity` account field. Daily PnL is the current attested equity minus that prior-close equity.
- Context: `RiskContext.daily_pnl` must not come from a caller, and account daily loss is distinct from per-strategy drawdown.
- Consequences: the value is derived read-only from immutable adapter evidence and binds the snapshot and attestation fingerprints. Version-1 attestations remain valid but cannot produce daily PnL evidence.
- Revisit when: the broker changes the account contract or reviewed policy requires a different daily-loss session boundary.

## 2026-08-03 — Risk decisions bind the temporal active reservation set

- Decision: inside the risk-decision transaction, derive the active reservation set from immutable rows whose reservation time is at or before evaluation, expiry is after evaluation, and release is absent or later than evaluation. Replace caller pending-capacity totals and fingerprint the exact set.
- Context: caller totals can omit a reservation or erase capacity with a timestamp from the wrong point in time. A later release must not change an earlier evaluation.
- Consequences: risk decisions now bind reservation IDs, reservation fingerprints, aggregate cash, gross exposure, order notional, and count. Filled capacity remains reserved until an effective release event.
- Revisit when: the complete attested risk context can consume this set alongside strategy drawdown and settlement evidence.
