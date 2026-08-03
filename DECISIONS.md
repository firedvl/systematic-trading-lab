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
