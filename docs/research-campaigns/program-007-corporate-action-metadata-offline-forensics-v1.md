# Program 007 corporate-action metadata offline forensics

Program 007, `multi-hour-sector-etf-research-006`, remains
`TERMINAL-FAIL-CONSUMED-NO-RETRY`. Its frozen contract failed, its authority is consumed, and its
exact symbol query must not run again. This analysis changes none of those facts.

The forensic result is separate: the empty-CUSIP failure is a
`QUALIFICATION-SPECIFICATION-DEFECT`, not evidence that Alpaca corporate-action metadata is
unsuitable. Program 008, `multi-hour-sector-etf-research-007`, is therefore proposed but not
authorized.

The machine-readable public analysis is
[`program-007-corporate-action-metadata-offline-forensic-analysis-v1.json`](../../config/research/program-007-corporate-action-metadata-offline-forensic-analysis-v1.json).
It contains only aggregate structure, dates, classifications, and hashes. It contains no provider
event IDs, dividend amounts, or reconstructable rows.

## Terminal evidence

The repository started from clean synchronized `main` at
`b10397ea649b066bc2d7cadde4276166c55476c2`. Program 007 made one symbol-chain request, received one
HTTP 200 response, and stopped with zero retries. The CUSIP chain never ran.

The retained page is 115,628 bytes with SHA-256
`52e77eb497e07af20f605103bb4a75187d600ab2b9d1d1c641f21ecf3a834ab0`. Its intent, body, and receipt
remain unchanged under `.trading-lab/program-007-corporate-action-metadata-v2/`. The receipt records
status, byte count, truncation state, and response hash; it does not retain HTTP headers.

A create-only private inventory lives under the ignored `.trading-lab` root with mode `0600`. Its
SHA-256/fingerprint is
`7eccdf64ddbbb585a3668a3324c725f7db4e8a5f5b9fce1759ceb7692bdf3073` /
`1ab8d6b2a11e782e4c16c8e9ae82645d2de6cd16bba17ccfa0e58e58f8ae5da1`. It retains the detailed
per-symbol counts and control event IDs needed for later cross-filter comparison. It is not tracked.

## Current provider contract

The current first-party [Alpaca corporate-actions documentation](https://docs.alpaca.markets/us/reference/corporateactions-1)
was fetched again on August 29, 2026. The 47,697-byte Markdown representation still has SHA-256
`2a91681f4bd7f6a59d0dda311066249c51f77caa097343f0580ab262934028c1`, matching the existing public
evidence artifact.

Under `data_quality=complete`, Alpaca normally excludes unprocessed incomplete actions, but returns
already-processed actions even when completeness fields such as ex-date, CUSIP, or ISIN are missing.
Alpaca also gives no creation-time guarantee. The provider contract therefore does not guarantee a
non-empty CUSIP or ISIN on every returned row.

Program 007 required every schema-listed CUSIP to be present and non-empty before public-ledger
identity resolution. That universal rule is incompatible with the documented provider behavior.

## Response shape

The top-level object has exactly `corporate_actions` and `next_page_token`. `corporate_actions` is an
object with two collections, and `next_page_token` is null.

| Event type | Rows | Symbols | CUSIP empty | CUSIP empty % | ISIN empty | Usable process date | Usable economic date | Unique IDs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `cash_dividend` | 538 | 13 | 189 | 35.13% | 538 | 538 | 538 | 538 |
| `forward_split` | 5 | 5 | 0 | 0.00% | 5 | 5 | 5 | 5 |

The 189 rows were only the empty-CUSIP subset of the 538 cash dividends. They were not the whole
response. The full page contains 543 events.

All other documented collections are absent: `reverse_split`, `unit_split`, `stock_dividend`,
`spin_off`, `cash_merger`, `stock_merger`, `stock_and_cash_merger`, `redemption`, `name_change`,
`worthless_removal`, `rights_distribution`, `partial_call`, `reorganization`, and
`capital_gains_distribution`. No unknown collection or field appears.

## Identifier findings

Missing CUSIP is common but not universal. It is specific to cash dividends in this response, occurs
for all thirteen symbols, and is confined to rows processed from March 18, 2016 through December 30,
2019. It is therefore type- and legacy-date-associated, not symbol-specific. All five split rows
carry the public-ledger CUSIP. No non-empty CUSIP conflicts with the ledger.

ISIN is empty on all 543 rows. Program 008 does not use ISIN as canonical identity because the public
ledger does not bind it. A conflicting pair of non-empty ISIN values for the same provider event ID
still fails as a provider self-discrepancy.

The corrected identity rules are:

- Empty or absent CUSIP is allowed only when the row maps through its symbol to exactly one public
  ledger identity.
- A matching non-empty CUSIP corroborates the public ledger.
- A conflicting non-empty CUSIP fails.
- Unknown or ambiguous identity fails.
- The public ledger remains primary; Alpaca supplies corroboration and discrepancy evidence only.

## Controls, dates, and IDs

XLB, XLE, XLK, XLU, and XLY are each
`PRESENT-AND-STRUCTURALLY-CONSISTENT`: one forward split, 2-for-1, effective December 5, 2025. Every
control has a usable UUID, process date, economic date, and matching non-empty CUSIP. Their ISIN fields
are empty. This is offline regression evidence, not a Program 007 pass.

All 543 event IDs are canonical UUIDs and unique. Cross-filter ID stability is not proved because the
CUSIP chain never ran.

All process dates lie from March 18, 2016 through July 31, 2026, inside the requested interval. All
documented economic dates are usable. Observed `process_date` minus economic-date lag ranges from zero
through 47 days.

The cash-dividend collection is not globally ascending by `process_date`: it contains thirteen
contiguous symbol blocks, each date-ascending, and twelve cross-block date inversions. Program 008
records this provider-order deviation, validates every process date, and sorts canonical events only
after complete pagination. The qualification does not rely on global provider order.

## Deeper compatibility review

The retained response has no missing control, malformed split ratio, impossible date, conflicting or
duplicate ID, unexpected symbol, unknown type, out-of-interval process date, ambiguous identity, or
missing term needed for the five unit-normalization controls. No deeper terminal source incompatibility
was found.

Cash dividends remain subject to identity and schema checks, but an empty CUSIP on a non-unit-changing
dividend cannot by itself block share-unit continuity. Relevant unit or identity events remain strict:
missing economic dates, wrong ratios, unsupported transformations, and ledger discrepancies fail.

The offline Program 008 parser accepts the retained one-page chain, enforces terminal and
nonrepeating pagination plus page and byte ceilings, maps all 543 events, recovers all five controls,
validates process and economic dates, and reports zero discrepancies. Its canonical core
inventory fingerprint is `a1fc338678830332f529dc48790156fa570f38795f310ad010c1a8b6e18f11e2`.
This result is exposed source-engineering evidence only.

## Program 008 authority readiness

The non-authorizing proposal is
[`program-008-corporate-action-metadata-qualification-proposal-v1.json`](../../config/research/program-008-corporate-action-metadata-qualification-proposal-v1.json).
It uses no Program 007 authority, proposal, or execution root.

The only future request shape is the never-executed chain over the same thirteen public-ledger CUSIPs.
It keeps `region=us`, `start=1990-01-01`, `end=2026-08-29`, `limit=1000`,
`data_quality=complete`, omitted `types`, and `sort=asc`. It permits one to four requests and
responses, four pages, 1 MiB per accepted page, 4 MiB total, one credential load, and zero retries.
It will not replay the Program 007 symbol query.

The future CUSIP evidence must recover and reconcile the five controls, preserve provider IDs and
core content across pages, map every row to the public ledger, and fail every non-empty identity
conflict or unsupported relevant event. New events may appear because provider creation lag is
unbounded; they must pass the full corrected contract. Non-unit events present only in the exposed
symbol response do not have to appear through the CUSIP filter.

The names-only preflight passed for `PROGRAM_007_CORPORATE_ACTIONS_API_KEY_ID` and
`PROGRAM_007_CORPORATE_ACTIONS_API_SECRET_KEY` without reading either value. Authority proposal
`program-008-corporate-action-metadata-qualification-authority-proposal-2026-08-29-v1` is
`READY FOR USER AUTHORIZATION`. It binds implementation commit/root
`f0ed2534e768d26cc5969d574d16f0ef951e28ac` /
`186168ba7fd738e2fa54e9a785808df726a97928a32a9f3e6969f8ff77adc507`, request-plan
SHA-256/fingerprint `882682b16bbf9f5fa81742a75577546f364d7c76bb04e6e15abf2d9a64043465` /
`18ae8ef4152f827fe70261c76f20baf026b44e1a091ae98f1537dcacda818fe7`, and the separate ignored
private root `.trading-lab/program-008-corporate-action-metadata-v1`.

Production execution owns its redirect-disabled fixed-host transport. Its public entry point accepts
no transport callback. The finite test transport takes only canned responses and credential-free
request intents. Authority-proposal SHA-256/fingerprint is
`2f7ca46c70fb1aeef298728c780fca28c16c9121bedba1ec1ea5d99954268da5` /
`6173cb00ab3119ad17846c0251d253c4448e017e344b882b104ef966c7bc3f78`; fresh authority-review
SHA-256/fingerprint is `c80decf235f7447740b895f400c3faa9386f8f5db10322bdfeb64a66219a7f66` /
`ec2b111145b20d59f92dd7b3cdbab8a04572d1889db388732690709a3d73f66f`.

The proposal and review created no active authority, external root, private root, claim, credential
value load, provider request, response, byte, OHLCV access, strategy result, protected action, PAPER
action, broker write, or live action. Derive the one external root only from final clean synchronized
`main`. That derivation does not activate authority. A future run still requires the exact separate
user authorization.

## Program 008 terminal qualification

The exact user authorization activated root
`90b60b95caef446d84e8242ae9aa3e0086d2655c7f55da9dc28c7d252153ad9e` on clean synchronized main
`37af39a2213ac8bb29b2877d452bf480a33b096a`. The one-use claim was written immediately before the
first transport. One credential load and one zero-retry, redirect-disabled CUSIP request returned one
HTTP 200 page with 83,338 bytes and no continuation token.

The reviewed parser accepted 354 unique canonical events: 349 cash dividends and five forward
splits. All 354 records corroborated exactly one public-ledger identity, none had an empty or
conflicting CUSIP, all 354 had an allowed empty ISIN, and no event-ID, process-date, economic-date,
pagination, or budget gate failed. XLB, XLE, XLK, XLU, and XLY each supplied exactly one 2-for-1
forward split dated `2025-12-05`. No unexpected relevant action appeared.

Program 008 metadata is `TERMINAL-PASS-CONSUMED-NO-REPLAY`. Public terminal-success
SHA-256/fingerprint is `23bf0e29b4f8b4b4655d7eeb470e4ceb1bc319717c854ec3d82790ef52c1762b` /
`151091ac4d863d73561afc24dc0138e5326dd237183dfb7da178cb5584871fcd`. The exact response remains
under the ignored private root; Git contains only counts, hashes, fingerprints, and validation
summaries. Program 007 was not replayed. No OHLCV request, dataset admission, strategy calculation,
controlled/protected access, PAPER action, broker write, or live action occurred. A successor OHLCV
authority-proposal task requires a new explicit user authorization and must not execute OHLCV.

The finding-free
[`program-008-corporate-action-metadata-qualification-terminal-success-independent-review-v1.json`](../../config/research/program-008-corporate-action-metadata-qualification-terminal-success-independent-review-v1.json)
binds both closeout commits and passes all 17 required challenges. The reviewer independently
rehashed the public and private evidence, reparsed all 354 events inside the ignored private boundary,
and found the response body absent from reachable and unreachable Git objects. Review
SHA-256/fingerprint is `65eda8a7e6bc6d262b382227db7ca82ecd42dc38caa97d637d6dd1b207a4e6c9` /
`143f8e5023b96bc950f9ec86d37e966fca42ceefd1c07c691d6d3c2af7c66dad`.

The earlier finding-free forensic review binds implementation commit
`02b2ed61f6a9e1a7affd8a49162437d89fdcb751`. Its SHA-256/fingerprint is
`0ff5fe1f2c3db02c468ce3f87b553acbdd94b290189eb9f03c843e071c18475d` /
`e987474a6af543a0e7097db67ee87475d0042b2ceae7b3c7e1b49d07e67b4064`.
