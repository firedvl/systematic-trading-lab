# Threat model

Protected assets are credentials, capital, broker authority, market and portfolio state, immutable evidence, holdouts, risk controls, and qualification decisions. Trust boundaries include providers, environment configuration, local files, SQLite, future broker and TradingView inputs, agents, and CI.

Main threats are secret disclosure, path or artifact tampering, stale or conflicting data, lookahead leakage, overbroad research reads, replayed intents, duplicate orders, timeout-after-acceptance resubmission, wrong endpoint or mode, broker drift, forged or reordered broker events, control weakening, premature holdout reads, holdout reuse, and selective evidence. Current controls are no broker writes, offline default, rejected live selection, names-only `.env.example`, ignored runtime data, canonical hashes, atomic immutable artifacts, reconstructible catalog, validation and quarantine evidence, secret scan, review-separated protected controls, range-limited cataloged experiment reads, registry-derived qualification evidence, one-time holdout-run authorization, exact candidate binding, atomic authorization consumption before data access, protected result storage, one-time holdout read access, and a redirect-blocking fixed-origin GET-only paper-state reader with normalized response validation.

M4 must add an exact paper endpoint allowlist, immutable intent receipts, durable idempotency, independent
risk decisions, atomic pending-capacity reservation and single-submitter claims, protected paper
authorization, a strict order envelope, fresh account/position/order/clock/quote snapshots,
forward-only order state, broker-event dedupe, reconciliation, persistent emergency disable, and an
append-only hash-chain journal. An unknown submit, cancel, or cancel-all result is unsafe until lookup
and reconciliation resolve it. Only schema-validated normalized broker fields may be stored; raw
responses, headers, URLs, exception text, and credentials must not enter logs or journal payloads.

Residual risks: local filesystem access can replace local databases and artifacts; paper snapshot and lookup attestations prove the local adapter path and journal binding, not resistance to hostile local code or wholesale database replacement; production paper mutation transport and its network failure surface have not been reviewed; no production risk-limit values, write-enablement controls, paper supervisor, or sustained operating evidence exist; the fixture calendar handles weekdays rather than exchange holidays; dependency provenance is not yet attested; Alpaca paper fills do not model market impact, queue position, or full liquidity. Reassess and approve [paper-write-readiness.md](paper-write-readiness.md) before enabling paper writes. Reassess separately before webhooks, remote artifact storage, or any live planning.
