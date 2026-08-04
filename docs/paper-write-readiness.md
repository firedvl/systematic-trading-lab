# Paper broker-write readiness

Status: **not ready**. This checklist does not authorize a broker call. `Settings.broker_writes_allowed`
remains hard-coded to `False`, no production mutation transport exists, and live trading remains
prohibited.

## Current blockers

All blockers must be removed in separate reviewed changes:

1. No candidate has passed qualification, so no current paper authorization exists.
2. `config/risk/` has no active reviewed risk-limit file or production financial values.
3. Runtime configuration can parse an exact activation-and-code opt-in. Submission and cancellation
   can bind it to dormant one-shot evidence and enforce its shared attempt cap. A main-only workflow
   can build a commit-bound wheel and manifest, but the current user-owned private repository cannot
   persist GitHub attestations. Fail-closed verification checks both artifacts against the fixed
   GitHub authority and binds a non-editable installed distribution to that wheel, but activation
   assessment does not yet consume the installed identity. Runtime write authority still always
   returns false.
4. Submission and cancellation adapters require injected test transports; no production mutation
   transport exists.
5. No paper-execution CLI or supervisor exists.
6. The threat model has not been reapproved for paper writes.
7. M5 sustained paper operation, recovery drills, and equivalence evidence have not begun.

## Evidence required before implementation

Before adding a production paper mutation transport, one reviewed change set must define:

1. The exact qualified candidate and unexpired paper authorization.
2. Every `RiskLimits` value, account, symbol, reviewer, reason, effective time, and expiry. Do not use
   test values as production defaults.
3. An explicit multi-control enablement design that cannot select a live origin and defaults off on
   missing, malformed, stale, or conflicting state.
4. The fixed paper endpoint allowlist, credential boundary, redirect policy, timeout policy, and
   sanitized error contract.
5. Startup checks for journal integrity, active authorization and limits, current attested account,
   quote and clock evidence, clean reconciliation, clear emergency state, and no unresolved mutation.
6. Shutdown, restart, exact-lookup recovery, cancel-all, credential rotation, database backup, and
   evidence-retention procedures.
7. Independent code review, updated threat model, injected failure tests, and explicit user approval
   for paper writes. Live trading needs a later separate policy and approval process.

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
only the exact bound pair across both operations. The supplied commit string is not trusted runtime
code identity, so assessment remains ineligible and no bound path can call a transport.
