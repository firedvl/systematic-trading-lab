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
It now also requires a positive strategy-capital allocation. The allocation enters the exact risk
configuration fingerprint; the repository supplies no production value.
It also requires an explicit nonnegative strategy fill-cost reserve in basis points. Zero is never
implicit. The reviewed value enters the same fingerprint and is a conservative accounting policy,
not broker fee evidence.

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

The terminal-replay recovery clear is separate from ordinary flat reconciliation. It exists only for
the fixed false positive where a repeated filled, canceled, or rejected exact lookup kept identical
terminal facts. Recovery requires a later production lookup plus three stable post-emergency account
snapshots with exact fill-derived cash, expected positions, no open orders, and fresh attestation. It
cannot clear another emergency reason or authorize a mutation.

Position settlement alone does not authorize capacity reuse. The protected release path rederives
the complete attested risk context under an immediate transaction and requires its current
settlement proof and emergency generation to match. It releases only the exact exclusive active
positive-fill reservation set, rejects later order mutations or unrelated active reservations, and
journals the individual releases and immutable summary proof atomically.

Immutable risk-input evidence now supplies a complete IEX bid/ask quote set and NYSE market-clock
state bound to a fresh production-attested portfolio snapshot, active paper authorization, and risk
configuration. This is necessary but not sufficient: no derived context is authoritative until
strategy PnL, drawdown, pricing basis, and the exact active-reservation set also have durable
provenance.
The configured snapshot-age limit also bounds provider timestamps on either side of the local
observation time. This tolerates small clock skew without accepting arbitrarily future evidence.
Long-only exposure valuation uses each attested IEX ask for held-symbol notionals and gross
exposure. The ask basis is conservative; it is not a side-aware execution quote or a claim about
liquidation value or realized PnL.
Risk evaluation now carries both quote sides and current whole-share quantity. It checks acquisition
price deviation at the ask and reduction price deviation at the bid. Quantity-target order notional
uses that executable side; projected long exposure remains ask-valued.
Paper snapshot attestation v2 also retains Alpaca `last_equity`. Account daily PnL is derived as
attested current equity minus prior-close equity, with both snapshot and attestation fingerprints.
This supplies the daily-loss input only; it does not substitute for per-strategy drawdown evidence.
An immutable strategy-equity baseline now binds that reviewed allocation to one paper authorization,
flat reconciliation baseline, account, strategy identity and version, operator, reason, and time.
Missing provenance fails closed. One post-clear, production-attested, clean flat reconciliation may
create the initial zero-equity checkpoint. It contains no fill, position, cost, or execution lineage;
cash, equity, and peak equity equal the reviewed capital allocation and drawdown is zero. Flat
checkpoints may chain fresh settlement and quote evidence only while no execution artifact exists.
This refreshes expiring observations without fabricating fills or resetting strategy state. Later
immutable strategy-equity checkpoints replay accepted cumulative-fill increments from that flat
checkpoint, apply the reviewed cost reserve to buys and sells, and mark settled long positions at
production-attested IEX bids. Each checkpoint binds the latest position-settlement proof, quote
evidence, fill-event set, prior checkpoint, equity peak, and derived drawdown. A later fill requires
new settlement before another checkpoint. The lineage remains read-only and grants no risk approval
or capacity release.
Risk decisions now derive the temporal active reservation set inside their immediate transaction.
They replace caller pending-capacity totals and bind the exact reservation IDs, fingerprints,
aggregates, and count. A reservation is active only after creation, before expiry, and before any
effective release timestamp.
A read-only attested-context builder now verifies all authorities in one database transaction. It
derives account equity, cash, buying power, ask-valued exposure, target bid and ask, current quantity,
open and recent order counts, active reservations, account daily PnL, strategy drawdown, market
session, observation times, and emergency state. Its proof binds the exact authorization, limits,
snapshot, adapter attestation, risk input, settlement, strategy-equity checkpoint, daily-PnL
evidence, reservation set, and emergency generation. It writes nothing and grants no risk decision
or capacity authority.
The public risk-decision path now accepts only an intent, authorization, reviewed limits, and
evaluation time. It rederives that attested context under the same immediate transaction that
journals the decision and any capacity reservation, then binds the context-provenance fingerprint
into the decision. Direct caller financial context is private test scaffolding. Exact replay excludes
the intent's own reservation and returns the original receipt; a changed second decision for the same
intent fails closed.
Settled-capacity replay binds the authorization, settlement proof, symbol, reviewed-limit
fingerprint, attested-context proof, exact active reservation set, and release time. Exact replay is
idempotent; any changed request fails closed. A positive-fill reservation may expire before this
proof completes. The release then requires that no unrelated reservation remains active and records
the expired reservation as settled rather than treating it as pending capacity.
Immediately before a quantity-target order can enter `submitting`, preflight rederives the complete
attested context under the submitter-claim transaction and reevaluates every gate without counting
the order's own reservation twice. The staged delta must match current shares, and current order,
cash, and gross-exposure amounts cannot exceed the existing reservation. The immutable proof binds
the authorization, limits, intent, delta, submitter, paper origin, and rechecked context. No broker
transport exists.
Only the process that creates the preflight may invoke the fake submission callable. Existing proof
means an attempt may already have reached the broker boundary, so replay requires lookup and full
reconciliation. A failed call or invalid normalized result enters `submission-unknown`; it never
releases capacity or retries.
The Alpaca paper order adapter is test-only because its transport is mandatory and injected. It
permits only the fixed paper `POST /v2/orders` request, validates the complete supported order echo,
and returns normalized broker evidence. It has no production network fallback or live origin.
Cancellation intent is a one-shot record separate from broker order state. It binds the latest
nonterminal event and never releases capacity. Unknown outcome remains unresolved until a later
authoritative terminal event or reconciliation proves the result; no retry path exists.
The injected cancellation adapter has no production fallback and permits only the fixed paper
single-order DELETE target. Empty acceptance grants no capacity release. Timeout or invalid response
records unknown outcome, and the immutable attempt blocks another call.
Cancel-all is plan evidence only. It binds the complete current nonterminal local order set but adds
no bulk mutation authority. Each order keeps its own capacity, attempt, unknown outcome, and terminal
resolution.
Cancel-all consumption never shares authority across orders. Each item rechecks its planned event
inside its attempt transaction. Prior attempts are skipped, stale bindings are not called, and one
unknown outcome does not erase or retry other progress.
