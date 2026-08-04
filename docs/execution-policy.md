# Execution policy

Backtests use explicit decision, order, and earliest-fill timestamps and a versioned conservative cost model. The current model applies configurable basis-point slippage and commission and fills a signal only on the next available bar for that symbol. An order never fills before it exists; rejected orders never change state. Do not assume perfect fills or silently omit spread, slippage, fees, latency, session rules, liquidity, partial fills, rejections, or price movement.

Portfolio backtests require the full symbol set in every session. The strategy sees immutable history only through the current session close. A nonempty decision must target every session symbol exactly once. The simulator rejects the whole target set for mismatched symbols, invalid weights, total weight above one, pending orders, or missing future fills, and records one rejection event per target. Accepted targets enter the same conservative next-bar fill model; position reductions run before buys at a shared open so sale proceeds can fund the allocation without symbol-order bias. This boundary creates no broker authority.

Paper flow is strategy intent, protected paper authorization, independent risk, order manager, broker adapter, events, reconciliation, and append-only evidence. Intents require a strategy version, symbol, decision time, target or whole-share quantity, reason, source-data fingerprint, reference price, expiry, and idempotency key. Exact duplicate delivery returns the existing receipt; reuse of a key with different content blocks execution. Authorization binds one qualified candidate and exact strategy, code, data, account, evidence, limits, and expiry; research code cannot grant it.

Only the Alpaca paper host may be selected. Long-only whole-share deltas produce one deterministic
broker-free client order ID per intent and target/current quantity pair. Staging requires the exact
active capacity reservation and matching immutable intent. One submitter ID is claimed atomically
with `staged -> submitting`; later callers cannot claim or bypass that transition.
Cancellation or rejection releases reserved capacity in the same transaction as the terminal local
order transition only when cumulative fill is zero. Any positive fill retains capacity until
reconciliation proves the resulting position.
A separate read-only adapter permits only `GET /v2/account`, `/v2/positions`, `/v2/orders`,
`/v2/clock`, and exact `GET /v2/orders:by_client_order_id` at
`https://paper-api.alpaca.markets`. It blocks redirects, rejects unexpected accounts,
symbols, values, and open-order states, and fails if a 500-order response cannot prove completeness.
It exposes no submit, cancel, replace, close-position, or other mutation method.
A timeout or crash after submission requires lookup by that ID before retry. Broker events now have
a broker-free evidence store that deduplicates exact provider event identity and normalized content,
checks forward state, cumulative fill quantity, and cumulative average fill price, and binds each
event to one known local order. Zero fill requires no price; a positive fill requires a positive
finite average, and later cumulative notional cannot move backward. This evidence does not yet
advance complete expected portfolio state or release filled capacity. An explicit baseline-bound
path atomically derives each signed fill increment from the immutable local order and stores a
sorted immutable expected-position checkpoint linked to its prior generation. It does not infer
cash, equity, buying power, fees, or settlement from fill evidence.
The current lineage head can be bound to a later complete production-attested paper snapshot as
immutable position-settlement evidence. The snapshot must match exact expected positions, contain
no open orders, follow every local order transition, remain fresh, and find no nonterminal local
order. Emergency state must be clear. Cash, equity, and buying power remain broker observations;
the proof neither compares them to invented local values nor releases filled capacity.
A read-only capacity assessment maps that proof to the exact positive-fill reservations and observed
cash, equity, and buying power. A separate protected mutation now rederives the complete attested
context under an immediate transaction, requires the settlement proof and exclusive active
reservation set to match, and journals their releases atomically. Later order changes, stale
evidence, changed replay, or unrelated active reservations fail closed.
The production-only risk-input reader now binds one fresh attested portfolio snapshot and active
paper authorization to a complete sorted IEX latest-quote set and current NYSE market-clock
evidence. The fixed-origin GET-only reads use the authorized risk configuration's symbols and
freshness limit. The store journals normalized evidence without raw responses or credentials. This
input bundle does not derive strategy PnL, drawdown, a risk context, approval, or capacity authority.
Long-only risk valuation uses the attested IEX ask for every held symbol and requires the target
symbol in the quote set. This produces deterministic conservative symbol notional and gross
exposure without trusting caller prices. It does not supply a side-aware execution quote, replace
broker account values, or supply strategy performance metrics.
The risk model separately selects the ask for position increases and the bid for reductions. This
prevents a favorable ask from hiding an adverse sell price. It retains ask-valued projected long
exposure.
Production paper snapshot attestation v2 retains the account's prior-close equity. A read-only
derivation binds current equity, prior-close equity, daily PnL, the snapshot fingerprint, and the
attestation fingerprint. It grants no risk or execution authority.
Strategy equity starts from the reviewed authorization-bound capital baseline. Immutable checkpoints
replay accepted fill notional, subtract the explicit reviewed fill-cost reserve on both sides, and
mark the latest settled long positions at attested IEX bids. The reserve is not a claim about actual
broker fees. Checkpoints bind peak lineage and derive strategy drawdown but grant no risk approval or
capacity authority.
Risk decisions also derive and fingerprint the exact temporal active reservation set in the same
transaction. Caller-supplied pending totals are replaced, and later releases cannot alter an earlier
evaluation.
The complete read-only context builder now composes the attested portfolio, quote, clock, daily-PnL,
strategy-equity checkpoint, settlement, reservation, authorization, limits, and emergency evidence
inside one read transaction. The resulting proof changes no state and cannot approve or release
capacity. A later risk-decision path must rederive it in its own immediate transaction.
That transaction-bound path now exists. It accepts no caller account, quote, PnL, drawdown, order,
reservation, session, or emergency values. The exact provenance fingerprint enters the immutable
risk decision. One intent can receive only one exact decision; changed replay fails closed.
The same transaction-bound context permits one narrow post-settlement mutation: replacing the
exclusive positive-fill reservation set after its exposure appears in the current attested
portfolio. It grants no broker-write authority.
A separate submission preflight accepts only quantity-target intents. Under one immediate
transaction it rederives the attested context without the order's own reservation, reevaluates every
risk gate, requires the staged delta to match current shares and the existing reservation to cover
current economics, then binds the proof into the atomic submitter claim. Paper mode and the fixed
paper origin are mandatory. Weight targets remain blocked until policy defines share rounding.
The fake-only coordinator consumes a newly created preflight once. It accepts normalized broker
evidence from an injected callable and records it through the existing broker-event authority. Any
call or evidence failure moves the order to `submission-unknown`. Existing preflight evidence blocks
another call, including after a process restart, until separate reconciliation resolves the outcome.
The injected submission adapter has no default network function. It constructs only the fixed paper
`POST /v2/orders` target and the supported simple whole-share day-market body. It requires the
response to echo the exact client ID, symbol, side, quantity, type, and order envelope before it
creates normalized broker evidence. HTTP and parsing failures expose no response body or credentials.
Cancellation uses a separate immutable mutation record so broker fill state remains authoritative.
The request binds the latest nonterminal broker event, authorization, operator, reason, fixed paper
origin, and time. Unknown outcome is separate sanitized evidence and never permits retry or capacity
release. A later terminal broker event resolves the pending attempt through the existing order and
capacity rules.
The cancellation coordinator lets only the process that creates the attempt invoke the injected
adapter. The adapter permits only the fixed paper `DELETE /v2/orders/{broker_order_id}` target and an
empty acceptance response. Acceptance does not claim cancellation succeeded. Timeout or invalid
response records unknown outcome; existing attempts block every repeat call.
Cancel-all is an immutable plan over the exact sorted local nonterminal order set and each order's
latest broker-event fingerprint. It never calls Alpaca's bulk endpoint. Planning creates no cancel
authority; every order must still use the single-order attempt, unknown-outcome, lookup, and terminal
event controls.
Cancel-all consumption rechecks each planned broker-event fingerprint inside the same transaction
that creates its one-shot attempt. It continues after per-order unknown outcomes, reports stale
bindings without calling, and treats existing attempts as durable prior progress. Restart cannot
repeat any prior call.
The local order store exposes a read-only, journal-verified list of `submission-unknown` orders so a
recovery worker can obtain the exact deterministic client IDs without changing execution state.
The production exact-lookup path can store a sanitized immutable 404 result for one such order only
after a separate account read matches the authorized account. The evidence binds that account, the
fixed paper origin and path, adapter version, and observation time; it does not change order state,
release capacity, clear emergency state, or permit retry.
The read-only recovery proof requires that 404 plus a later complete adapter-attested clean
reconciliation for the same active account, authorization, and reviewed limits. It also requires
the reservation and emergency-clear state to remain valid, the order to remain unknown, and no
other submitting or unknown order. The proof is review evidence only and grants no retry authority.
Successful production exact lookups now store separate immutable provenance for the normalized
broker event. A read-only cancellation assessment requires that lookup after the cancellation
attempt and any unknown-outcome record, then accepts only the latest matching terminal event and
local state. It reports canceled, rejected, or filled resolution; it never permits retry or another
broker call. Zero-fill release and positive-fill retention remain broker-event transaction rules.
Storage accepts only schema-validated normalized fields and excludes raw bodies, headers, URLs, and
exception text. A valid event advances local order state in the same transaction as its evidence;
zero-fill cancellation or rejection also releases capacity. Conflicting identity, order, quantity,
sequence, or local state restores persistent emergency disable before the event is rejected.
Only the reader's non-injected production lookup path can convert one normalized lookup result into
durable broker-event evidence. The event identity binds the complete lookup snapshot, broker update
time, and local observation time; injected transports remain unable to create provenance.
Conflicting duplicates, unknown statuses, out-of-order transitions, or position drift trigger
emergency disable. Each submit, cancel, and cancel-all mutation is journaled before the call and has
an unknown-outcome state resolved by lookup and reconciliation before retry. No production order
submission is implemented. The broker-free intent store validates immutable intent content,
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

Future paper-write authority has a dormant evidence boundary. One immutable activation binds exact
authorization, limits, account, code, fixed origin, operation scope, distinct approver and operator,
attempt cap, emergency generation, and time. A separate process opt-in names the activation and
commit; revocation is append-only. Submission preflights and cancellation attempts can bind both
records inside their existing immediate transactions. The cap counts the exact activation and opt-in
pair across both operations. Unbound injected attempts do not count. Assessment without a fresh
matching installed identity remains ineligible. Even an eligible assessment cannot grant transport
authority: the production coordinator rejects construction while runtime broker-write authority is
hard-coded false.

The authorization's code commit identifies the qualified candidate research code. The activation's
code commit identifies the installed execution build. The authorization fingerprint retains the
first binding; process opt-in and fresh installed-runtime identity retain the second. They need not
name the same commit, and either mismatch blocks the attempt.

The paper startup assessment opens the execution database in SQLite read-only and query-only mode.
It verifies current authority and evidence, reports every blocker, and cannot initialize schema,
clear emergency state, create activation, or reach the mutation coordinator.

Runtime build verification is read-only. It accepts only a strict commit-bound manifest whose wheel
name and SHA-256 match the supplied artifact, then requires GitHub attestations for both files from
the fixed repository, fixed signer workflow, and GitHub-hosted runner boundary. It returns an
immutable build identity. Installed runtime verification then rejects editable installs, requires the
archive hash to name that wheel, checks every wheel-owned installed file against both `RECORD`
copies, rejects unexpected package files, and binds all loaded package modules to that distribution.
Activation assessment requires that identity's full source commit to match both activation and
process opt-in and accepts only proof from the prior five seconds. New request-bound submission and cancellation
attempts persist the identity fingerprint inside their existing immediate transactions. The proof
cannot grant broker authority: runtime write authority remains false and no production mutation
transport exists.
