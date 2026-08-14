# Paper broker-write readiness

Status: **not ready for another broker call**. This checklist does not authorize a broker call. Exact paper mode plus an
activation-and-commit process opt-in opens only the outer runtime gate. The production coordinator
still requires current transaction-bound authority before any network access. Live trading remains
prohibited.

## Approved scope

Paper execution may use only candidate `strategic-allocation-21`, strategy
`strategic-allocation-portfolio` version `1`, and risk configuration
`alpaca-paper-strategic-allocation-v1` with fingerprint
`20b4f89e13f1b379c0055d9c37b2296de2b95a798dba67602f6d28b68a6d3703`. The account,
symbols, and financial values come only from `config/risk/alpaca-paper-v1.json`. The paper
authorization and activation must each expire no later than 24 hours after creation. A shorter
window is allowed; extension or renewal needs a new record. The first Alpaca paper session occurred
on 2026-08-04. Four production-bound orders filled: GLD 3, IWM 8, QQQ 3, and SPY 4. Its
replay/shadow/paper comparison passed. That evidence does not authorize another session.

## Current blockers

1. Restore valid dedicated Alpaca PAPER credentials. Current GET requests return sanitized HTTP 401.
   Do not print, log, or weaken authentication handling.
2. Before each session, build and verify the current main-only attested wheel, install it without
   edits, and use an activation bound to that exact commit. Run authority-grade verification as the
   documented unprivileged execution account; root ownership of protected artifacts is not verifier
   authority.
3. Create a maximum-24-hour continuation declaration from the latest settled authorization. Complete
   it only from fresh production-attested account, position, order, quote, and clock evidence. The
   append-only handoff must preserve positions, fill economics, strategy cash, equity peak, and
   drawdown. It cannot create a flat baseline.
4. Generate replay and shadow plans with `paper plan`, create matching quantity intents through the
   existing guarded path, record equivalence, and rerun startup assessment. Any mismatch, stale
   input, active reservation, unresolved order, or emergency transition stops the run.
5. Obtain explicit user approval immediately before any new paper broker mutation.

M5 began and produced sustained observation and recovery evidence. Its remaining 168-hour duration
was explicitly waived and remains incomplete; the waiver does not turn the failed Week 1 continuity
limit or the unobserved period into passing evidence.

## Fixed-origin transport design

The production writer reuses the existing request construction and response normalization. It does
not add another order schema or broker client.

1. The origin is the constant `https://paper-api.alpaca.markets`. Configuration, command-line
   arguments, responses, redirects, or environment variables cannot replace it.
2. The allowlist contains only `POST /v2/orders` and
   `DELETE /v2/orders/{percent-encoded broker_order_id}`. Query strings, fragments, user information,
   custom ports, bulk cancellation, replace, close-position, and every other method or path fail
   before network access.
3. The POST body remains canonical JSON for one simple, whole-share, long-only ETF market order with
   `day`, `extended_hours=false`, and the deterministic client order ID. DELETE has no body. POST
   accepts only HTTP 200 JSON; DELETE accepts only HTTP 204 with an empty body.
4. Credentials enter only from `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` at process startup. They
   remain only in adapter process memory and request headers; they never enter domain records,
   SQLite, journal events, output, or error text. Environment proxy routing is disabled for mutation
   calls.
5. The standard TLS verifier and system trust store remain enabled. Redirects are rejected. Each
   call has a 10-second socket timeout, reads at most 1 MiB, and never retries automatically.
6. Any timeout, connection failure, redirect, unexpected final URL, HTTP status, body size, content
   type, JSON shape, or response mismatch returns one sanitized error. Only the numeric HTTP status
   may be retained. The coordinator records the already-journaled attempt as unknown and requires
   exact lookup plus reconciliation; it never infers that the broker rejected the call.
7. The transport is reachable only after a transaction-bound submission preflight or cancellation
   attempt has consumed the exact activation and process opt-in, stored a fresh installed-runtime
   identity, and passed its attempt cap. Tests keep using injected transports and cannot gain
   production provenance.

The execution activation commit names the installed execution build. The paper authorization binds
the candidate's research commit through its immutable qualification evidence. Tests reject a changed
candidate authorization, process commit, or installed execution build.

## Evidence required before a paper mutation

Before any production paper mutation, the reviewed system must provide:

1. An unexpired authorization for the exact approved candidate, account, and risk fingerprint above.
2. The committed risk configuration must load unchanged through the strict production loader.
3. Process opt-in may enable `broker_writes_allowed` only in exact paper mode with both activation ID
   and execution commit present. Database activation, runtime identity, preflight, and emergency
   state remain separate required controls.
4. The fixed-origin transport implementation must match the design above.
5. Startup checks for journal integrity, active authorization and limits, current attested account,
   quote and clock evidence, clean reconciliation, clear emergency state, and no unresolved mutation.
6. Shutdown, restart, exact-lookup recovery, cancel-all, credential rotation, database backup, and
   evidence-retention procedures.
7. Independent code review, injected failure tests, and explicit user approval for the next paper
   broker mutation. Live trading needs a later separate policy and approval process.

## Paper session gate

When the blockers above have been removed, an operator must stop before a write unless all of
these facts hold at the same assessment time:

1. Runtime mode is exactly `paper`; the selected origin is exactly
   `https://paper-api.alpaca.markets`.
2. Broker-write enablement is explicit, current, and independently bound to the reviewed code and
   account.
3. The paper authorization and risk configuration are active and fingerprint-exact.
4. Emergency disable is clear through its reviewed transition, not by direct database editing.
5. Complete account, position, open-order, quote, and clock evidence is fresh and production-attested.
6. Reconciliation is clean and no submit, cancel, or cancel-all outcome is unresolved.
7. The proposed quantity order has passed the transaction-bound risk preflight and owns its exact
   capacity reservation.
8. The operator has recorded the session reason, observation window, maximum intended activity, and
   stop conditions.

Any failed or unavailable fact keeps writes disabled.

## Abort and recovery

Stop new writes immediately on stale or conflicting evidence, broker or network uncertainty,
reconciliation drift, unexpected order state, authorization or limit expiry, journal failure, or an
emergency-disable transition. Do not retry an unknown submission or cancellation. Use exact lookup,
terminal broker evidence, and complete reconciliation; preserve every failed attempt as evidence.

The current repository cannot execute this procedure while any blocker remains. Do not interpret
this document, a paper authorization record, an assessment proof, paper mode, or process opt-in alone
as broker-write authority.

The dormant activation binds the exact authorization, limits, account, code commit, fixed paper
origin, submit/cancel scope, distinct approver and operator, attempt cap, emergency generation, and
active interval. A separate process opt-in names its activation and commit. Submission and
cancellation recheck and bind both records inside each one-shot transaction. Assessment counts only
the exact bound pair across both operations. A fresh attested installed identity must match and is
persisted with each new bound attempt. Process opt-in makes the coordinator reachable but never
bypasses those transaction-bound checks.
