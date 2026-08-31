# Program 012 exposed-prefix acquisition

Program 012, `multi-hour-sector-etf-research-011`, is
`IMPLEMENTED-PROSPECTIVE-NOT-AUTHORIZED`. Proposal v3 defines a raw-only Alpaca SIP acquisition and
a new prefix-specific structural admission. The runtime is implemented and mock-tested, but
no standing child authority or child review exists. It does not enact Program 002 admission, evaluate
its quote grid, or authorize a strategy.

Proposal SHA-256/fingerprint is
`337a5b14ff15f9d40d0f88ed05822cf9e55293fe6c5219f56d63f1d65a67c19a` /
`7f5817707001b03765ee5563fcb07f728ac066cc7352137b732f87312743c80b`.
The finding-free correctness and credential-boundary review binds source commit `4c493b0` at
SHA-256/fingerprint `3a61db10f5cd074ea3d3d1b446eaa4acd6b8bbdebe8b4c2dc13328ed58cf30e7` /
`98736a47227b309447c34a8731edb2b7bff8c5e64a9392329145eb444cd5eb4d`.
V1 and v2 remain immutable and are superseded before execution. V1 did not require a
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

Implementation v1 binds runtime commit `da18b55f6e16234dc93fdb61801847a79e4fc178`, tree
`709a0f86d2acbe2a9f2667c68acd210f13a3cf6d`, and implementation root
`a00fd6ceda78d6733b51af143d0d1ddfd87b6501e78ffab0245f0631dc347c70`. Its artifact fingerprint is
`5fc2dc3789f3689307d4b7b352880f51c19753d498fab51d7ae18627152cb080`.

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

Raw pages, response tokens, exact missing coordinates, and exact unexpected exclusions stay in the
ignored private root. Public evidence contains only aggregate counts, gate results, hashes, and a
dataset identity on pass.

The runtime includes a credential preflight, provider client, private store, activation path, and
structural admission path. Focused tests cover intent crashes, completed-page recovery, concurrent
owners, unpaired credential attempts, malformed-response accounting, recovered pacing and budgets,
and the two key missingness cases. No credential presence or value has been inspected, no private
state exists, and no provider request has occurred. A fresh independent runtime review and clean
merge remain mandatory. A separate reviewed standing child may then enable only provider contact,
credential access, source requests, acquisition, and structural admission. Controlled/protected data,
purchases, strategy execution, PAPER, broker writes, and live execution remain disabled.
