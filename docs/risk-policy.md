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
`RiskLimits` also carries a positive reviewed reconciliation-stability interval. Clear readiness has
no default interval and cannot substitute the snapshot freshness limit.

Paper authorization is a separate immutable, expiring operator record bound to one qualified
candidate, strategy configuration, code revision, dataset and universe, qualification evidence,
account, and risk-limit fingerprint. Research code cannot issue or alter it. The initial executable
envelope is allowlisted U.S. ETFs, positive whole-share quantities, long-only position changes,
simple `day` market or limit orders, and `extended_hours=false`. The reviewed limits must cover
account, symbol, per-order notional, buying power, cash, position, gross exposure, open orders, and
order rate.

The broker-free risk model now implements this envelope without supplying any financial value. Each
`RiskLimits` value is explicit, reviewed, effective, and expiring. Evaluation binds the complete
context and configuration fingerprints and returns every failed gate plus the cash, order-notional,
and gross-exposure capacity a later transaction must reserve. A risk decision alone grants no paper
or broker authority. The execution database initializes emergency disable as active and journals it;
missing or changed emergency state fails closed. Clearing it remains unavailable until the protected
authorization, reconciliation, operator, and journal-proof checks exist.

Paper authorization is now a separate immutable journaled record. It accepts only fingerprint-valid
qualification evidence whose approved gates all pass, and it binds the evidence candidate's strategy,
parameters, code revision, dataset, and universe to one account and exact risk configuration period.
Creating this record does not clear emergency disable, reserve capacity, stage an order, or contact a
broker.

Durable evaluation now reloads the immutable intent and authorization in one immediate transaction
and replaces the supplied emergency flag with verified persistent state. It journals rejected
decisions. Approval is explicitly blocked until clean reconciliation can support a journaled emergency
clear and the same transaction can reserve pending cash, order notional, gross exposure, and order
count. This prevents a caller or test-only flag from creating unproven capacity authority.

The read-only clear-readiness proof selects the latest three evidence records for one baseline. All
three must use distinct adapter-attested snapshots, be clean with no unresolved mutation, and have
strictly increasing comparison and observation times separated by the reviewed stability interval.
It rechecks current snapshot freshness, active exact authorization and limits, and the current
emergency generation. A dirty latest sample resets readiness. The proof cannot clear emergency
state by itself. A separate operator clear request is bounded, idempotent, and journaled; it
recomputes the proof in the same immediate transaction that changes emergency state. A dirty
reconciliation journals and restores disable atomically.

Position settlement does not authorize capacity reuse. Until risk context is derived from durable
production-attested account, position, order, quote, and clock evidence, settlement-capacity
assessment remains read-only and reports `context-provenance-missing`.

Immutable risk-input evidence now supplies a complete IEX bid/ask quote set and NYSE market-clock
state bound to a fresh production-attested portfolio snapshot, active paper authorization, and risk
configuration. This is necessary but not sufficient: no derived context is authoritative until
strategy PnL, drawdown, pricing basis, and the exact active-reservation set also have durable
provenance.
Long-only exposure valuation uses each attested IEX ask for held-symbol notionals and gross
exposure. The ask basis is conservative; it is not a side-aware execution quote or a claim about
liquidation value or realized PnL.
Risk evaluation now carries both quote sides and current whole-share quantity. It checks acquisition
price deviation at the ask and reduction price deviation at the bid. Quantity-target order notional
uses that executable side; projected long exposure remains ask-valued.
Paper snapshot attestation v2 also retains Alpaca `last_equity`. Account daily PnL is derived as
attested current equity minus prior-close equity, with both snapshot and attestation fingerprints.
This supplies the daily-loss input only; it does not substitute for per-strategy drawdown evidence.
