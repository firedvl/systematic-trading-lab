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

## 2026-08-03 — Strategy drawdown starts from reviewed allocated capital

- Decision: require a positive strategy-capital allocation in each reviewed risk configuration and bind one immutable strategy-equity baseline to the exact paper authorization and flat reconciliation baseline.
- Context: account equity drawdown can hide one strategy's loss behind another strategy's gain, while the bootstrap defines no strategy-capital allocation value.
- Consequences: the allocation changes the risk-configuration fingerprint and has no production default. The baseline binds account, strategy identity and version, allocation, operator, reason, and time. It grants no PnL, peak, drawdown, risk approval, or capacity authority.
- Revisit when: immutable fills, strategy cash flows, fees, and quote marks can advance strategy-equity checkpoints.

## 2026-08-03 — Strategy equity uses fill replay, cost reserve, and bid marks

- Decision: derive immutable strategy-equity checkpoints by replaying cumulative accepted-fill notional, subtracting an explicit reviewed basis-point cost reserve on buys and sells, and marking settled long positions at production-attested IEX bids.
- Context: account equity cannot isolate one strategy, cumulative average fill price is not an incremental cash ledger, and the current broker evidence has no authoritative fee field.
- Consequences: `RiskLimits` requires a nonnegative strategy fill-cost value with no production default. Each checkpoint requires the latest settlement proof, complete fresh bid evidence, and prior peak lineage. The reserve is policy, not broker fee evidence. Derived drawdown grants no risk approval or capacity authority.
- Revisit when: authoritative broker fee evidence can replace or reconcile the reserve, or the execution envelope permits shorts.

## 2026-08-03 — Complete risk context is derived in one read transaction

- Decision: derive every `RiskContext` field from verified journaled evidence inside one SQLite read transaction and return a fingerprinted provenance proof.
- Context: independently valid account, quote, clock, daily-PnL, strategy-drawdown, settlement, reservation, authorization, limits, and emergency values can still describe different moments or authorities.
- Consequences: callers supply only authorization, symbol, reviewed limits, and evaluation time. The builder writes nothing and grants no risk approval or capacity authority. One-minute order activity comes from journaled reservations, including completed attempts, while active reservation capacity uses exact temporal membership.
- Revisit when: the risk-decision transaction replaces its legacy caller-supplied context with this derivation under an immediate write lock.

## 2026-08-03 — Risk decisions derive attested context under their write lock

- Decision: expose only a risk-decision entry point that derives the complete attested context inside the same immediate transaction as decision and reservation persistence.
- Context: a read-only proof can become stale before a later write, while caller financial inputs cannot establish provenance.
- Consequences: callers provide only intent, authorization, reviewed limits, and evaluation time. Decisions bind the context-provenance fingerprint. Exact replay excludes its own reservation and returns the original receipt; a changed second decision for one intent fails closed. Direct context injection remains private test scaffolding.
- Revisit when: settled filled reservations can be replaced atomically by the same current attested context without double counting.

## 2026-08-03 — Settled positions replace exclusive pending capacity atomically

- Decision: release positive-fill reservations only when the same immediate transaction derives a complete attested context that matches the current settlement proof, emergency generation, and exact exclusive active reservation set.
- Context: retaining settled reservations double counts exposure already present in the attested portfolio, while releasing them from settlement evidence alone can reuse capacity against stale or incomplete risk inputs.
- Consequences: later order mutations, stale evidence, unrelated active reservations, and changed replay fail closed. Individual capacity releases and one immutable summary proof share the transaction. The release grants no broker-write authority.
- Revisit when: multiple concurrent settled batches must share one account without requiring an exclusive active reservation set.

## 2026-08-03 — Paper submission preflight accepts quantity targets only

- Decision: before a quantity-target order enters `submitting`, rederive the complete attested context and reevaluate every risk gate under the same immediate transaction as the single-submitter claim. Require the staged delta to match current shares and current economics to fit within the existing reservation.
- Context: staging binds an intent and reservation but does not prove that an arbitrary whole-share delta matches a weight target or a later portfolio state.
- Consequences: preflight binds paper mode, fixed origin, authorization, limits, intent, delta, submitter, and current risk proof. Weight-target submission remains blocked. No broker transport exists.
- Revisit when: policy defines deterministic weight-to-share rounding and its reservation treatment.

## 2026-08-03 — Submission preflight is the one-shot attempt marker

- Decision: let only the process that creates a paper submission preflight invoke the fake transport. Treat every existing preflight as a prior attempt that requires lookup and reconciliation before any retry.
- Context: an idempotent submitter claim cannot distinguish a harmless read replay from a duplicate external call after a crash.
- Consequences: valid normalized fake evidence advances through the broker-event authority. Transport or evidence failure enters `submission-unknown`. Restart and concurrent replay cannot invoke the injected transport twice. No HTTP transport exists.
- Revisit when: the production paper adapter can bind its exact POST attempt and sanitized outcome to the same authority.

## 2026-08-03 — Paper order POST remains injected-only

- Decision: construct and validate the exact Alpaca paper `POST /v2/orders` contract behind a mandatory injected transport with no production fallback.
- Context: request and response semantics need end-to-end coverage before repository policy permits any broker write.
- Consequences: tests exercise the supported whole-share day-market envelope, fixed origin, normalized acknowledgement, sanitized timeout, and one-shot outcome handling without contacting Alpaca. Production paper and all live calls remain impossible.
- Revisit when: cancellation recovery, cancel-all evidence, operations runbooks, an active reviewed risk configuration, and explicit broker-write enablement exist.

## 2026-08-03 — Cancellation mutation state stays separate from fill state

- Decision: store one immutable cancellation attempt per nonterminal order and separate unknown-outcome evidence without adding cancel states to the order lifecycle.
- Context: a cancel request can race with partial or full fills. Replacing broker order state with `canceling` would hide authoritative fill progress.
- Consequences: the attempt binds the latest broker event, authorization, operator, reason, paper origin, and time. Unknown outcome never retries or releases capacity. Later broker events remain authoritative and terminal state resolves the attempt.
- Revisit when: the injected cancellation adapter and lookup recovery can prove a richer mutation lifecycle without obscuring fills.

## 2026-08-03 — Cancel acceptance is not cancellation proof

- Decision: let only the creator of an immutable cancellation attempt call the injected fixed-origin single-order DELETE adapter. Treat an empty response as request acceptance, not terminal order evidence.
- Context: Alpaca can accept a cancel request while a fill or cancellation remains in flight, and a timeout cannot reveal whether the request arrived.
- Consequences: timeout or invalid response records unknown outcome. Existing attempts block repeat calls. Only later broker evidence can resolve the order and release eligible capacity. No production transport exists.
- Revisit when: production paper mutation authority and cancellation lookup recovery are reviewed together.

## 2026-08-03 — Cancel-all is a plan, not a bulk broker call

- Decision: store one immutable cancel-all snapshot of the exact sorted local nonterminal order set and its latest broker-event fingerprints. Do not use Alpaca's bulk cancellation endpoint.
- Context: one bulk response can hide partial acceptance, timeout, fills, and per-order unknown outcomes.
- Consequences: the plan grants no mutation authority. Each item must use the existing single-order attempt and resolution controls, preserving evidence and capacity per order.
- Revisit when: measured scale proves sequential single-order cancellation cannot meet an explicit emergency deadline.

## 2026-08-03 — Cancel-all progress is per order and restart-safe

- Decision: consume a cancel-all plan sequentially through separate one-shot attempt transactions that recheck each planned broker-event fingerprint.
- Context: the order state can change after planning, and a process can stop after any subset of external calls.
- Consequences: accepted, unknown, prior-attempt, and stale results remain distinct. Restart skips durable attempts, stale items make no call, and one failure does not erase other progress.
- Revisit when: measured cancellation latency requires bounded parallel workers with the same per-order invariants.

## 2026-08-03 — Cancellation resolution requires positive lookup provenance

- Decision: store immutable fixed-origin production exact-lookup provenance beside each successful normalized broker event and assess cancellation resolution read-only.
- Context: a bare broker event cannot prove that an exact lookup occurred after a cancellation attempt or its unknown outcome.
- Consequences: only the latest matching post-attempt lookup and local terminal state can report canceled, rejected, or filled resolution. The assessment grants no retry, broker-write, capacity, or emergency authority. A crash between event and provenance writes remains fail-closed and a later safe GET can complete the evidence.
- Revisit when: a reviewed recovery workflow needs a separately authorized mutation after complete reconciliation.

## 2026-08-03 — A readiness runbook cannot enable broker writes

- Decision: record every paper-write prerequisite, first-session check, abort condition, and recovery rule while keeping runtime write authority hard-coded off.
- Context: no candidate qualifies, no production risk values or mutation transport exist, and a checklist must not become an implicit enablement control.
- Consequences: the runbook makes missing authority explicit but changes no configuration, endpoint, credential, risk, order, or broker behavior. Each blocker requires a separate reviewed change; paper and live writes remain prohibited.
- Revisit when: a qualified candidate and reviewed production risk values exist and the explicit multi-control paper enablement boundary is ready for design review.

## 2026-08-03 — Paper-write activation and process opt-in are separate controls

- Decision: store one immutable, expiring activation bound to exact reviewed authority and require a separate process opt-in naming its fingerprint and code commit. Revocation is append-only.
- Context: paper mode, credentials, authorization, or an environment flag alone must never create broker-write authority.
- Consequences: activation binds account, authorization, limits, code, fixed origin, operation scope, distinct approver and operator, attempt cap, emergency generation, and time. Assessment remains read-only, runtime write authority stays false, and no production transport exists.
- Revisit when: submission and cancellation can recheck both controls inside their one-shot attempt transactions.

## 2026-08-03 — Activation caps count exact bound attempts

- Decision: bind the activation ID and process opt-in fingerprint inside existing submission and cancellation attempt transactions, then count the exact pair across both journal event types.
- Context: global event counts cannot prove which activation authorized an attempt, and separate per-operation counts could exceed one activation-wide cap.
- Consequences: the count and insert share one immediate transaction. Existing unbound injected attempts remain compatible and do not count. Runtime code identity remains unverified, bound records expose no transport, and broker-write authority stays false.
- Revisit when: a reviewed runtime build-identity proof can replace the remaining explicit assessment blocker.

## 2026-08-03 — Runtime identity starts with an attested wheel

- Decision: build one wheel on `main`, bind its SHA-256 and package metadata to the exact 40-character source commit in a deterministic manifest, and request GitHub attestations for both artifacts from one fixed workflow.
- Context: an environment commit string, editable install, clean Git checkout, wheel metadata, or installed `RECORD` hashes cannot prove which reviewed workflow built an artifact.
- Consequences: ordinary CI validates wheel and manifest creation. The manual provenance workflow has only read, OIDC, and attestation permissions. GitHub run `30877972755` confirmed that the repository could not persist attestations while it was user-owned and private. After it became public, run `30882447856` persisted attestations for both artifacts. The workflow retains unsigned files for diagnosis but stays failed when attestation fails.
- Revisit when: the runtime verifier and first retained attested artifact exist.

## 2026-08-04 — Build verification requires both attested artifacts

- Decision: verify both the exact wheel and its strict manifest through GitHub CLI against the fixed repository, fixed signer workflow, and GitHub-hosted runner policy before constructing an immutable runtime build identity.
- Context: a manifest attestation authenticates its wheel digest, but verifying the named wheel too avoids relying on one indirect subject. Caller strings, command output, and artifact names alone are not authority.
- Consequences: missing files, unknown fields, wrong authority, digest mismatch, tamper, timeout, missing GitHub CLI, or either failed attestation blocks identity creation without exposing subprocess output. The proof remains read-only and does not yet bind installed files or remove the activation blocker.
- Revisit when: non-editable installation provenance and complete installed-file hashes can bind the running package to the verified wheel.

## 2026-08-04 — Installed runtime identity requires exact wheel files

- Decision: accept only a non-editable archive install whose `direct_url.json` SHA-256 names the verified wheel, whose wheel-owned installed files match both `RECORD` copies, whose package tree has no unexpected importable files, and whose loaded package and modules resolve inside that exact distribution.
- Context: an attested wheel does not prove that the running process loaded it. Installed metadata alone is mutable and editable or mixed-package imports can bypass the reviewed artifact.
- Consequences: missing, malformed, parent-escaping, mismatched, extra, mixed-origin, editable, or tampered evidence blocks installed identity creation. Installer-generated script and `__pycache__` rows remain outside the trusted file set. The check is read-only and does not protect against local mutation after it returns, verify dependencies, or grant paper-write authority.
- Revisit when: activation assessment can bind a fresh installed identity to its exact reviewed commit.

## 2026-08-04 — Runtime identity is bound inside paper-attempt transactions

- Decision: activation assessment accepts one installed runtime identity verified no more than five seconds earlier, requires its full source commit to match the activation and process opt-in, and binds its fingerprint into each new request-bound submission preflight or cancellation attempt under the existing immediate transaction.
- Context: verifying an installation without carrying that proof into the atomic attempt record leaves the code identity detached from the authority it checked.
- Consequences: a missing, stale, mismatched, future-dated, or invalid identity blocks new activation-bound attempts. Activation and process opt-in commits must be full lowercase Git SHA-1s. Legacy records without the field remain readable. The fingerprint is immutable evidence of the identity checked near creation, not a defense against later local file mutation or hostile local code. Runtime broker-write authority stays false and no production transport exists.
- Revisit when: a reviewed production paper transport can consume only complete bound evidence without creating implicit authority.

## 2026-08-04 — Exact process opt-in opens only the outer paper-write gate

- Decision: let `broker_writes_allowed` become true only in exact paper mode with both an activation fingerprint and full execution commit in the process request.
- Context: the production coordinator must become reachable without treating mode, credentials, or process configuration as transaction authority.
- Consequences: construction remains blocked without exact opt-in. Submission and cancellation still recheck durable activation, installed identity, risk context, emergency state, operation scope, and shared attempt capacity inside each one-shot transaction before transport.
- Revisit when: another paper operation needs a separately reviewed transaction-bound authority path.

## 2026-08-04 — Strategic allocation advances to protected holdout

- Decision: predeclare a 35% SPY, 25% QQQ, 25% IWM, 15% GLD, and 0% TLT allocation with a 21-session rebalance interval and 10- and 42-session neighbors.
- Context: the fixed ETF universe needed a low-turnover candidate whose allocation and search volume were fixed before controlled training and validation.
- Consequences: the base beat fixed-weight in all three validation folds and passed all 17 unchanged approved gates. One exact 2026 holdout completed with its metrics protected. This evidence grants no paper or broker-write authority.
- Revisit when: a separately approved one-time holdout review has recorded its result or new evidence invalidates the candidate.

## 2026-08-04 — Holdout review binds approved gates before access

- Decision: permit one holdout read only through an approved proposal bound to the exact holdout campaign, then persist the event ID, proposal fingerprint, gate observations, result, and review fingerprint.
- Context: the completed strategic-allocation holdout must not be exposed before its evaluation rules are approved, and a crash after access logging must not force an untracked second read.
- Consequences: unapproved or mismatched proposals fail before access. Exact replay can complete the same review; another event or changed reviewer or reason fails closed. The seven approved gates reuse the validation thresholds for return, Sharpe, drawdown, exposure, concentration, and turnover.
- Revisit when: the one-time review is complete or another holdout schema needs different approved metrics.

## 2026-08-04 — Strategic allocation passes protected holdout review

- Decision: record the strategic-allocation holdout as qualified after event `m3-sa-holdout-review-v1` applied all seven approved gates.
- Context: the one-time review observed 0.091569 total return, 0.990546 Sharpe ratio, 0.107254 maximum drawdown, 0.993060 average gross exposure, 0.196134 top-five-session profit share, 0.398111 top-instrument profit share, and 1.166143 turnover.
- Consequences: every gate passed and the stored review fingerprint is `5264274cdab7ad11cde9a87895acc09be81ddae1057fa227694b72ec731e6dfc`. This result permits later paper-authorization review but grants no risk, transport, activation, broker-write, or live authority.
- Revisit when: new evidence invalidates the candidate or a reviewed paper authorization expires.

## 2026-08-04 — Risk-input freshness bounds provider-clock skew symmetrically

- Decision: apply the reviewed snapshot-age limit to the absolute difference between provider and local observation timestamps.
- Context: production IEX quotes were about 3.12 seconds ahead of the local clock and failed before evidence persistence despite remaining within the 15-second freshness window.
- Consequences: quote and NYSE clock timestamps may lead or trail local observation only within the configured limit. Larger past or future differences fail closed. No broker-write authority changes.
- Revisit when: measured clock behavior needs a separate, stricter skew limit.

## 2026-08-04 — Flat checkpoints may refresh only before execution

- Decision: allow a new zero-state checkpoint to chain from the prior zero-state checkpoint while fresh flat settlement and risk-input evidence exist and no capacity reservation has ever been created for the authorization.
- Context: the initial checkpoint's observations expire after 15 seconds, so a one-shot checkpoint cannot support later startup assessment even when the account remains flat.
- Consequences: pre-trade readiness can refresh without inventing fills or resetting strategy state. Any fill-mode checkpoint or execution artifact permanently closes the flat refresh path.
- Revisit when: a reviewed session supervisor owns periodic pre-trade evidence refresh.

## 2026-08-04 — Long-only weights floor to whole shares at the ask

- Decision: convert each approved target weight to `floor(allocated capital * target weight / attested ask)` before creating a quantity intent.
- Context: paper submission accepts only exact whole-share quantities, while the qualified strategic-allocation candidate emits weights.
- Consequences: fractional cash remains uninvested, target notional cannot exceed its weight budget at the planning quote, and submission continues to reject raw weight intents. Risk preflight revalues the quantity at a fresh executable-side quote.
- Revisit when: odd lots, fractional shares, tax lots, or cash-allocation optimization receive separate policy.

## 2026-08-04 — Terminal replay recovery requires stable fill-derived state

- Decision: clear the former unchanged-terminal replay false positive only after two identical production exact-lookups, a later post-emergency lookup, and three stable production portfolio snapshots match fill-derived cash and expected positions.
- Context: the first 4-share SPY paper fill resolved exactly, but a second identical filled lookup was rejected before terminal self-replay support existed and set emergency generation 3.
- Consequences: another emergency reason, changed terminal economics, missing lookup provenance, open orders, position drift, cash drift, stale evidence, or an unstable sample blocks recovery. The clear binds its complete proof and grants no broker mutation. A later reviewed clear may precede settlement of an older confirmed fill; an active emergency still blocks settlement.
- Revisit when: sustained paper supervision owns a general incident-classified recovery workflow.

## 2026-08-04 — Expired filled reservations still receive settlement evidence

- Decision: permit settled-capacity release after a positive-fill reservation expires when the fresh attested portfolio contains the fill, the settlement and emergency generation match, the reservation remains unreleased, and no unrelated active reservation exists.
- Context: the first SPY fill required reviewed terminal-replay recovery longer than the reservation lifetime. Expiry removed pending capacity but left no immutable record that the filled reservation had settled into broker holdings.
- Consequences: expiry cannot block accounting completion or restore pending capacity. The release remains append-only, idempotent, and broker-free. Any missing fill, stale context, later order change, prior release, or unrelated active reservation fails closed.
- Revisit when: sustained supervision can settle fills within the reservation lifetime or concurrent settlement needs a broader account-wide proof.

## 2026-08-04 — Sustained observation starts read-only

- Decision: define a bounded paper observation campaign from one production-attested portfolio snapshot and record immutable healthy, drift, or sanitized read-failure samples without activation or broker mutation authority.
- Context: M5 needs measured continuity and disconnect evidence before a scheduler or recovery supervisor can make operational decisions.
- Consequences: the campaign fixes expected positions, account, maximum sample gap, and end time. Assessment reports current staleness, historical failure and drift counts, and the largest completed gap. Recovery samples never erase prior failures. No observation can submit, cancel, settle, clear emergency state, or approve risk.
- Revisit when: measured sampling behavior defines scheduler tolerances and the replay/shadow equivalence record needs shared campaign identity.

## 2026-08-04 — Equivalence compares immutable action plans

- Decision: bind one replay plan, one shadow plan, and paper actions derived from stored quantity intents under the active observation campaign, then retain exact mismatch reasons.
- Context: M5 needs replay, shadow, and paper comparison evidence without giving a comparison tool strategy, risk, or broker authority.
- Consequences: strict external plans bind their source, configuration, targets, and evidence fingerprints. The paper side is rederived from immutable intents. Strategy, source, configuration, or target differences remain append-only failed evidence. The comparison does not claim fill equivalence or approve execution.
- Revisit when: a scheduler-independent replay or shadow runner can emit the strict plan directly instead of handing the recorder a file.

## 2026-08-04 — The first observation timer stays outside the program

- Decision: use the operating system's task scheduler to call the one-shot observation command every 10 minutes from one exact attested runtime.
- Context: the first campaign needs timing and cold-process restart evidence, but no in-program daemon, broker authority, or remote state service.
- Consequences: the task can wake the computer from sleep and start missed work when available. It cannot run while the computer is off, and any late sample remains visible in the immutable gap evidence. The task expires with the campaign.
- Revisit when: a reviewed always-on host and durable remote state can replace the local task.

## 2026-08-04 — A VPS screen loop remains one external writer

- Decision: permit one GNU Screen session to call the one-shot observation command at a bounded interval, guarded by a local file lock, while keeping restart after a VPS reboot manual.
- Context: an always-on VPS removes dependence on a personal computer without adding an in-program daemon or systemd unit.
- Consequences: SSH disconnects do not stop sampling, but a VPS reboot does. Migration must stop the old writer before copying SQLite. Cleanup defaults to a preview and deletes only validated project-local data unless the operator also requests repository deletion. External broker, GitHub, backup, audit, and shell records remain outside its scope.
- Revisit when: automatic reboot recovery or remote state requires a reviewed service manager and monitoring design.

## 2026-08-07 — Intraday bars use XNYS bar-open timestamps

- Decision: support `1m` and `5m` immutable bars whose UTC timestamps label bar opens, with expected intervals derived from each actual XNYS regular-session open and close.
- Context: daily session dates could not represent multiple bars per session or prove holiday and early-close completeness.
- Consequences: dataset identity binds `bar-open-utc-v1` and `XNYS-regular-session-bars-v1`. Missing, duplicate, non-increasing, malformed, or out-of-session records reject the dataset and remain evidence. Daily labels and validation remain unchanged.
- Revisit when: quotes, trades, extended hours, partial bars, another venue, or a provider convention requires another versioned schedule.

## 2026-08-07 — Intraday replay observes completed bars before next-bar fills

- Decision: reuse the existing simulator with an explicit timeframe. An intraday bar becomes observable at open plus duration; decisions and order creation use that time, and fills use the next eligible same-symbol bar open after the configured whole-bar delay.
- Context: treating a provider bar-open label as the decision time would allow its completed high, low, close, and volume to influence the past.
- Consequences: contiguous next-bar fills may share the bar-close decision timestamp but never precede it. Daily behavior remains unchanged. Intraday diagnostics aggregate equity at each New York session end, while experiments, qualification, holdouts, paper execution, and broker authority remain daily-only.
- Revisit when: quote-based spread, latency, partial-fill, impact, or intraday qualification models receive separate review.

## 2026-08-08 — Day-trading replay flattens at the final eligible bar open

- Decision: add the explicit `XNYS-regular-session-flat-v1` policy. It limits delayed fills to one New York session, creates a zero-weight intent early enough to fill at the final validated bar open, rejects unsafe late entries, and fails if exposure or a pending order survives the session.
- Context: the generic intraday replay could carry a position or delayed order through a normal or early close. A close-price liquidation decided after the close would introduce lookahead.
- Consequences: flat-at-close decisions use only completed bars and respect the configured whole-bar delay. The last regular-session bar may mark the already-flat portfolio but cannot create another eligible fill. Daily replay and intraday diagnostics without the day-trading policy remain unchanged. Intraday experiment and qualification paths remain blocked.
- Revisit when: a reviewed auction, market-on-close, quote-latency, partial-fill, or halt model can replace the final-bar-open approximation.

## 2026-08-08 — Intraday research uses separate versioned evidence contracts

- Decision: store `intraday-experiment-v1` in the shared lifecycle registry, run only cataloged training or validation ranges, and emit `intraday-backtest-report-v1` plus research-only `intraday-qualification-evidence-v1`.
- Context: daily lifecycle and catalog primitives are reusable, but daily report, qualification, and holdout contracts do not bind timeframe, bar-open observability, flat-at-close policy, raw cost values, whole-bar delay, or intraday benchmarks.
- Consequences: existing daily records and interfaces remain unchanged. Intraday candidates bind a fixed campaign budget and ordinal, preserve failures, report zero-trade results, and expose sample, holding, exposure, cost, benchmark, concentration, session, cost-stress, and delay-stress evidence. The intraday evaluator cannot authorize holdout access, paper execution, broker writes, or promotion.
- Revisit when: production-scale sealed intraday campaign plans, a separately reviewed protected holdout, opening-range behavior, or M5C paper controls receive approval.

## 2026-08-08 — Initial intraday strategies remain fixed engineering baselines

- Decision: begin with cash, one-bar directional momentum, and a 12-bar moving-average trend over complete SPY/QQQ slices. Allocate at most one-half to each symbol, stay long-only and unlevered, and enforce `XNYS-regular-session-flat-v1`.
- Context: M5B needs deterministic system checks without broad search or claims of profitability.
- Consequences: the CLI exposes no strategy parameter override. Opening-range breakout, parameter optimization, shorting, leverage, extended hours, options, and autonomous generation remain deferred. Validation variants may change only preregistered costs, delay, or parameter-neighbor evidence and must retain parent lineage.
- Revisit when: reviewed campaign plans define bounded parameter neighborhoods or another fixed baseline adds enough evidence to justify its complexity.

## 2026-08-08 — The first intraday campaign reserves every base and stress run

- Decision: preregister `intraday-research-v1` with SPY/QQQ `5m` data, one six-month training window, three following two-month validation windows, the three fixed M5B baselines, and five candidates per strategy-period pair: base, increased cost, harsher cost, `+1` bar, and `+2` bars.
- Context: the first historical campaign must test chronological validation and research evidence without adding candidates or changing assumptions after results appear.
- Consequences: the strict plan fingerprint reserves all 60 ordinals, uses 5/1, 10/2, and 20/5 slippage/commission basis points with one/two/three-bar delays, and rejects parameter neighbors or any holdout, paper, broker-write, or live authority. No real run can start until independent read-only credentials produce four valid sealed datasets. A deterministic fixture proof remains ignored and is not campaign evidence.
- Revisit when: independent historical credentials are available, a data defect blocks the frozen windows, or a software defect requires a separately versioned campaign.

## 2026-08-12 — Final observation status preserves historical failures

- Decision: derive current health, completion, continuity, and final campaign result separately from immutable observations. A completed campaign passes only when its latest state is healthy and fresh, no completed sample gap exceeds the configured maximum, and no drift occurred.
- Context: Week 1 ended healthy after 1008 healthy samples and one recovered read failure, but two VPS reboots created a real gap of approximately 1030.755 seconds, reported as 1031 seconds, against the fixed 900-second limit. The old assessor exposed the gap but based its exit code only on current health.
- Consequences: a recovered read failure remains counted but does not alone fail the campaign because scheduled failure and recovery are M5 evidence. Historical drift and excess gaps remain final blockers after recovery. Existing databases need no migration or evidence change, and assessment grants no broker authority.
- Revisit when: a separately reviewed policy defines tolerated failure budgets or restart-safe supervision.

## 2026-08-12 — systemd supervises one verified read-only observation loop

- Decision: use one boot-enabled systemd service to run the packaged paper-observation supervisor from an exact project-local attested runtime. Pin the campaign, runtime artifacts, home, interval, GitHub host, and GitHub CLI directories in a generated unit; hold both current and legacy locks beside the execution store; keep Screen as an optional launcher for the same command. Migrate an old root-run deployment by changing ownership only on `.env`, the execution database and present SQLite sidecars, and both locks. Keep the project-local state parent root-owned and sticky and every runtime-build path root-owned and non-writable by the service.
- Context: GNU Screen survives SSH disconnects but not a host reboot. Week 1 proved that manual restart can breach the 900-second continuity limit. The old VPS store is root-owned, while the service must be unprivileged. GitHub CLI exposes one generic failure exit for remote attestation transport, absence, and rejection, so the caller cannot safely infer a permanent remote verdict from that code. A finite systemd start limit can permanently stop automatic retries after several transient failures; expiry of its interval does not restart the unit.
- Consequences: local configuration, authentication, provenance, integrity, journal, and lock failures exit 2 and do not restart. A timeout or explicitly recognized DNS, connection, rate-limit, or server-availability attestation error exits 75 without observing. systemd waits at least 60 seconds and retries without a finite start-count limit, so repeated transient failures cannot latch the service off and recovery can still be recorded after continuity has failed. Missing attestations, policy/signature rejections, and unrecognized failures remain exit 2. No retry grants authority. Startup still requires live GitHub access. The service blanks paper-write opt-in, loads credentials only from a private repository `.env`, logs to journald, and exits after either final campaign result. Migration preserves database and sidecar bytes, refuses active observers, never recursively changes ownership, and leaves Week 1 archives untouched. A 600-second interval leaves limited reboot tolerance; sufficiently long host, network, DNS, broker, or provenance-verification outages still fail continuity.
- Revisit when: the bounded VPS recovery drill exposes a missing boot dependency or the observation store moves off-host.

## 2026-08-12 — Close M5 with an explicit sustained-duration waiver

- Decision: accept the shorter passing reboot/recovery validation and the healthy portion of the stopped follow-up campaign, and waive the remaining unobserved part of the 168-hour requirement for the current M5 operational closeout.
- Context: Week 1 preserved a failed continuity gate. The later shorter validation passed, and the longer follow-up remained healthy until it was intentionally stopped before 168 hours.
- Consequences: M5 operational work closes without rewriting Week 1 evidence or claiming that the full 168 hours passed. The unobserved duration remains an explicit evidence gap. The waiver grants no paper activation, broker-write, live, research-qualification, or strategy-promotion authority, and the restart-safe supervision controls remain available.
- Revisit when: a later paper-operation decision depends on full-duration sustained evidence or new operational evidence invalidates the shorter validation.

## 2026-08-13 — Campaign V1 binds one complete dataset set before execution

- Decision: record the Alpaca adapter and IEX feed in dataset identity, require the reviewed SPY/QQQ `5m` universe, fully validate all four frozen period datasets, and bind all 60 Campaign V1 reservations in one transaction. Keep the sealed `base_code_commit` as the reviewed M5B foundation reference and block Campaign V1 execution until the actual checkout or build identity is separately reviewed and recorded.
- Context: per-candidate binding allowed a run before the other three period datasets existed, the plan's provider label did not match the concrete manifest adapter name, manifests omitted the selected feed, mutable universe configuration could change later binding, and reports could present the old reviewed commit without proving which reconciled code executed them.
- Consequences: missing, corrupt, substituted, repeated, partial, or changed binding fails before a candidate is claimed and cannot burn one ordinal. The sealed plan, costs, delays, dates, parameters, ordinals, policy fingerprint, authority flags, and foundation reference remain unchanged. If the execution source differs materially from the reviewed source surface, a new campaign version is required.
- Revisit when: a reviewed execution-source provenance contract can identify the running source without rewriting sealed Campaign V1 fields.

## 2026-08-13 — Zero scheduled early closes satisfy complete coverage

- Decision: interpret `early_close_coverage` as complete when a fully validated XNYS period reports any nonnegative integral scheduled-early-close count, including zero.
- Context: Validation A, B, and C contain no scheduled early closes, while the reviewed policy rationale requires complete coverage for any reported early-close sessions. Requiring a positive count would make all nine validation base candidates fail regardless of data completeness.
- Consequences: zero is a vacuous coverage pass only after calendar and dataset validation. Missing, malformed, fractional, or negative counts fail. The policy file, threshold, fingerprint, periods, and candidate identities remain unchanged.
- Revisit when: a later policy version records expected and observed early-close sessions as separate metrics.

## 2026-08-13 — Campaign V1 records execution identity outside the sealed plan

- Decision: keep Campaign V1's `base_code_commit` as its reviewed M5B foundation reference. Separately assess the main-only GitHub-attested wheel, the canonical GitHub CLI path and SHA-256 used for both attestation checks, exact non-editable installed project package, sealed-lockfile dependency wheels and installed files, and a CPython 3.12 standard-library `venv --without-pip` runtime invoked only with the fixed `-I -B -S` bootstrap. Compare every `.py` file in the application package against wheel-bound `intraday_campaign_v1_surface.json` (48 modules): foundation-exact, an exact reviewed delta, or a reviewed new file. Record one immutable explicit review while all 60 candidates remain pending. Bind a fresh matching assessment to each candidate in the same transaction that claims it, and verify the runtime again before publishing its report.
- Context: the sealed foundation reference identifies the code reviewed before preregistration, not the later checkout or build that executes a candidate. Installed dependency metadata can be rewritten with altered files, and a component-only surface can leave result-affecting code outside the review boundary. The inert surface manifest is wheel-bound but cannot verify itself.
- Consequences: added, missing, or byte-mutated application modules fail; there is no AST normalization. The application wheel may contain only the project package and its own distribution metadata, so it cannot add an unmanifested top-level importable file. The attestation verifier is resolved once to an absolute canonical executable named `gh`, checked before and after both exact-path calls, and retained in the assessment; a changed path or bytes fails later equality checks. The verifier file and every install-path ancestor must be owned by another trusted account and non-writable by the execution account, so stable caller-selected substitution also fails. The reviewed deltas include PR #114 dataset-feed identity patch `3a339ab7866a22a2e200aee617395d9cc05e45c9` / diff `4ac13c3d58d675544a11b4bb00ea9d52996e53b1dc6e84c21658fc0485ec7f92` and domain patch `952fc104c15c25260b0e29488df7ab61ae4b9a50` / diff `c3ded022ed3c9a7a8841c09c8d8c32dac167227c4e4bd084b0ef0605b564a65d`. The human reviewer must inspect the full main-attested source commit and wheel, the verifier path and hash, and the assessment fingerprint. A source-surface mismatch requires Campaign V2. Missing review, artifact or installed-byte mismatch, unexpected dependency, unsafe Python path, `.pth`, startup customization, cached bytecode, altered import hooks, or post-computation drift fails closed. The mechanism grants no holdout, paper, broker-write, or live authority.
- Revisit when: a future campaign uses another reviewed surface, the dependency lock changes, or execution moves to a runtime whose interpreter or wheel-install contract needs another version.

## 2026-08-13 — Filter Alpaca intraday transport extras at the adapter boundary

- Decision: for `1m` and `5m` requests, derive the exact expected XNYS regular-session bar-open set in `AlpacaHistoricalProvider`. Map every returned bar, retain every mapped record in immutable raw evidence, and send only requested-symbol records on that exact grid to dataset normalization. Keep unexpected symbols in the validation stream and keep `DatasetService` and `validate_records` strict.
- Context: the first Campaign V1 Training import returned the complete expected grid plus 2,758 premarket, postmarket, normal-close-boundary, and early-close-boundary records. The adapter used the grid only to set Alpaca's exclusive end, so correct dataset validation rejected the whole import before publication.
- Consequences: transport extras cannot enter normalized Parquet. A published dataset binds them into `raw.jsonl`, its fingerprint, and dataset identity; a rejected import binds mapped acquisition records and their fingerprint into quarantine evidence. Missing or duplicate requested intervals, invalid mapped OHLCV even outside the requested grid, unexpected symbols, and malformed payloads or bars still fail. Daily behavior and broker authority do not change.
- Revisit when: a provider supplies a native regular-session filter with evidence strong enough to replace local exact-grid selection, or raw HTTP payload retention receives a separate storage and privacy design.

## 2026-08-13 — Abort Campaign V1 and preregister Campaign V2

- Decision: keep `intraday-research-v1` as immutable evidence of an attempt aborted before dataset publication or candidate execution. Block new V1 sealing, dataset binding, source review, and execution. Preregister `intraday-research-v2` with the unchanged 60-candidate design, plan fingerprint `52db8a27fa4ff86865ab69b6bd7456899329ef3b861a582e59ab32904c03c122`, foundation reference `f3d7ee7d86c3a02b52c09270a6399aa1bf5f78b7`, and a new exact 49-module wheel surface that includes the corrected provider.
- Context: V1's source review was recorded, but its source surface cannot describe the corrected execution code. No strategy result was observed, so carrying forward the fixed matrix does not use result-driven information.
- Consequences: V1's sealed plan, stored review, runtime state, candidate records, and quarantine evidence remain readable and immutable. V2 uses the existing campaign-keyed source-review and candidate-binding tables without migration and preserves main-only attestation, trusted-verifier, exact install, fixed-lock, isolated-runtime, per-candidate reassessment, and no-broker-authority controls.
- Revisit when: V2 observes its first candidate result, another software or data defect changes the reviewed execution surface, or a later campaign changes the research design.

## 2026-08-13 — Close Campaign V2 as immutable failed evidence

- Decision: record `intraday-research-v2` as complete at 60/60 controlled candidates, with all 12 base research qualification groups failed and no holdout access or authorization. Preserve its plan, exact-weight execution, source review, reports, qualification evidence, and 49-module source manifest unchanged.
- Context: V2 reported extreme turnover and transaction costs. Adding recorded costs back to net P&L produced results near zero, while longer delays reduced turnover and improved net returns.
- Consequences: V2 remains valid failed evidence under its frozen semantics. Source inspection confirms that repeated 0.5 targets recalculated exact quantities after drift and that pending orders made longer delays suppress later target applications. The delay variants therefore confound latency and application cadence. These findings do not prove a profitable zero-cost signal or permit weaker gates, parameter tuning on V2 dates, holdout access, or execution authority.
- Revisit when: an integrity review contradicts the supplied campaign closeout or diagnostic export identity. A new result does not rewrite V2; it creates separate evidence.

## 2026-08-13 — V3 queues state changes instead of repeated exact weights

- Decision: add `state-transition-delayed-fifo-v1` under `intraday-experiment-v2`, `intraday-backtest-report-v2`, and `XNYS-regular-session-state-transition-flat-v2`. Evaluate SPY/QQQ desired state every completed five-minute slice, queue each changed per-symbol state for the Nth later same-session open, preserve FIFO order without supersession, and create no order for an unchanged state. Support no periodic rebalance.
- Context: V2 rescheduled unchanged targets and recalculated their quantity from current equity. Its one-pending-order rule changed accepted target cadence as delay increased.
- Consequences: an entry sizes once, an exit closes the held quantity, and price drift alone cannot trade. Later decisions remain queued while earlier transitions wait. At the deterministic close cutoff, the session controller records and cancels queued work, records late changes as rejected, and schedules any required final-open exit. Complete XNYS sessions, completed-bar causality, normal and early-close safety, and flat overnight state remain mandatory. V1/V2 code, IDs, golden fingerprints, and manifests remain unchanged.
- Revisit when: measured research needs periodic rebalance, supersession, partial fills, quote latency, auction execution, or another stale-state rule. Each requires a new reviewed contract.

## 2026-08-13 — V3 diagnostics and campaign design remain non-authoritative drafts

- Decision: pair each V3 realistic replay with `zero-cost-counterfactual-v1` on the identical semantic trace, and fingerprint both in `intraday-backtest-report-v2`. Fix three future strategies: the V2 12-bar MA signal, six-bar momentum, and a first-six-bar opening-range breakout that enters only after a later completed close exceeds the range high and then holds until close. Draft 60 candidates from three strategies, four roles, and five fixed cost/delay variants; keep cash outside the budget.
- Context: a cost add-back cannot reconstruct sizing, and V2 dates are exposed. An exact paired replay separates signal-path diagnostics from realistic cost results without turning the diagnostic into qualification evidence.
- Consequences: zero-cost results cannot enter qualification or grant authority. `intraday-qualification-policy-v1` thresholds remain unchanged, but a reviewed V3 report binding is still required. Training and Validation A/B/C dates stay unset. The selector rejects known exposed validation overlap and never certifies freshness; independent review must first inventory every observed window. All V2 dates from 2025-07-01 through 2026-06-30 are exposed. The V3 draft cannot seal or execute, and a future whole-package source manifest must include `intraday_v3.py`.
- Revisit when: the exposure inventory, exact forward validation periods, qualification binding, source review, runtime closure, and independent datasets are ready for preregistration.

## 2026-08-13 — Unresolved external freshness blocks V3 sealing

- Decision: retain a fingerprinted repository-known exposure inventory and calendar-only candidate period selection, but leave every V3 validation approval false until a separate attestation covers ignored runtime state, provider records, other clones, and human exposure. Add the non-authoritative V3 realistic-cost qualification binding, whole-package manifest build step, and artifact preassessment, but do not create a final plan, registry reservations, dataset binding, source review, runner, or execution command.
- Context: the audit found dated daily, V1, V2, strategic-allocation, and paper-account exposure through 2026-08-11. Validation A/B/C avoid all dated disqualifying entries, but repository evidence cannot prove universal freshness. The task requires unapproved periods rather than fabricated certainty when freshness remains unresolved.
- Consequences: inventory fingerprint `0666996faabb50abce0b8959c49980e36a655ea290618bc1463342d2ab5122f9` and selection fingerprint `d371488a56a1b960ebb54c9d5a1cfe46e043523e21c99a49da392e69cc75d0b1` describe candidate periods only. Training may reuse 2025-07-01 through 2026-06-30 as explicitly exposed evidence. Validation A is 2026-08-14 through 2026-10-16, Validation B is 2026-10-19 through 2026-12-18, and Validation C is 2026-12-21 through 2027-02-26. Binding fingerprint `11ce501cafc2ad0078d5750e185470dccbbf17a8b01b4ecfd95159c615b45cc3` keeps every v1 threshold, consumes only `realistic.metrics`, verifies each completed registry report and its reviewed source evidence, requires durable reasons for failed records, and grants no authority. The build workflow can attest a canonical exact-byte manifest for every package source file only after merge. The preassessment can then verify the same trusted `gh` identity across the attested wheel, build manifest, and whole-package manifest plus the installed package, fixed lock, exact dependency wheels, and isolated runtime. It remains artifact evidence only and cannot create a campaign, source review, binding, dataset, runner, or authority. No V3 contract or candidate can run or qualify. Caller-configured V1 research remains separate and cannot become V3 evidence; any use on candidate dates creates exposure. The future sealed V3 contract must reserve its namespace and expose only a V3 stored-spec runner. No V3 plan fingerprint exists, no market data or result was observed, and V1/V2 evidence remains unchanged.
- Revisit when: an independent freshness attestation approves or rejects each candidate validation period. Approval permits a separately reviewed versioned preregistration; rejection requires new periods and a new selection fingerprint.
