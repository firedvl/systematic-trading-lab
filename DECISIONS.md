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

- Decision: derive dataset directories from a SHA-256 fingerprint of canonical normalized bars and write artifacts atomically; re-import returns the existing version.
- Context: evidence must not be silently overwritten and identical inputs must reproduce.
- Alternatives: mutable named files or database blobs.
- Reasoning: content addressing makes deduplication, integrity checks, and catalog reconstruction direct.
- Consequences: corrected data becomes a new version; metadata that varies by retrieval is outside the data fingerprint.
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
- Consequences: stale running experiments become failed evidence; completion cannot overwrite a failed or completed record.
- Revisit when: concurrent distributed workers exceed SQLite's measured write capacity.

## 2026-08-04 — Holdout access requires a logged event

- Decision: ordinary reads hide holdout metrics; completed holdouts require a unique reviewer/reason event before metrics can be read or qualification recorded.
- Context: repeated holdout inspection turns the holdout into development data.
- Alternatives: filesystem naming conventions or an honor-system command flag.
- Reasoning: registry-enforced access makes the protected transition explicit and auditable.
- Consequences: holdout creation and evaluation use a separate controlled code path; routine experiment CLI excludes holdout creation.
- Revisit when: remote authorization and immutable external audit storage replace the local registry.
