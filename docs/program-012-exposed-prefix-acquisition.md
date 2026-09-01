# Program 012 exposed-prefix acquisition

Program 012, `multi-hour-sector-etf-research-011`, is
`IMPLEMENTED-PROSPECTIVE-NOT-AUTHORIZED`. Proposal v4 defines a raw-only Alpaca SIP acquisition, a
new prefix-specific structural admission, and a public terminal that discloses no data-derived
commitment or dynamic acquisition state. Runtime v4 preserves the reviewed v3 code and fixes the
prospective child lineage baseline. No standing child authority or child review exists. Program 012
does not enact Program 002 admission, evaluate its quote grid, or authorize a strategy.

Proposal SHA-256/fingerprint is
`7785108f301052e654d00ea056656e7a9d4c95c1775bcadb7c3bdaf52c1662c4` /
`66d61d1671964eea30231057a185d4798ad640c7138db05144528b067724aee9`.
The finding-free public-evidence design review has SHA-256/fingerprint
`a1ead64e3f1363c39ad3f8839b78853ccd029acbee81d0acf9f6b1290502e661` /
`63463151f427f5a61d530480536a3b75d20724822af5879966129ece1003f9d6`.
Proposal v4 is scientifically and authority-equivalent to v3. V1 and v2 remain immutable and are
superseded before execution. V1 did not require a
durable intent before dispatch, did not scope credential loads across process recovery, and applied
its exact-nine-coordinate rule too broadly. V2 did not make credential-load accounting crash-safe,
bind the exact coordinate inventory, or require inter-process serialization. V3 changes no chronology,
admission ceiling, or authority.

## Chronology

The active protected registration covers `2026-01-02..2026-07-31`. The older Program 005 range
therefore cannot be requested as written. Program 012 stops at `2025-12-31` and keeps the twenty
unprotected context sessions needed before the first exposed decision as a distinct context-only
segment.

| Segment | Range | Sessions | Full | Early close | Coordinates |
| --- | --- | ---: | ---: | ---: | ---: |
| Context only | `2020-06-26..2020-07-24` | 20 | 20 | 0 | 20,280 |
| Exposed prefix | `2020-07-27..2025-12-31` | 1,366 | 1,354 | 12 | 1,379,508 |
| Total request | `2020-06-26..2025-12-31` | 1,386 | 1,374 | 12 | 1,399,788 |

The removed 145 protected sessions and 147,030 coordinates are neither missing observations nor
members of an admission denominator. The final `2025-07-31..2025-12-31` block is a truncated
structural prefix, not the historical Program 002 final fold.

## Source and transport

Each session is one thirteen-symbol `GET https://data.alpaca.markets/v2/stocks/bars` chain with
raw SIP `5Min`, `sort=asc`, `limit=1000`, and `asof=2026-07-31`. Null
`next_page_token` is the only successful terminus. The runtime reuses Program 011's per-symbol
timestamp validation, deterministic post-validation sorting, token and duplicate checks, fixed-host
client, disabled redirects and environment proxies, synchronized-main and protected-range checks,
and zero retries.

The 1,386 chains imply 2,760 nominal responses when complete. The hard limits are 22,176 requests
and responses, 8 MiB per page and session, 4 GiB total response bytes, 8 GiB working disk, 120
requests per minute, one credential load, one sequential chain, and zero retries.

The runtime takes the existing exclusive Program 011 private-root lock before checkpoint validation
and holds it through every intent, provider call, page receipt, checkpoint, and terminal write.
Before each dispatch, it atomically creates and fsyncs an intent bound to the authority, source,
session, page, request identity, and exact private URL. It then persists an append-only raw body and
parser-independent response receipt before budget accounting and parsing. A restart may reparse an
exact completed page and continue from its stored token, or start a session with no intent. Recovery
reconstructs request, response, byte, and pacing state from durable receipts. An intent without a
complete page, an unreceipted body, or a changed checkpoint is terminal failure and may not cause a
second request.

Before credential access, each process fsyncs a value-free load-attempt record. It then writes a
value-free success or failure receipt. An unpaired attempt counts conservatively as a load. Each
validated process may load credentials once; terminal evidence counts all loads, credential values
are never persisted, and process restarts are never automatic.

Implementation v4 supersedes v3 before authority or execution without changing runtime behavior. It
binds checkpoint commit `47de7536ca8a85c3dd2c7c8523218751fd751a9c`, tree
`7cf99cfee801370e7a5306019b2ca0a36f18166b`, and implementation root
`52f20b9d3e5a8e36b5b3ee0f03aeac2592577972e969a5362b0df9028b65635b`. Its artifact
SHA-256/fingerprint is `117212f123d65784d9703b4529dba0dfb196fa64f9589a0d9d5b7fb58bf31a4f` /
`8ec987889ec3fe5fb993f26d77eb25d17e1fbb0f452296ab7ad28346da014d27`.

Runtime v3 had frozen `f6d5d18e30de20d3b96aaaf567b4529a25974297` as the future child source,
but eight runtime-finalization files followed that commit. The repository preflight permits only the
child authority and its review after the child's runtime source, so a later child bound to that stale
commit could never activate. Runtime v4 requires the child to freeze its runtime source commit and
tree from clean synchronized `main` after v4 merges. A topology regression proves that the stale
binding fails and the post-finalization binding passes.

V3 rederives the private dataset content identity, gate results, missingness counts, and admitted
session bindings from canonical private evidence during recovery. It accepts only an exact generated
public terminal on re-entry, rejects all other repository dirt, and compares that terminal with a
fresh reconstruction before authority derivation completes. Repository terminal publication and CLI
output use the same public projection. A process-local latch also prevents a second credential access
after an interrupted attempt record.

## Structural policy

Program 012 keeps the five exact pre-exposed quarantine dates. They remain excluded even if the
provider now returns every coordinate. Any context or early-close omission fails admission. A
missing coordinate on another full session excludes that whole session without fill, interpolation,
symbol dropping, reranking, or date replacement.

On a fixed quarantine date, any missing coordinate outside the exact nine-coordinate incident
inventory fails admission. That rule does not consume the one allowed nonquarantine slot: one
isolated nonquarantine full-session loss may pass only when every concentration gate also passes.
The nine-coordinate inventory is the sorted unique union of Program 002's completed-segment
`synthesized_coordinates` and failed-segment `missing_intervals`. Its fingerprint is
`b725b51b5854a9297f8514c282a15b9729b44a4666de6c09066e5316aef8e9fe`, and it must equal Program
005's frozen `known_mdy_coordinates` before admission.

The protected truncation requires a new prospective denominator. Applying the old rate without
weakening it gives `floor(1354 * 7 / 1499) = 6`, so the five fixed dates leave one unexpected
full-session slot. The annual, fixed-block, rolling-63, adjacency, same-symbol rolling-252, context,
clock, and SPY/MDY morning gates remain binding with their prefix populations recomputed before any
new response.

Raw prices stay unchanged. The dataset binds the reviewed Program 007 public unit-changing-action
ledger. Program 012 does not request a provider-adjusted view or materialize adjusted prices or
volumes. A later authorized feature calculation must use the existing exact `Fraction` share-volume
normalization with the feature session as its basis.

A pass creates only `ADMITTED-PROGRAM-012-RAW-STRUCTURAL-PREFIX`. A separate prospective strategy
successor must define any evaluation folds and execution. Program 012 calculates no feature, fill,
P&L, return, or candidate gate.

## Evidence and authority

Raw pages, response tokens, every dynamic count, exact missing coordinates, exact unexpected
exclusions, detailed failure and gate evidence, response/canonical/admission/missingness/manifest/
terminal hashes, and the private dataset content identity stay in the ignored private root. Public
evidence contains only authority and source lineage, result kind, status, admission, a pass-only
lineage identity derived from public controls, static privacy/scientific/disabled-authority
assertions, and observation time. The public lineage identity is not a content identity.

The runtime includes a credential preflight, provider client, private store, activation path, and
structural admission path. Twenty-nine focused runtime tests cover intent crashes, completed-page recovery,
concurrent owners, unpaired credential attempts, malformed-response accounting, recovered pacing and
budgets, terminal re-entry, forged recovery state, public redaction, CLI parity, bounded ordinary
failure output, and the two key missingness cases. The new topology regression and focused Program
012/provenance checks pass. A fresh independent bypass review found no material finding in the v3
runtime. No credential presence or value has been inspected, no private state exists, and no
provider request has occurred. The 1,626-test full suite passes with four skips; Ruff, full mypy,
the 677-file secret scan, shell syntax, sdist, wheel, and diff checks also pass. Exact-HEAD v4
correctness and security reviews precede the clean merge. A separate reviewed standing child may then enable only provider
contact, credential access, source requests, acquisition, and structural admission.
Controlled/protected data, purchases, strategy execution, PAPER, broker writes, and live execution
remain disabled.
