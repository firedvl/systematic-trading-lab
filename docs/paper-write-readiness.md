# Paper broker-write readiness

Status: **not ready**. This checklist does not authorize a broker call. `Settings.broker_writes_allowed`
remains hard-coded to `False`, so the production coordinator rejects construction before database or
network access. Live trading remains prohibited.

## Approved scope

The first paper run may use only candidate `strategic-allocation-21`, strategy
`strategic-allocation-portfolio` version `1`, and risk configuration
`alpaca-paper-strategic-allocation-v1` with fingerprint
`20b4f89e13f1b379c0055d9c37b2296de2b95a798dba67602f6d28b68a6d3703`. The account,
symbols, and financial values come only from `config/risk/alpaca-paper-v1.json`. The paper
authorization and activation must each expire no later than 24 hours after creation. A shorter
window is allowed; extension or renewal needs a new record.

## Current blockers

All blockers must be removed in separate reviewed changes:

1. The approved candidate passed validation and holdout gates, but no current paper authorization
   exists.
2. The reviewed paper risk configuration exists. Loading it does not grant broker authority.
3. Runtime configuration can parse an exact activation-and-code opt-in. Submission and cancellation
   can bind it to dormant one-shot evidence and enforce its shared attempt cap. A main-only workflow
   builds a commit-bound wheel and manifest. Public-repository run `30885939678` persisted GitHub
   attestations for commit `f5f12fe8de8e98a98d4af49b234a59455c94ca87`, and fail-closed verification
   accepted those artifacts and a clean non-editable installation. Activation assessment and new
   request-bound attempts consume and persist that identity, but runtime write authority still
   always returns false. The activation now
   binds the installed execution commit independently from the candidate research commit retained by
   the authorization.
4. The fixed-origin production mutation transport and activation-bound submission/cancellation
   coordinator exist, but hard-coded runtime authority makes the coordinator unreachable.
5. A read-only startup assessment CLI exists. No CLI initializes execution state, activates writes,
   submits, cancels, or runs a supervisor.
6. The transport threat model below is defined, but production use still needs independent code
   review and explicit user approval after implementation and failure tests pass.
7. M5 sustained paper operation, recovery drills, and equivalence evidence have not begun.

## Fixed-origin transport design

The first production writer must reuse the existing request construction and response normalization.
It adds one transport function, not another order schema or broker client.

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

## Evidence required before implementation

Before adding a production paper mutation transport, one reviewed change set must define:

1. An unexpired authorization for the exact approved candidate, account, and risk fingerprint above.
2. The committed risk configuration must load unchanged through the strict production loader.
3. Process opt-in may enable `broker_writes_allowed` only in exact paper mode with both activation ID
   and execution commit present. Database activation, runtime identity, preflight, and emergency
   state remain separate required controls.
4. Implementation must match the fixed-origin transport design above.
5. Startup checks for journal integrity, active authorization and limits, current attested account,
   quote and clock evidence, clean reconciliation, clear emergency state, and no unresolved mutation.
6. Shutdown, restart, exact-lookup recovery, cancel-all, credential rotation, database backup, and
   evidence-retention procedures.
7. Independent code review, injected failure tests, and explicit user approval for the first paper
   activation. Live trading needs a later separate policy and approval process.

## First paper session gate

When the blockers above have been removed, an operator must stop before the first write unless all of
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

The current repository cannot execute this procedure because the blockers remain. Recovery today is
read-only. Do not interpret this document, a paper authorization record, an assessment proof, or
paper mode alone as broker-write authority.

The dormant activation binds the exact authorization, limits, account, code commit, fixed paper
origin, submit/cancel scope, distinct approver and operator, attempt cap, emergency generation, and
active interval. A separate process opt-in names its activation and commit. Submission and
cancellation can recheck and bind both records inside each one-shot transaction. Assessment counts
only the exact bound pair across both operations. A fresh attested installed identity must match and
is persisted with each new bound attempt. Even an eligible assessment cannot call a transport because
runtime write authority remains false, so the production coordinator cannot reach the mutation
transport.
