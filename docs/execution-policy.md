# Execution policy

Backtests use explicit decision, order, and earliest-fill timestamps and a versioned conservative cost model. The current model applies configurable basis-point slippage and commission and fills a signal only on the next available bar for that symbol. An order never fills before it exists; rejected orders never change state. Do not assume perfect fills or silently omit spread, slippage, fees, latency, session rules, liquidity, partial fills, rejections, or price movement.

Portfolio backtests require the full symbol set in every session. The strategy sees immutable history only through the current session close. A nonempty decision must target every session symbol exactly once. The simulator rejects the whole target set for mismatched symbols, invalid weights, total weight above one, pending orders, or missing future fills, and records one rejection event per target. Accepted targets enter the same conservative next-bar fill model; position reductions run before buys at a shared open so sale proceeds can fund the allocation without symbol-order bias. This boundary creates no broker authority.

Paper flow is strategy intent, protected paper authorization, independent risk, order manager, broker adapter, events, reconciliation, and append-only evidence. Intents require a strategy version, symbol, decision time, target or whole-share quantity, reason, source-data fingerprint, reference price, expiry, and idempotency key. Exact duplicate delivery returns the existing receipt; reuse of a key with different content blocks execution. Authorization binds one qualified candidate and exact strategy, code, data, account, evidence, limits, and expiry; research code cannot grant it.

Only the Alpaca paper host may be selected. Long-only whole-share deltas produce one deterministic
broker-free client order ID per intent and target/current quantity pair. Staging requires the exact
active capacity reservation and matching immutable intent. One submitter ID is claimed atomically
with `staged -> submitting`; later callers cannot claim or bypass that transition.
Cancellation or rejection releases reserved capacity in the same transaction as the terminal local
order transition. Filled orders retain capacity until reconciliation proves the resulting position.
A separate read-only adapter now permits only `GET /v2/account`, `/v2/positions`, `/v2/orders`, and
`/v2/clock` at `https://paper-api.alpaca.markets`. It blocks redirects, rejects unexpected accounts,
symbols, values, and open-order states, and fails if a 500-order response cannot prove completeness.
It exposes no submit, cancel, replace, close-position, or other mutation method.
A timeout or crash after submission requires lookup by that ID before retry. Broker events now have
a broker-free evidence store that deduplicates exact provider event identity and normalized content,
checks forward state and cumulative fill quantity, and binds each event to one known local order.
Storage accepts only schema-validated normalized fields and excludes raw bodies, headers, URLs, and
exception text. Applying events to local lifecycle state remains a separate protected transition.
Conflicting duplicates, unknown statuses, out-of-order transitions, or position drift trigger
emergency disable. Each submit, cancel, and cancel-all mutation is journaled before the call and has
an unknown-outcome state resolved by lookup and reconciliation before retry. No order submission is
implemented yet. The broker-free intent store is implemented: it validates immutable intent content,
persists each new intent and journal event in one transaction, returns the same receipt for exact
replay, and fails startup when its sequence, hash chain, stored head, schema, or database is invalid.

The broker-free reconciliation boundary accepts only normalized complete local-expected or
Alpaca-paper snapshots. It compares exact account, cash, equity, buying power, account readiness,
whole-share positions, full supported open-order descriptors, separate account/position/order
observation times, and unresolved mutation count. Wrong
source roles, stale or future observations, or any mismatch produce explicit dirty reasons. Snapshots,
flat baseline creation, and later results now share the execution journal. The baseline binds active
paper authorization and reviewed freshness limits and must not predate its recorded flat snapshots.
The reader binds its version, exact paper origin, completion time, and normalized snapshot in an
attestation. The execution database stores that snapshot and attestation with separate journal events
in one transaction. Flat baselines and later reconciliation reject unattested Alpaca-paper snapshots.
No attestation or reconciliation result can clear emergency disable by itself. A bounded operator
clear request is separately journaled and idempotent, binds the recomputed proof, and changes
emergency state in the same immediate transaction. Dirty reconciliation atomically re-disables it.
Read-only clear readiness requires the latest three distinct adapter-attested reconciliation records
to be clean and separated by the stability interval in the reviewed risk configuration. It rechecks
freshness, authority, configuration, and emergency generation. Dirty evidence resets the streak.
