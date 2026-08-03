# Risk policy

Current permitted execution authority is none. Offline research is the default; paper is a declared future mode but no broker writer exists. Live remains disabled.

Before paper execution, independent risk must enforce position and gross-exposure limits, daily loss and strategy drawdown, order-rate limits, stale and duplicate rejection, expected broker positions, price movement, regular sessions, emergency disable, cancel-all, and append-only events. Unknown configuration, data, broker state, or portfolio state rejects the operation. Research agents cannot weaken these controls.

Risk evaluation owns approval, but never broker communication. One database transaction must reserve
the deterministic client order ID, pending cash, exposure, position, open-order, and order-rate
capacity against exact snapshot and configuration generations. It must also atomically claim one
submitter before the network call. Pending capacity includes staged, submitting, acknowledged, and
submission-unknown orders. The order manager must recheck mode, endpoint, authorization, freshness,
reconciliation, and emergency state immediately before submission. A risk approval is invalid after
any bound context or configuration fingerprint changes.

Executable limits require their own reviewed configuration. No library default is an approved
financial limit; missing, malformed, inactive, or mismatched limits reject every intent.

Paper authorization is a separate immutable, expiring operator record bound to one qualified
candidate, strategy configuration, code revision, dataset and universe, qualification evidence,
account, and risk-limit fingerprint. Research code cannot issue or alter it. The initial executable
envelope is allowlisted U.S. ETFs, positive whole-share quantities, long-only position changes,
simple `day` market or limit orders, and `extended_hours=false`. The reviewed limits must cover
account, symbol, per-order notional, buying power, cash, position, gross exposure, open orders, and
order rate.
