# Roadmap

Each milestone requires passing formatting, lint, typing, tests, secret checks, documentation review, and every listed gate. A later milestone does not weaken an earlier gate.

## M0 — Foundation and policy

Package, safe configuration, CLI, CI, persistent documentation, initial domain types, deterministic fingerprints, storage layout, and test infrastructure. Gate: clean setup; CLI and checks pass; runtime defaults offline; live is rejected; no secrets or generated data are tracked.

## M1 — Market data

Provider-neutral acquisition, Alpaca historical adapter, fixtures, immutable raw and normalized storage, catalog, validation and quarantine, calendar and corporate-action policy, and data CLI. Gate: adjusted daily data for the fixed universe is reproducible; provider corrections create versions; invalid data cannot silently enter a dataset; catalog reconstruction works. The fixed-universe gate now covers XNYS calendar validation, raw JSONL and Parquet artifacts, deterministic fixtures, read-only paginated Alpaca acquisition, immutable correction lineage, cross-provider version isolation, provider-adjusted action handling, rejection of unadjusted data, and issuer-sourced point-in-time membership bound into dataset and experiment provenance. A local unadjusted corporate-action processor remains out of scope for this slice.

## M2 — Backtester and baselines

Timestamp semantics, portfolio accounting, deterministic orders and fills, conservative versioned costs, ledgers, metrics, benchmarks, and simple baseline strategies. The current slice covers explicit next-bar fills, cash accounting, bps slippage and commission, decision/order/trade/equity ledgers, cash, buy-and-hold, fixed-weight, moving-average trend, time-series momentum, moving-average mean-reversion, and volatility-targeted exposure baselines, cash-relative report comparisons, deterministic fixture reports, and a separate complete-session boundary for atomic multi-symbol portfolio targets. Gate: no lookahead; accounting and order invariants pass; fixed transactions cannot benefit from higher costs; reports reproduce. Walk-forward evaluation and qualification remain M3.

## M3 — Experiments and qualification

Durable campaigns and experiments, restart recovery, split controls, walk-forward and robustness checks, comparisons, gate-based qualification, and protected holdout workflow. The current slice covers search budgets, pending/running/completed/failed lifecycle, heartbeats and stale-run recovery, explicit split classification, hidden holdout metrics with logged access events, approved disqualifying gates, range-limited registry-backed runs on cataloged datasets, chronological walk-forward candidates, cost and delayed-fill sensitivity candidates, bounded run and comparison CLI commands, score-free comparison reports, fingerprinted training plans that preregister exact candidates before execution, and controlled-run provenance with fingerprinted report artifacts for qualification sources. Provider campaigns retain superseded methods and corrected reruns. Report schema v2 adds risk-adjusted return, exposure, session and instrument concentration, and SPY regime metrics. Recorded training campaigns include rejected long-horizon per-symbol momentum and rejected monthly relative-strength portfolio families with predeclared parameter neighborhoods. The approved machine-readable policy records every gate and rationale. A registry-backed evidence manifest reproduces aggregate metrics and formal rejections in an immutable report without loading bars. One-time stored authorization replaces the raw holdout-creation flag and binds an exact qualified candidate to one post-validation holdout record. The controlled runner consumes that authority before reading data, scans only the authorized Parquet timestamp range, retains failures, and keeps completed metrics behind the separate read event. Strategic allocation passed all approved validation and one-time holdout gates. Gate: failures remain evidence; ordinary research cannot read holdout results; no single score can hide a disqualifying failure.

## M4 — Alpaca paper execution

Paper-only adapter, intents, independent risk, order management, idempotency, broker events, reconciliation, operational journal, and emergency disable. The reviewed design requires one transactional execution database, deterministic client order IDs, exact paper-endpoint selection, fresh broker and market snapshots, forward-only state, reconciliation before retry, persistent emergency disable, and append-only hash-chain evidence. Broker-free intents, journal verification, risk gates with no default values, default-on emergency disable, code-bound paper authorization, durable fail-closed decisions, normalized snapshots, explicit flat baselines, durable reconciliation evidence, fixed-origin GET-only paper account state, journaled adapter provenance, stable emergency-clear readiness, idempotent journaled emergency transitions, authorization-bound strategy-capital baselines, immutable fill-and-bid-marked strategy-equity checkpoints, complete attested risk context, transaction-bound attested risk decisions, atomic settled positive-fill capacity release, transaction-bound quantity-order submission preflight, one-shot fake submission outcomes, strict injected-only paper order POST normalization, durable one-shot cancellation attempts with unknown-outcome evidence, strict injected-only single-order DELETE normalization, immutable deterministic cancel-all order-set planning, restart-safe per-order plan consumption, immutable positive exact-lookup provenance, read-only terminal cancellation recovery, a fail-closed paper-write readiness runbook, dormant activation, opt-in, assessment, and revocation controls, exact activation-bound submission and cancellation attempt caps, a main-only attested-wheel build path, fixed-authority wheel and manifest verification, exact non-editable installed-distribution binding, and transaction-bound runtime identity evidence now exist; no production HTTP broker transport exists. Gate: unknown or stale state blocks writes; duplicate intents are harmless; reconciliation discrepancies stop execution; live endpoints cannot be selected.

## M5 — Equivalence and sustained paper operation

Replay/shadow/paper comparison, supervisor recovery, disconnect and stale-data handling, and sustained paper campaign. Gate: discrepancies are explained; recovery drills pass; operating limits hold for the approved observation period.

## M6 — Bounded automated research

Machine-readable specifications, approved strategy families, bounded candidate generation, search accounting, isolated runs, and evidence-producing pull requests. Gate: all candidates remain recorded; agents cannot alter protected controls or promote strategies.

## M7 — Controlled continuous improvement

Scheduled sealing and reevaluation, champion/challenger lifecycle, shadow-to-paper advancement, drift detection, rollback, and reviewed promotion reports. Gate: every transition is explicit, reversible, evidenced, and human-approved.

## M8 — Future live canary

Out of scope. Gate to begin planning: qualified extended paper results, explicit user approval, reviewed live-risk policy and threat model, independent kill-switch validation, capital limits, legal and broker review, runbooks, and recovery drills.
