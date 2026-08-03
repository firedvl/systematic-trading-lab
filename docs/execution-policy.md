# Execution policy

Backtests use explicit decision, order, and earliest-fill timestamps and a versioned conservative cost model. An order never fills before it exists; rejected orders never change state. Do not assume perfect fills or silently omit spread, slippage, fees, latency, session rules, liquidity, partial fills, rejections, or price movement.

Later paper flow is strategy intent, independent risk, order manager, broker adapter, events, reconciliation, and append-only evidence. Intents require a strategy version, symbol, decision time, target or quantity, reason, source-data fingerprint, expiry, and idempotency key. No order submission is implemented now.
