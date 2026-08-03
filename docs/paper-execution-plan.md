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
3. Delta order construction, deterministic client IDs, and guarded order lifecycle.
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
committed, and emergency disable prevents approvals. Capacity reservations and emergency clear wait
for stable reconciliation evidence rather than accepting a placeholder proof.

The slice 5 foundation now journals strict normalized local-expected and Alpaca-paper portfolio
snapshots, a reviewed flat baseline, and later clean or dirty comparison results. It fails on source,
account, cash, equity, buying power, account readiness, position, complete open-order state,
freshness, timing, authorization, or unresolved-mutation
differences. Adapter provenance, stable repeat evidence, and emergency-clear authority remain absent.

The paper read adapter now permits only fixed-origin GET requests for account, positions, open orders,
and clock. It validates one expected account, an explicit symbol allowlist, account readiness and
buying power, positive whole-share positions, full supported open-order state, and UTC timestamps.
The caller supplies the reviewed clock freshness limit. The reader blocks
redirects and treats a full 500-order page as incomplete. Tests inject a mock transport; development
makes no Alpaca request. Persisted adapter provenance remains the next boundary.

## Alpaca contract

The current read adapter uses Trading API 2.0.1 paper endpoints for account, positions, clock, and
open orders. A later separately reviewed writer may add order lookup by client ID, submission, and
single-order cancellation. Polling is authoritative; streaming may later reduce latency but cannot
replace reconciliation. Orders are whole-share, long-only,
nonextended-hours ETF `day` market or limit orders for one authorized account. Replace, fractional or
notional orders, shorts, bulk close, options, crypto, and account mutation stay out of scope.

Official references reviewed 2026-08-03:

- <https://docs.alpaca.markets/us/docs/paper-trading>
- <https://docs.alpaca.markets/us/docs/trading-api>
- <https://docs.alpaca.markets/us/reference/getallorders-1>
