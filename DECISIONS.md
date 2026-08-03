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
