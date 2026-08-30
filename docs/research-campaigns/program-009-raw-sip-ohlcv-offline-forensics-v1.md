# Program 009 raw SIP OHLCV offline forensics

Program 009, `multi-hour-sector-etf-research-008`, remains
`TERMINAL-FAIL-CONSUMED-NO-RETRY`. This review does not replay it or change its result.

The machine record is
[`program-009-raw-sip-ohlcv-offline-forensic-analysis-v1.json`](../../config/research/program-009-raw-sip-ohlcv-offline-forensic-analysis-v1.json).
Its SHA-256 and fingerprint are
`cc77d9a9f767d66262547704892f98584dad38a5771324025f1828b9048bed17` and
`27803619aa67637c9e6d4fe656976f4269de23c7d2312765bbabec9640ceaba8`.

## Evidence boundary

The review used the immutable Program 009 public records, all nine retained private response pages,
their intents, receipts, response manifest, current public Alpaca documentation, and synthetic data.
It made no Alpaca data request, read no credential name or value, and ran no strategy calculation.
No retained price or volume appears in Git or this report.

## Terminal execution

Program 009 made nine requests and received nine HTTP 200 responses totaling 1,806,300 bytes. It made
no retry. The three normal chains each ended in one page with exactly 1,014 canonical coordinates.
The ten-session chain retained six pages and 14,239 raw rows, including 4,344 extended-hours rows and
9,895 canonical rows. Page six still had a continuation token. The executor stopped before page seven,
the early-close chain, or the post-split chain.

That stop remains the correct execution of the frozen Program 009 rule. The rule itself is assessed
prospectively below.

## Current provider contract

The current first-party [multi-symbol historical bars reference](https://docs.alpaca.markets/us/reference/stockbars)
states that:

- `limit` is a maximum of 1 to 10,000 total points per page;
- a page may contain fewer points while more points remain;
- clients must inspect `next_page_token` and continue with `page_token`;
- results progress by symbol and then timestamp; and
- continued requests eventually reach later symbols.

The retrieved Markdown had 17,662 bytes and SHA-256
`c69f35cfc4d20fb0c79a6a80876a562e2260a062ce8e1dd901e09ca140bff233` on
August 30, 2026. The current single-symbol reference states the same underfilled-page rule and had
SHA-256 `e66203e8b3a29f2b9e43d543e98742324967de29896ebec0ccca63da17787bff`.
The retrieval record is
[`program-010-alpaca-bars-public-contract-evidence-v1.json`](../../config/research/program-010-alpaca-bars-public-contract-evidence-v1.json).

## Six-page ceiling

Classification: **QUALIFICATION-SPECIFICATION-DEFECT**.

The Program 007 proposal from which Program 009 inherited the value records one basis: 10,140
canonical rows exceed the documented 10,000-point maximum, so the chain must paginate. It does not
derive the six-page maximum. Source history shows six arrived as an unexplained five-page allowance
above the two-page lower bound. No record ties it to a provider guarantee, observed minimum fill, or
finite-domain proof.

Alpaca expressly permits underfilled nonterminal pages. A continuation token on page six therefore
does not prove provider incompatibility. It proves that the chain was incomplete when the frozen
Program 009 budget stopped it. Program 009 still fails because the consumed run had to obey that
budget.

## Page sequence

All first and last timestamps below are RTH coordinates. The retained bodies contain no repeated
coordinate or token and advance in documented symbol-first order.

| Page | Raw rows | Bytes | First | Last | Token | Cumulative raw | Cumulative canonical |
| ---: | ---: | ---: | --- | --- | :---: | ---: | ---: |
| 1 | 2,428 | 257,274 | `IWM@2023-05-16T13:30Z` | `MDY@2023-05-30T18:55Z` | yes | 2,428 | 1,547 |
| 2 | 2,235 | 237,184 | `MDY@2023-05-30T19:00Z` | `XLB@2023-05-23T15:45Z` | yes | 4,663 | 2,757 |
| 3 | 2,557 | 259,557 | `XLB@2023-05-23T15:50Z` | `XLF@2023-05-24T13:35Z` | yes | 7,220 | 4,369 |
| 4 | 2,443 | 253,110 | `XLF@2023-05-24T13:40Z` | `XLK@2023-05-26T18:40Z` | yes | 9,663 | 6,146 |
| 5 | 2,311 | 237,103 | `XLK@2023-05-26T18:45Z` | `XLU@2023-05-18T18:10Z` | yes | 11,974 | 8,012 |
| 6 | 2,265 | 238,982 | `XLU@2023-05-18T18:15Z` | `XLY@2023-05-24T19:05Z` | yes | 14,239 | 9,895 |

The chain fully traversed IWM, MDY, SPY, XLB, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, and XLV before
entering XLY. It stopped at `XLY@2023-05-24T19:05Z`.

## Missing versus unobserved

The old public record grouped 245 absent pagination-range coordinates as missing. The ordered-domain
review splits them:

- `MDY@2023-05-19T17:10Z`: **CONFIRMED-SOURCE-MISSING**. The pages contain every other expected MDY
  coordinate, finish MDY on page two, and continue through later symbols.
- 244 later XLY coordinates: **NOT-OBSERVED-DUE-TO-PAGINATION-STOP**. They begin at
  `2023-05-24T19:10Z` and cover the rest of that session plus May 25, May 26, and May 30. The
  continuation token proves that the provider chain had not finished XLY.

The completed ordered domains contain one confirmed source-missing coordinate. The whole Program 009
sample has 1,804 unobserved coordinates: the 244-coordinate XLY tail plus 546 early-close and 1,014
post-split coordinates in chains that were never requested.

## Qualification and admission

Classification of the old any-missing-means-fail rule:
**QUALIFICATION-SPECIFICATION-DEFECT**.

Source qualification should decide whether the source can be acquired, retained, parsed, paginated,
projected, and audited without semantic ambiguity. Dataset admission should decide whether the full
terminal chronology meets the frozen `7/1499` whole-session limit, five-session quarantine, two
unexpected-session slots, and every concentration, adjacency, recurrence, and context gate.

An isolated absent coordinate is a source-quality fact. It does not make opaque-token transport or
raw SIP semantics unusable. Moving that adjudication downstream does not make qualification automatic.
Qualification still fails on inaccessible SIP, schema drift, malformed or duplicate coordinates,
invalid OHLCV, foreign symbols, token cycles or reuse, zero progress, request identity drift, raw
persistence failure, calendar ambiguity, an absent required symbol or session, action mismatch, or a
resource overrun.

Prospective missingness has three states:

1. A terminal chain makes every absent canonical coordinate `SOURCE-MISSING`.
2. A nonterminal ordered chain makes absent coordinates before its frontier `SOURCE-MISSING`.
3. A nonterminal ordered chain makes absent coordinates after its frontier
   `UNOBSERVED-BECAUSE-CHAIN-INCOMPLETE`.

No state permits imputation.

## Prospective transport

The selected design is one multi-symbol request chain per exact XNYS session:

- `GET https://data.alpaca.markets/v2/stocks/bars`;
- all 13 symbols;
- exact RTH open through final five-minute bar open, inclusive;
- `feed=sip`, `timeframe=5Min`, `adjustment=raw`, `sort=asc`, `asof=2026-07-31`;
- `limit=1000`;
- continue until `next_page_token` is null;
- reject token reuse or cycles, ordering regression, zero progress, duplicates, identity drift, and
  raw persistence failure; and
- retain bounded raw bytes before parsing or continuation.

A complete normal session has 1,014 coordinates, so it normally exercises pagination. A 546-coordinate
early close normally fits in one page. Neither shape assumes a fixed page count.

The operational cap is 16 pages per session. It is a
`RESOURCE-AND-ABNORMAL-PROVIDER-BEHAVIOR-SAFETY-CAP`, not an expected scientific page count. The exact
domain permits at most 1,014 one-coordinate progress pages. Sixteen gives an eightfold margin over a
two-page complete normal session while limiting 1,499 sessions to 23,984 requests, about 200 minutes
at 120 requests per minute. A nonterminal token at page 16 is an operational source-contract failure,
not missing data.

Single-symbol transport would normally need 19,487 requests for 1,499 sessions, versus about 2,998
for session-scoped multi-symbol transport. It offers finer symbol restart units but adds request,
receipt, and mapping state while dataset admission acts on whole sessions. Multi-symbol session chains
are the smaller provable design.

Exact RTH bounds leave no valid extended-hours coordinate inside a normal chain. An out-of-bounds row
is invalid. Raw-first retention remains mandatory.

## Fresh successor sample

All Program 009 observations are exposed. The eligible audit excludes the 198-session Programs
002-009 OHLCV union and the 145-session in-range protected inventory. Using seed
`program-010-raw-sip-qualification-sample-v1`, the three lowest hashes select:

- `2021-05-25`;
- `2021-07-02`; and
- `2024-01-11`.

The sample also keeps `2025-11-28` as the fresh early-close/pre-split control and `2025-12-15` as the
fresh post-split control. Program 009 planned but never requested those chains. No earlier request
inventory contains any of the five selected sessions.

The sample has 4,602 expected coordinates. Typical shape is nine requests and responses; the
qualification cap is 80 requests and responses, 8 MiB per page and session, 40 MiB total, one future
credential load, and zero retries. These are proposal values only.

Program 008's terminal metadata PASS and public ledger v3 remain prerequisites. Provider-adjusted
OHLCV remains prohibited. Raw contemporaneous prices remain canonical. Only split-spanning share-count
comparisons use the exact rational ledger factor.

## Scope

This slice adds an offline synthetic transport and a non-authorizing design record. It creates no
authority, credential path, provider client, request, dataset, strategy result, controlled or protected
access, PAPER action, broker write, or live action.
