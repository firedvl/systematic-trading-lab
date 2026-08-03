# Threat model

Protected assets are credentials, capital, broker authority, market and portfolio state, immutable evidence, holdouts, risk controls, and qualification decisions. Trust boundaries include providers, environment configuration, local files, SQLite, future broker and TradingView inputs, agents, and CI.

Main threats are secret disclosure, path or artifact tampering, stale or conflicting data, lookahead leakage, replayed intents, duplicate orders, wrong endpoint or mode, broker drift, control weakening, holdout reuse, and selective evidence. Current controls are no broker code, offline default, rejected live selection, names-only `.env.example`, ignored runtime data, canonical hashes, atomic immutable artifacts, reconstructible catalog, validation and quarantine evidence, secret scan, and review-separated protected controls.

Residual risks: local filesystem access can replace both data and manifests; the fixture calendar handles weekdays rather than exchange holidays; dependency provenance is not yet attested. Reassess before Alpaca access, webhooks, paper writes, or remote artifact storage.
