# Program 007 raw source contract implementation v3

## Status

Program 007, `multi-hour-sector-etf-research-006`, remains
`PROPOSED-NOT-AUTHORIZED`. The raw-first implementation is available only for synthetic testing.
Dataset admission and any one-use authority proposal remain blocked because ledger v2 leaves IWM,
MDY, and SPY `COVERAGE-UNRESOLVED`.

This report supersedes only the execution-boundary wording and implementation binding in v2. It
does not change ledger v2, the frozen sample, source parameters, science, chronology, costs, delays,
budgets, or any authority flag.

## Execution boundary correction

Fresh review of implementation v2 found that its generic callback and caller-selected storage root
could invoke a real transport despite inactive authority and could write raw observations to a
tracked path.

V3 removes that surface:

- `execute_synthetic_qualification` is the only public execution entry point.
- It accepts only the concrete `SyntheticPageSource` with finite in-memory `RawResponse` values.
- The source owns an OS temporary workspace; callers cannot select another root.
- Exact frozen proposal and request-plan checks run before source or filesystem activity.
- A request intent is durable before each synthetic response read.
- Restart validation reads retained pages without reading the source again.
- No provider client, credential API, generic transport callback, or real-source entry point exists.

Tests reject an arbitrary callback without invoking it and reject an alternate root before any
write. A future real transport must be a separate implementation bound to an active reviewed
one-use authority and the exact ignored private root.

## Unchanged evidence and behavior

Implementation v2 remains the full ledger and source-contract report. Its evidence conclusions
remain current: XLB, XLE, XLK, XLU, and XLY each have a 2-for-1 split effective `2025-12-05`; XLF,
XLI, XLP, XLRE, and XLV have bounded no-applicable-action conclusions; IWM, MDY, and SPY remain
unresolved. Any unresolved symbol blocks the full thirteen-symbol dataset and ledger-backed
normalization.

The six-chain sample remains unchanged. Seven synthetic responses produce 14,742 canonical RTH
coordinates across fifteen XNYS sessions, while one valid extended-hours row remains in raw evidence
only. Raw pages are retained with SHA-256 receipts before parsing or semantic validation. Invalid
rows fail closed after bounded retention; exact calendar-derived 13/13 RTH completeness remains
mandatory. Only split-spanning relative-volume share counts use exact rational unit conversion; raw
prices remain unchanged.

## Immutable binding

- Source commit: `0a57a81444b7825e5c7f21bb35010245ff82d163`
- Implementation root: `6cd20ce0dab030d6e40a072a79c9186f6fce47bd027fe2437dab5957149d3534`
- V3 artifact SHA-256: `32a5fa3f18127cc95e98b9da1382590a855ed30d76e4de908c312cd6cea3774e`
- V3 fingerprint: `a72c8e25406dd13dc711bb46832f991e3645a706ddadb468d8fc6a91b438f925`
- Ledger v2 SHA-256: `3b815581d0da66db427243bce34f9ced5021f73719acd2b5d5e277d57065d53a`
- Ledger v2 fingerprint: `0ec39d6f38d469e099862173ff710c0e737b39b464e233e291c9e9b20c089c25`

Implementation artifacts and reports v1 and v2 remain byte-identical historical records.

## Verification and next gate

Thirty-one Program 007 synthetic and forensic tests, Ruff, strict mypy, and the public secret scan
pass. These checks made zero Alpaca or market-data provider requests, read no credential value or
presence state, read no Program 006 private page, and generated or read no strategy return. The 326
authorized public NYSE research calls remain recorded only as public exchange research.

Provider contact, subscription purchase, credential access, source request, source qualification,
acquisition, dataset admission, strategy work, research qualification, controlled evaluation,
protected holdout, PAPER, broker write, and live execution remain false.

The next gate remains complete public issuer or exchange unit-changing-action coverage for IWM,
MDY, and SPY in a new strict ledger version, followed by a finding-free review, green CI, and clean
synchronized main. Only then may a separate one-use raw Alpaca SIP structural source-qualification
authority proposal be drafted and reviewed for a new explicit user grant. This work does not create,
authorize, or execute that proposal.
