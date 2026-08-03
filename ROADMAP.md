# Roadmap

Each milestone requires passing formatting, lint, typing, tests, secret checks, documentation review, and every listed gate. A later milestone does not weaken an earlier gate.

## M0 — Foundation and policy

Package, safe configuration, CLI, CI, persistent documentation, initial domain types, deterministic fingerprints, storage layout, and test infrastructure. Gate: clean setup; CLI and checks pass; runtime defaults offline; live is rejected; no secrets or generated data are tracked.

## M1 — Market data

Provider-neutral acquisition, Alpaca historical adapter, fixtures, immutable raw and normalized storage, catalog, validation and quarantine, calendar and corporate-action policy, and data CLI. Gate: adjusted daily data for the fixed universe is reproducible; provider corrections create versions; invalid data cannot silently enter a dataset; catalog reconstruction works. The fixed-universe gate now covers XNYS calendar validation, raw JSONL and Parquet artifacts, deterministic fixtures, read-only paginated Alpaca acquisition, immutable correction lineage, cross-provider version isolation, provider-adjusted action handling, rejection of unadjusted data, and issuer-sourced point-in-time membership bound into dataset and experiment provenance. A local unadjusted corporate-action processor remains out of scope for this slice.

## M2 — Backtester and baselines

Timestamp semantics, portfolio accounting, deterministic orders and fills, conservative versioned costs, ledgers, metrics, benchmarks, and simple baseline strategies. The current slice covers explicit next-bar fills, cash accounting, bps slippage and commission, decision/order/trade/equity ledgers, cash, buy-and-hold, fixed-weight, moving-average, and momentum baselines, cash-relative report comparisons, deterministic fixture reports, and a separate complete-session boundary for atomic multi-symbol portfolio targets. Gate: no lookahead; accounting and order invariants pass; fixed transactions cannot benefit from higher costs; reports reproduce. Walk-forward evaluation and qualification remain M3.

## M3 — Experiments and qualification

Durable campaigns and experiments, restart recovery, split controls, walk-forward and robustness checks, comparisons, gate-based qualification, and protected holdout workflow. The current slice covers search budgets, pending/running/completed/failed lifecycle, heartbeats and stale-run recovery, explicit split classification, hidden holdout metrics with logged access events, approved/unapproved disqualifying gates, range-limited registry-backed runs on cataloged datasets, chronological walk-forward candidates, cost and delayed-fill sensitivity candidates, bounded run and comparison CLI commands, and score-free comparison reports. Provider campaigns retain superseded methods and corrected reruns. Report schema v2 adds risk-adjusted return, exposure, session and instrument concentration, and SPY regime metrics; the latest campaign adds parameter neighborhoods. A strict machine-readable threshold proposal records every gate and rationale as unapproved. A registry-backed evidence manifest reproduces the aggregate metrics and gate failures in an immutable report without loading bars. One-time stored authorization replaces the raw holdout-creation flag and binds an exact qualified candidate to one post-validation holdout record. The controlled runner consumes that authority before reading data, scans only the authorized Parquet timestamp range, retains failures, and keeps completed metrics behind the separate read event. Human approval and a qualifying candidate remain; no holdout run is authorized. Gate: failures remain evidence; ordinary research cannot read holdout results; no single score can hide a disqualifying failure.

## M4 — Alpaca paper execution

Paper-only adapter, intents, independent risk, order management, idempotency, broker events, reconciliation, operational journal, and emergency disable. Gate: unknown or stale state blocks writes; duplicate intents are harmless; reconciliation discrepancies stop execution; live endpoints cannot be selected.

## M5 — Equivalence and sustained paper operation

Replay/shadow/paper comparison, supervisor recovery, disconnect and stale-data handling, and sustained paper campaign. Gate: discrepancies are explained; recovery drills pass; operating limits hold for the approved observation period.

## M6 — Bounded automated research

Machine-readable specifications, approved strategy families, bounded candidate generation, search accounting, isolated runs, and evidence-producing pull requests. Gate: all candidates remain recorded; agents cannot alter protected controls or promote strategies.

## M7 — Controlled continuous improvement

Scheduled sealing and reevaluation, champion/challenger lifecycle, shadow-to-paper advancement, drift detection, rollback, and reviewed promotion reports. Gate: every transition is explicit, reversible, evidenced, and human-approved.

## M8 — Future live canary

Out of scope. Gate to begin planning: qualified extended paper results, explicit user approval, reviewed live-risk policy and threat model, independent kill-switch validation, capital limits, legal and broker review, runbooks, and recovery drills.
