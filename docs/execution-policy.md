# Execution policy

Backtests use explicit decision, order, and earliest-fill timestamps and a versioned conservative cost model. The current model applies configurable basis-point slippage and commission and fills a signal only on the next available bar for that symbol. An order never fills before it exists; rejected orders never change state. Do not assume perfect fills or silently omit spread, slippage, fees, latency, session rules, liquidity, partial fills, rejections, or price movement.

Portfolio backtests require the full symbol set in every session. The strategy sees immutable history only through the current session close. A nonempty decision must target every session symbol exactly once. The simulator rejects the whole target set for mismatched symbols, invalid weights, total weight above one, pending orders, or missing future fills, and records one rejection event per target. Accepted targets enter the same conservative next-bar fill model; position reductions run before buys at a shared open so sale proceeds can fund the allocation without symbol-order bias. This boundary creates no broker authority.

Paper flow is strategy intent, protected paper authorization, independent risk, order manager, broker adapter, events, reconciliation, and append-only evidence. Intents require a strategy version, symbol, decision time, target or whole-share quantity, reason, source-data fingerprint, reference price, expiry, and idempotency key. Exact duplicate delivery returns the existing receipt; reuse of a key with different content blocks execution. Authorization binds one qualified candidate and exact strategy, code, data, account, evidence, limits, and expiry; research code cannot grant it.

Only the Alpaca paper host may be selected. Each staged order has one deterministic client order ID.
A timeout or crash after submission requires lookup by that ID before retry. Broker events are
deduplicated by provider event identity and sanitized payload hash. Broker storage accepts only
schema-validated normalized fields and excludes raw bodies, headers, URLs, and exception text.
Conflicting duplicates, unknown statuses, out-of-order transitions, or position drift trigger
emergency disable. Each submit, cancel, and cancel-all mutation is journaled before the call and has
an unknown-outcome state resolved by lookup and reconciliation before retry. No order submission is
implemented yet. The broker-free intent store is implemented: it validates immutable intent content,
persists each new intent and journal event in one transaction, returns the same receipt for exact
replay, and fails startup when its sequence, hash chain, stored head, schema, or database is invalid.

The broker-free reconciliation boundary accepts only normalized complete local-expected or
Alpaca-paper snapshots. It compares exact account, cash, equity, whole-share positions, open client
order IDs, separate account/position/order observation times, and unresolved mutation count. Wrong
source roles, stale or future observations, or any mismatch produce explicit dirty reasons. A pure
result is not durable reconciliation evidence and cannot clear emergency disable.
