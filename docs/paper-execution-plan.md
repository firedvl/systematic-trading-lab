# Paper execution plan

M4 builds paper-only execution in guarded slices. Development and tests must not submit orders to
Alpaca. Live trading stays disabled.

## Authority sequence

```text
qualified strategy intent
  -> immutable paper authorization
  -> durable intent receipt
  -> independent risk decision
  -> staged order and deterministic client order ID
  -> paper-only broker adapter
  -> broker events
  -> position, cash, and open-order reconciliation
  -> append-only hash-chain evidence
```

One `execution.sqlite3` database owns paper authorization, intent, risk, order, broker-event,
reconciliation, emergency, and journal state. Each state mutation and its journal event share one
transaction. Decimal values use canonical strings. Broker input passes through one schema validator
and sanitizer; storage contains only normalized fields, never response bodies, headers, URLs,
credentials, or raw exception text. Hashes cover sanitized canonical events.

A protected operator workflow creates an immutable, expiring paper authorization after qualification.
It binds the candidate, strategy version and parameters, code revision, dataset and universe,
qualification evidence, account, risk-limit fingerprint, and expiry. Research and strategy code
cannot create, replace, or extend it.

## Required guards

Submission requires all of these facts at the last possible point before the network call:

- mode is exactly `paper` and the endpoint is exactly `https://paper-api.alpaca.markets`;
- an active, reviewed risk configuration fingerprint exists;
- one unexpired paper authorization matches the exact intent, account, code, data, qualification,
  and risk-limit fingerprints;
- account, positions, open orders, clock, quote, and session state are known and fresh;
- reconciliation is clean and emergency disable is clear;
- the intent is unexpired, unique, and approved by every independent risk gate;
- the account and symbol are allowlisted U.S. ETFs, the action can only maintain or reduce a
  long-only position, quantity is positive whole shares, and the order is a simple market or limit
  order with `day` time in force and `extended_hours=false`;
- per-order notional, buying power, cash, gross exposure, position, open-order, and order-rate gates
  include all staged, submitting, acknowledged, and submission-unknown commitments;
- risk approval, pending-capacity reservation, deterministic `client_order_id`, and one submitter
  claim were reserved atomically against exact snapshot and configuration generations.

Unknown or stale state rejects the operation without calling the adapter. Immediately before the
call, one worker must atomically claim `staged -> submitting`; no other worker may submit that order.
A timeout or crash from `submitting` enters `submission-unknown`; recovery queries Alpaca by
`client_order_id` before any retry. It never blindly resubmits.

## State and recovery

Intents move from `created` to `risk-approved`, `risk-rejected`, `expired`, or `cancelled`. Orders
move forward from `staged` through `submitting`, broker acknowledgement, and terminal fill,
rejection, expiration, or cancellation states. Unknown or out-of-order broker states block further
submission.

Broker snapshots may establish expected positions only through a separate reviewed baseline action.
After that, accepted fills advance expected state. Any broker drift persists emergency disable. A
protected manual clear requires operator identity and reason, valid configuration, journal proof, no
unresolved broker mutation, and stable clean reconciliation. Clearing never rebaselines positions.

Every broker mutation is journaled before the call. Submission, cancellation, and cancel-all track
their own unknown-outcome states. Cancel-all records and resolves each order separately. Retry is
allowed only after order lookup and full reconciliation prove the prior mutation did not take effect;
an unresolved or conflicting result remains disabled. Restart recovery first reads account,
positions, open orders, clock, and orders by deterministic client ID; nonterminal local state never
resumes blindly. Startup verifies the journal sequence and hash chain. A missing event, hash mismatch,
unsupported schema, or database corruption forces read-only emergency-disabled recovery; broker
snapshots cannot rebuild or overwrite the authoritative local journal. The local chain detects
partial corruption, not wholesale database replacement; any later malicious-tamper claim requires an
external or signed checkpoint.

## Implementation slices

1. Validated intents, configuration fingerprints, append-only hash-chain journal, and durable dedupe.
2. Protected paper authorization, independent risk context, reviewed limits, capacity reservations,
   risk decisions, and persistent emergency disable.
3. Delta construction, deterministic client IDs, reservation-bound staging, forward-only local
   lifecycle states, and atomic single-submitter claims now exist. No broker mutation method exists.
4. Normalized broker-event evidence has immutable exact dedupe, order binding, forward-state and
   cumulative-fill checks, and atomic local-state application. Conflicts restore emergency disable.
4. Paper-only Alpaca REST adapter behind a mockable protocol and an exact host/path allowlist.
5. Broker-event ingestion, reconciliation, restart recovery, and cancel-all evidence.
6. Fake-adapter end-to-end tests and paper operations runbooks.

Each slice gets its own review and cannot weaken earlier controls. Paper mode remains non-operational
until every M4 gate passes and an explicit reviewed risk configuration exists.

Slice 1 is complete: the broker-free store validates immutable intents, binds configuration and data
fingerprints, deduplicates exact replay across restarts, rejects changed keys, and verifies its
append-only hash chain and stored head at startup. It has no broker, risk, or network authority.

Slice 2 now has the pure independent risk envelope, persistent default-on emergency state, and
immutable paper authorization bound to passing qualification evidence, exact code, strategy, data,
account, limits, reviewer, reason, and expiry. Risk decisions now reload those durable records and
verified emergency state in one transaction before journaling the result. No financial limit is
committed, and emergency disable prevents approvals. Approved decisions now create immutable
cash, gross-exposure, order-notional, and order-count reservations in the same transaction as
the risk decision. Cancellation or rejection with zero cumulative fill releases the reservation
with a separate immutable journal event. Partial- and full-fill capacity remains reserved until
later reconciliation proves the new position state; this prevents early reuse against a stale
portfolio snapshot.

The slice 5 foundation now journals strict normalized local-expected and Alpaca-paper portfolio
snapshots, a reviewed flat baseline, and later clean or dirty comparison results. It fails on source,
account, cash, equity, buying power, account readiness, position, complete open-order state,
freshness, timing, authorization, or unresolved-mutation differences. Durable adapter provenance now
exists. Read-only stable-repeat readiness now requires the latest three distinct clean records and
the reviewed risk configuration's explicit separation interval. Emergency clear is now a bounded,
idempotent operator transition that recomputes and journals the proof in one transaction; dirty
reconciliation atomically restores disable. Reservation creation and zero-fill
cancellation/rejection release exist; fill reconciliation and broker writes remain absent.

The paper read adapter now permits only fixed-origin GET requests for account, positions, open orders,
and clock. It validates one expected account, an explicit symbol allowlist, account readiness and
buying power, positive whole-share positions, full supported open-order state, and UTC timestamps.
The caller supplies the reviewed clock freshness limit. The reader blocks
redirects and treats a full 500-order page as incomplete. Tests inject a mock transport; development
makes no Alpaca request. Only the reader's non-injected production path can atomically persist a
versioned exact-origin attestation with its normalized snapshot. Injected transports remain read-only,
and a caller-recorded snapshot cannot gain provenance later. Baselines and later reconciliation
refuse unattested paper snapshots.

## Alpaca contract

The current read adapter uses Trading API 2.0.1 paper endpoints for account, positions, clock, open
orders, and exact lookup by deterministic client order ID. The lookup remains fixed-origin, GET-only,
and schema validated. Only its production path can persist the normalized lookup as broker-event
evidence or a sanitized immutable 404 result for a `submission-unknown` order; injected transports
cannot create provenance. A read-only proof can bind the 404 to later complete clean reconciliation,
the active account, authorization, limits, reservation, emergency state, and absence of other
unresolved submissions. The proof remains review evidence and has no retry authority. A later
separately reviewed writer may add
submission and single-order
cancellation. Polling is authoritative; streaming may later reduce latency but cannot
replace reconciliation. Orders are whole-share, long-only,
nonextended-hours ETF `day` market or limit orders for one authorized account. Replace, fractional or
notional orders, shorts, bulk close, options, crypto, and account mutation stay out of scope.

Positive exact lookups now retain cumulative average fill price with cumulative filled quantity.
This supports later deterministic incremental position and gross cash calculations. It does not
invent fees, equity, or buying power, and filled reservations remain held until a separate expected
state authority and complete reconciliation can prove settlement.

The position-only authority now accepts an explicit flat baseline and records signed cumulative-fill
increments as immutable sorted position checkpoints in the broker-event transaction. It uses local
orders for symbol and side, links each checkpoint to its prior fingerprint, and rejects missing prior
fills, cross-authorization baselines, or negative positions. It does not replace a complete portfolio
snapshot or release filled capacity.

The next boundary now stores a successful positions-only settlement proof for the current lineage
head and one later complete production-attested snapshot. It requires exact positions, no broker
open orders, no nonterminal local orders, fresh post-fill observations, the same account and
baseline controls, and clear emergency state. The evidence binds but does not derive the observed
cash, equity, or buying power. It does not alter full reconciliation or release capacity.

A read-only settlement-capacity assessment enumerates the exact positive-fill reservations and the
proof's observed account values. The protected release path now rederives the complete attested
context under an immediate transaction and requires the same settlement proof, emergency generation,
and exclusive active reservation set. It rejects later order changes, stale evidence, unrelated
reservations, and changed replay. The individual releases and one immutable summary proof share the
transaction.

The current risk-input prerequisite journals production-attested IEX bid/ask quotes for every
reviewed symbol and the NYSE `/v3/clock` phase, provider time, next open, and next close. The bundle
binds one fresh adapter-attested portfolio snapshot, active paper authorization, account, and risk
configuration. The configuration supplies the exact symbols and freshness limit. Injected
transports can never persist provenance. Strategy PnL, drawdown, pricing policy, reservation
generation, risk admission, and capacity mutation remain separate.
The first derived input uses each complete-set IEX ask to value long positions and requires the
target symbol in the quote set. This avoids understating long exposure. The valuation remains
read-only, supplies no side-aware execution quote, and rejects a changed snapshot or any position
without a quote.
Risk evaluation requires both quote sides and current whole-share quantity. Buy-side gates use the
ask; sell-side gates use the bid. The later context builder must source them from the attested bundle
and preserve its evidence linkage.
Paper reader v2 retains Alpaca account `last_equity` inside immutable snapshot attestation. The
store derives account daily PnL from that value and the snapshot's current equity. Legacy v1
attestations remain verifiable but cannot supply the daily-loss input.
The risk-decision transaction derives the active reservation set using creation, expiry, and release
times. It binds the exact set and replaces caller pending totals; capacity mutation remains blocked
until strategy drawdown and the full attested context exist.
Reviewed limits now require a positive strategy-capital allocation and bind it into their fingerprint.
One immutable strategy-equity baseline can bind that allocation to the exact paper authorization and
flat reconciliation baseline. It grants no drawdown value, risk approval, or capacity authority.
A later immutable checkpoint can replay every accepted fill increment for that baseline, subtract
the reviewed fill-cost reserve, require the latest settlement proof, mark long positions at attested
IEX bids, and derive peak-linked strategy drawdown. A checkpoint remains read-only and does not make
the full `RiskContext` authoritative.
The read-only context builder now derives every `RiskContext` field from verified evidence in one
transaction and returns a fingerprinted provenance proof. It does not persist approval or mutate
capacity. The risk-decision transaction must rederive the same authorities before it can replace the
legacy caller context path.
The public risk-decision path now performs that rederivation under its immediate write transaction
and binds the proof into the decision. The caller-context path is private test scaffolding. The
settled-capacity path reuses the same derivation to release only capacity already represented by the
current attested portfolio. Neither path adds a broker writer.
A quantity-target submission preflight now reuses that derivation under the same immediate
transaction as the single-submitter claim. It requires paper mode, the fixed paper origin, an exact
current-share delta, all rechecked gates to pass, and the existing reservation to cover current
economics. The proof is immutable and replay-safe. Weight targets remain blocked because no reviewed
share-rounding rule exists. No transport or Alpaca write call exists.

Official references reviewed 2026-08-03:

- <https://docs.alpaca.markets/us/docs/paper-trading>
- <https://docs.alpaca.markets/us/docs/trading-api>
- <https://docs.alpaca.markets/us/reference/getallorders-1>
- <https://docs.alpaca.markets/reference/getorderbyclientorderid-1>
- <https://docs.alpaca.markets/us/reference/stocklatestquotes-1.md>
- <https://docs.alpaca.markets/us/reference/clock-1.md>
