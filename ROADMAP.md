# Roadmap

Each milestone requires passing formatting, lint, typing, tests, secret checks, documentation review, and every listed gate. A later milestone does not weaken an earlier gate.

## M0 — Foundation and policy

Package, safe configuration, CLI, CI, persistent documentation, initial domain types, deterministic fingerprints, storage layout, and test infrastructure. Gate: clean setup; CLI and checks pass; runtime defaults offline; live is rejected; no secrets or generated data are tracked.

## M1 — Market data

Provider-neutral acquisition, Alpaca historical adapter, fixtures, immutable raw and normalized storage, catalog, validation and quarantine, calendar and corporate-action policy, and data CLI. Gate: adjusted daily data for the fixed universe is reproducible; provider corrections create versions; invalid data cannot silently enter a dataset; catalog reconstruction works. The current slice implements only the offline fixture path.

## M2 — Backtester and baselines

Timestamp semantics, portfolio accounting, deterministic orders and fills, conservative versioned costs, ledgers, metrics, benchmarks, and simple baseline strategies. Gate: no lookahead; accounting and order invariants pass; fixed transactions cannot benefit from higher costs; reports reproduce.

## M3 — Experiments and qualification

Durable campaigns and experiments, restart recovery, split controls, walk-forward and robustness checks, comparisons, gate-based qualification, and protected holdout workflow. Gate: failures remain evidence; ordinary research cannot read holdout results; no single score can hide a disqualifying failure.

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
