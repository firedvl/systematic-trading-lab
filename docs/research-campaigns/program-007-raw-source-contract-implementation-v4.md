# Program 007 raw source contract implementation v4

## Status

Program 007, `multi-hour-sector-etf-research-006`, remains
`PROPOSED-NOT-AUTHORIZED`. Its raw-first pipeline is available only for synthetic tests. Dataset
admission and any one-use authority proposal remain blocked because ledger v2 leaves IWM, MDY, and
SPY `COVERAGE-UNRESOLVED`.

V3 review was not finding-free. It replaced the mutable source's `next_response` method and private
root, then showed that execution invoked the injected method and wrote under the replacement root.
It also showed that the public `now` callback ran before response consumption. V4 supersedes V3
without changing the frozen sample, ledger, source parameters, science, chronology, costs, delays,
budgets, or authority state.

## Corrected execution boundary

- `execute_synthetic_qualification` remains the sole public execution entry point.
- It accepts only the exact `SyntheticPageSource` and finite in-memory `RawResponse` values.
- The slotted source rejects normal field or method assignment.
- A module-owned function consumes responses; no caller-replaceable response method is invoked.
- Public and internal execution accept no storage-root parameter.
- The root derives only from the source's OS temporary workspace.
- Deterministic tests may pass an exact built-in `datetime` whose `tzinfo is datetime.UTC`.
- No caller-supplied callable is accepted; callback-capable clock and timezone objects fail before
  invocation or filesystem activity.
- Request intent still precedes response consumption, and restart still reads retained pages without
  consuming another response.
- No provider client, credential API, real transport, or real-source entry point exists.

A future real transport must use a separate implementation bound to the exact active one-use
authority and ignored private root. It must not extend this synthetic entry point.

## Unchanged evidence

The complete public-evidence analysis remains in the v2 report. Ledger v2 resolves ten symbols:
XLB, XLE, XLK, XLU, and XLY each have a 2-for-1 split effective `2025-12-05`; XLF, XLI, XLP, XLRE,
and XLV have bounded no-applicable-action conclusions. IWM, MDY, and SPY remain unresolved. Any one
unresolved symbol blocks the full thirteen-symbol dataset and ledger-backed normalization.

The six-chain sample remains unchanged. Seven synthetic responses produce 14,742 canonical RTH
coordinates across fifteen XNYS sessions; one valid extended-hours row remains raw-only. Raw pages
and SHA-256 receipts precede parsing and semantic validation. Invalid rows fail after bounded
retention, exact calendar-derived 13/13 RTH completeness remains mandatory, and split-spanning
relative-volume uses exact share-unit ratios without changing raw prices.

## Immutable binding

- Source commit: `d779b45131ab08108ed7b5eb1c89133e83601a5e`
- Implementation root: `e5e5a06fbfea32050d6915e444c1d28b2ba215fa1adc35b5f36bad8d635ce6ac`
- V4 artifact SHA-256: `4cec636042b8213d7ec15b5d6f72a702dffc36e7721e56486227f3931976e765`
- V4 fingerprint: `58f22785e48b0ed480961cf0809e3bce4f969e1b2a68298549d60a47119507af`
- Ledger v2 SHA-256: `3b815581d0da66db427243bce34f9ced5021f73719acd2b5d5e277d57065d53a`
- Ledger v2 fingerprint: `0ec39d6f38d469e099862173ff710c0e737b39b464e233e291c9e9b20c089c25`

Implementation artifacts and reports v1 through v3 remain byte-identical history. V3 is not a
finding-free implementation claim.

## Verification and next gate

Thirty-one Program 007 synthetic and forensic tests, Ruff, strict mypy, and the public secret scan
pass. These checks made zero Alpaca or market-data provider requests, read no credential value,
read no Program 006 private page, and generated or read no strategy return. One required unsanitized
full-suite run reached 1,316 passes and four skips; four Program 002 synthetic-runner tests failed
closed because Program 006 credential names were present in the shell. No credential value was
inspected. A sanitized full-suite rerun remains required.

Provider contact, subscription purchase, credential access, source request, source qualification,
acquisition, dataset admission, strategy work, research qualification, controlled evaluation,
protected holdout, PAPER, broker write, and live execution remain false.

The next gate is complete public issuer or exchange unit-changing-action coverage for IWM, MDY, and
SPY in a new strict ledger version, followed by a finding-free review, green CI, and clean
synchronized main. Only then may a separate one-use raw Alpaca SIP structural source-qualification
authority proposal be drafted and reviewed for a new explicit user grant. This work does not create,
authorize, or execute that proposal.
