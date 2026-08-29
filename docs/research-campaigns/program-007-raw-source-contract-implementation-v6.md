# Program 007 raw source contract implementation v6

## Status

Program 007, `multi-hour-sector-etf-research-006`, remains
`PROPOSED-NOT-AUTHORIZED`. The raw-first implementation accepts synthetic responses only. Dataset
admission, ledger-backed normalization, and a one-use authority proposal remain blocked because
ledger v2 leaves IWM, MDY, and SPY `COVERAGE-UNRESOLVED`.

V5 is immutable failed-review history. Its descriptor-relative child operations rejected symbolic
links but could still open a pre-existing external directory moved under the workspace or read a
hard-linked external file. `O_NOFOLLOW` proved path shape, not inode origin. V6 removes child-path
evidence operations without changing the sample, source parameters, ledger, strategy science,
chronology, costs, delays, budgets, or authority state.

## Capability-held evidence

`SyntheticPageSource` creates one unnamed `TemporaryFile` before callers receive the source and
keeps its descriptor open for the source lifetime. The temporary workspace is only a root-identity
and foreign-entry canary. Any visible workspace entry rejects before execution. Evidence reads and
writes never reopen a child path.

The descriptor stores create-only logical entries in canonical JSON lines. Each entry binds its
logical key, strict canonical Base64 payload, byte count, SHA-256, and entry fingerprint. Publication
appends and fsyncs while holding both a per-source `RLock` and `flock`. The in-process lock is needed
because `flock` is reentrant when threads share one open-file description.

Request intent is appended and fsynced before synthetic response consumption. A bounded raw body is
appended and fsynced before its receipt, parse, raw structural checks, RTH projection, or completeness
checks. A partial intent or body remains inspectable and blocks restart under the zero-retry rule.
Restart works only through the same `SyntheticPageSource` object while its unnamed descriptor remains
open. A future authorized real transport needs a separate persistent-store design.

## Unchanged scientific result

Ledger v2 resolves ten symbols. XLB, XLE, XLK, XLU, and XLY each have a 2-for-1 split effective
`2025-12-05`; XLF, XLI, XLP, XLRE, and XLV have bounded no-applicable-action conclusions. IWM, MDY,
and SPY remain unresolved, so no Program 007 dataset or ledger-backed normalization can be admitted.

The six-chain sample still contains 14,742 canonical RTH coordinates across fifteen XNYS sessions in
seven synthetic responses. Valid extended-hours rows remain in raw evidence and outside the canonical
projection. Invalid rows fail after bounded retention. Raw prices remain canonical. Exact split ratios
apply only to cross-session relative-volume share counts.

Qualification requires every selected session to be complete. The proposal requires all 14,742
coordinates before any later missing-session disposition, so a missing selected coordinate records a
failure and stops the synthetic qualification.

## Immutable binding

- Source commit: `b06b6c77b170705ce52b18ae5058e96f861c29e1`
- Implementation root: `1e3fc58344fa2c4f72cd8f3638c63f9fd2e9e69ceb8c7265a2b7768aed7c9df8`
- V6 artifact SHA-256: `9903d4c243e94c34879cc5edd086747b4687b33224167db549782229f259b188`
- V6 fingerprint: `4e611bd85f4f59f045c1cf981ac77cc5359fce7205bedf698bd3f84050c57456`
- Independent-review SHA-256: `e0cb67fed583490fbea484f7067a8ffcb93f663381a6cc51b80c0db3522d8238`
- Independent-review fingerprint: `7c6517671aa9a8e0fa9f13e3f1adf94343639c45b49a602b4efd8cc62b3b6841`
- Ledger v2 SHA-256: `3b815581d0da66db427243bce34f9ced5021f73719acd2b5d5e277d57065d53a`
- Ledger v2 fingerprint: `0ec39d6f38d469e099862173ff710c0e737b39b464e233e291c9e9b20c089c25`

Implementation artifacts and reports v1 through v5 remain byte-identical history. Neither V4 nor V5
is a finding-free implementation claim.

## Review and verification

Fresh standards, specification, and storage-boundary reviews found no material source defect at the
bound commit after the concurrency fix. The specification review confirmed that exact qualification
completeness is intentional. Ledger incompleteness remains a pre-authority blocker, not a synthetic
implementation PASS.

Forty-six focused Program 007 tests and the sanitized full suite pass; the full result is 1,335 passed
and four skipped. Ruff, strict mypy, the public/private secret guard, distribution builds, runtime
manifest, CI, and post-merge provenance must also pass before this branch closes.

No Alpaca or market-data provider request, credential value or presence read, Program 006 private
observation read, strategy calculation, controlled or protected access, PAPER action, broker write,
or live action occurred. Every authority flag remains false.

## Next gate

Bind complete public issuer or exchange unit-changing-action coverage for IWM, MDY, and SPY in a new
reviewed ledger version. Then rebind the implementation if required, pass clean synchronized-main
review and CI, and draft a separate one-use raw Alpaca SIP structural source-qualification authority
proposal for a new explicit user grant. This work does not create, authorize, or execute that proposal.
