# Program 012 exposed-prefix acquisition

Program 012, `multi-hour-sector-etf-research-011`, is `PROPOSED-NOT-AUTHORIZED`. Proposal v2 defines a
raw-only Alpaca SIP acquisition and a new prefix-specific structural admission. It does not enact
Program 002 admission, evaluate its quote grid, or authorize a strategy.

Proposal SHA-256/fingerprint is
`06a2d2544def3443040e104f246458cd79a8205820a059efef037751f053ef74` /
`696c4e44ffa4aa1053ee5ea131dea6c3a8a639f2a22f1aff630fd24a142d60e8`.
V1 remains immutable and is superseded before execution: review found that it did not require a
durable intent before dispatch, did not scope credential loads across process recovery, and applied
its exact-nine-coordinate rule too broadly. V2 changes no chronology, admission ceiling, or authority.

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
`next_page_token` is the only successful terminus. The runtime must reuse Program 011's per-symbol
timestamp validation, deterministic post-validation sorting, token and duplicate checks, raw-first
persistence, fixed-host client, disabled redirects and environment proxies, synchronized-main and
protected-range checks, and zero retries.

The 1,386 chains imply 2,760 nominal responses when complete. The hard limits are 22,176 requests
and responses, 8 MiB per page and session, 4 GiB total response bytes, 8 GiB working disk, 120
requests per minute, one credential load, one sequential chain, and zero retries.

Before each dispatch, the runtime must create and fsync an intent bound to the authority, source,
session, page, request identity, and exact private URL. A restart may reparse an exact completed page
and continue from its stored token, or start a session with no intent. An intent without a complete
page, an unreceipted body, or a changed checkpoint is terminal failure and may not cause a second
request. Each validated process may load credentials once; recovery loads are counted in terminal
evidence, credential values are never persisted, and process restarts are never automatic.

## Structural policy

Program 012 keeps the five exact pre-exposed quarantine dates. They remain excluded even if the
provider now returns every coordinate. Any context or early-close omission fails admission. A
missing coordinate on another full session excludes that whole session without fill, interpolation,
symbol dropping, reranking, or date replacement.

On a fixed quarantine date, any missing coordinate outside the exact nine-coordinate incident
inventory fails admission. That rule does not consume the one allowed nonquarantine slot: one
isolated nonquarantine full-session loss may pass only when every concentration gate also passes.

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

This proposal adds no runtime, credential check, provider client, private state, or active authority.
A later implementation must pass focused tests and independent review. A separate reviewed standing
child may then enable only provider contact, credential access, source requests, acquisition, and
structural admission. Controlled/protected data, purchases, strategy execution, PAPER, broker writes,
and live execution remain disabled.
