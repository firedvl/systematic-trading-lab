# Program 010 raw OHLCV structural qualification

Program 010, `multi-hour-sector-etf-research-009`, is `PROPOSED-NOT-AUTHORIZED`.
It is an offline, synthetic successor design. It creates no execution authority, external
authorization root, credential path, provider transport, provider request, dataset, or strategy
result.

Program 009 remains `TERMINAL-FAIL-CONSUMED-NO-RETRY`. Do not replay it or create another Program
009 authority.

## Program 009 forensic result

Current first-party Alpaca documentation says `limit` is a page maximum, a page may contain fewer
rows while more data remains, and clients must follow `next_page_token`. Multi-symbol bars are sorted
by symbol and then timestamp. Program 009's six-page ceiling was not derived from a documented
minimum page fill. All six retained pages made forward progress and page six remained nonterminal.
The ceiling is therefore a `QUALIFICATION-SPECIFICATION-DEFECT`, not proof of provider
incompatibility. This finding does not change Program 009's terminal failure.

The retained pagination chain progressed as follows without publishing prices or volumes:

| Page | Rows | Bytes | First coordinate | Last coordinate | Token | Cumulative raw | Cumulative RTH |
| ---: | ---: | ---: | --- | --- | --- | ---: | ---: |
| 1 | 2,428 | 257,274 | IWM, `2023-05-16T13:30Z` RTH | MDY, `2023-05-30T18:55Z` RTH | present | 2,428 | 1,547 |
| 2 | 2,235 | 237,184 | MDY, `2023-05-30T19:00Z` RTH | XLB, `2023-05-23T15:45Z` RTH | present | 4,663 | 2,757 |
| 3 | 2,557 | 259,557 | XLB, `2023-05-23T15:50Z` RTH | XLF, `2023-05-24T13:35Z` RTH | present | 7,220 | 4,369 |
| 4 | 2,443 | 253,110 | XLF, `2023-05-24T13:40Z` RTH | XLK, `2023-05-26T18:40Z` RTH | present | 9,663 | 6,146 |
| 5 | 2,311 | 237,103 | XLK, `2023-05-26T18:45Z` RTH | XLU, `2023-05-18T18:10Z` RTH | present | 11,974 | 8,012 |
| 6 | 2,265 | 238,982 | XLU, `2023-05-18T18:15Z` RTH | XLY, `2023-05-24T19:05Z` RTH | present | 14,239 | 9,895 |

The chain passed the complete MDY domain and ten later symbols before reaching XLY. MDY
`2023-05-19T17:10:00Z` is absent from its otherwise complete 780-coordinate domain and is
`CONFIRMED-SOURCE-MISSING`. The 244 XLY coordinates after the page-six frontier are
`NOT-OBSERVED-DUE-TO-PAGINATION-STOP`. Across the Program 009 sample, one coordinate is confirmed
source-missing and 1,804 are unobserved or were never requested.

Forensic analysis SHA-256/fingerprint is
`cc77d9a9f767d66262547704892f98584dad38a5771324025f1828b9048bed17` /
`27803619aa67637c9e6d4fe656976f4269de23c7d2312765bbabec9640ceaba8`.
The archived public-contract evidence SHA-256/fingerprint is
`ad925b6aaf12ab654090cb7acad0bf7418fdb2a5d2b8f50225488515f9e56e69` /
`d645ff34c78de25b4a79a1f9317e99d9456c957f8d07adf78742ba22542d1319`.

## Qualification and dataset admission

Source qualification asks whether the source and transport can be acquired deterministically,
retained, parsed, projected to canonical RTH coordinates, and audited without semantic ambiguity.
Dataset admission asks whether the complete chronology meets the frozen missingness, coverage,
concentration, corporate-action, and quality limits needed for research.

Program 009's zero-missing sample rule conflated those decisions. Program 010 uses these semantics:

- An absent coordinate in a terminal chain is `SOURCE-MISSING`.
- An absent coordinate before an incomplete chain's ordered frontier is `SOURCE-MISSING` because
  documented ordering has passed it.
- An absent coordinate after that frontier is `UNOBSERVED-BECAUSE-CHAIN-INCOMPLETE`.
- An isolated source-missing coordinate is recorded without imputation and does not alone fail
  structural source qualification.
- Every required symbol must contain a strict majority of its calendar-derived session coordinates:
  40 of 78 on a normal session or 22 of 42 on an early close. Lower coverage fails as
  catastrophic coverage loss.

Qualification also fails on inaccessible SIP, malformed schema or coordinates, duplicates, invalid
OHLC or volume, symbol contamination, pagination cycle, token reuse, order regression, zero progress,
request identity drift, raw persistence failure, calendar ambiguity, corporate-action mismatch, or a
resource cap. It is not an automatic pass.

Only a later complete acquisition may apply the frozen dataset-admission policy: at most seven of
1,499 whole sessions, including the five pre-exposed quarantine sessions and at most two isolated
unexpected exclusions, subject to every existing concentration, adjacency, context, and recurrence
control. No strategy may run before admission.

## Corrected transport

Each chain requests all thirteen symbols for one exact XNYS regular session:

- `GET https://data.alpaca.markets/v2/stocks/bars`
- `feed=sip`, `timeframe=5Min`, `adjustment=raw`
- `sort=asc`, `limit=1000`, `asof=2026-07-31`
- start at the calendar-derived regular-session open and end at the final five-minute bar open,
  inclusive
- zero automatic retries

A chain ends only when `next_page_token` is null. Tokens are opaque. A cycle, reuse, repeated page,
order regression, cross-page duplicate, or nonterminal zero-progress page fails. Each bounded body is
fsynced before parsing or continuation.

The 16-page session ceiling is a resource and abnormal-provider-behavior cap, not an expected page
count. A normal session has at most 1,014 canonical coordinates and needs at least two pages at
`limit=1000`. Sixteen pages allow eight times that lower bound while limiting a 1,499-session safety
case to 23,984 requests, about 199.87 minutes at 120 requests per minute. A nonterminal token at the
cap means `CHAIN-INCOMPLETE-RESOURCE-CAP`; later coordinates remain unobserved, not source-missing.

Exact RTH bounds leave no valid extended-hours coordinate in a request. An out-of-bounds row fails
after raw retention. General raw parsing remains unchanged.

## Fresh sample

The deterministic audit excludes every Programs 002-009 OHLCV-observed session and all protected or
controlled dates. It binds a 198-session observed union and leaves 1,189 eligible unobserved,
unprotected sessions. The seed `program-010-raw-sip-qualification-sample-v1` selects the three
lowest `SHA-256(seed|normal|date)` normal-session digests, then adds the two Program 009 controls that
were never requested.

| Session | Role | Prior OHLCV requests | Coordinates |
| --- | --- | ---: | ---: |
| `2021-05-25` | normal | 0 | 1,014 |
| `2021-07-02` | normal | 0 | 1,014 |
| `2024-01-11` | normal | 0 | 1,014 |
| `2025-11-28` | early-close, pre-split | 0 | 546 |
| `2025-12-15` | post-split | 0 | 1,014 |

The sample has 4,602 expected coordinates. Program 009 requested zero pages for both semantic
controls. Program 008 metadata observations do not expose OHLCV. No Program 009 market observation
may count as Program 010 scientific qualification evidence.

Program 008's terminal metadata PASS and public ledger v3 are required inputs. Raw contemporaneous
prices remain canonical. Only split-spanning share-count comparisons may apply the exact rational
ledger factor for the XLB, XLE, XLK, XLU, and XLY 2-for-1 splits effective `2025-12-05`.

## Budgets and production comparison

The five-session qualification typically needs about nine requests and responses, but no fixed page
count is promised. It allows at most 80 requests and responses, 8 MiB per page, 8 MiB per session,
40 MiB total, and zero retries.

For 1,499 sessions, multi-symbol session chains project to about 2,998 typical requests and 23,984 at
the safety cap. Typical runtime is 24.98 minutes at 120 requests per minute; the safety case is 199.87
minutes. Typical raw bodies are estimated at 158,876,842 bytes, or about 160-200 MiB with receipts and
manifests. The 8 MiB per-session safety case caps raw bodies at 11.71 GiB.

Single-symbol transport would typically require 19,487 requests and about 162.39 minutes. It improves
symbol-level isolation but adds thirteen request, receipt, and mapping units per session. The selected
multi-symbol design uses one restart unit per session and matches the whole-session admission policy.

These estimates authorize no full acquisition.

## Immutable proposal evidence

- Implementation ID: `program-010-raw-source-implementation-2026-08-30-v2`
- Implementation commit/root: `974e223f0b07e5662adc2342fd5c0ed4289b1b46` /
  `fef66005316009c2da835111772437294c3e3077e946d45bdd81e8eaa2b138da`
- Implementation artifact SHA-256/fingerprint:
  `049cbc08764ed6867042cf53ede2045bca339acc3216c9daf54b0cfe49d8c080` /
  `8d3f6cd635524baaa2c71b38d5eb02bab290d56ef4afad771150370683c84a60`
- Proposal ID:
  `program-010-raw-alpaca-sip-ohlcv-structural-qualification-proposal-2026-08-30-v2`
- Proposal SHA-256/fingerprint:
  `6b9ddc99dae6e5ce51559feda41f86eaa7ef98cdb120689bdbc33b3a721c21b7` /
  `00f71af4e1016d708e2e6c62867593554879065da50e99e5f412adad427ab0d4`
- Fresh closure review: pending

Initial review found that top-level execution did not always close its unnamed evidence file and that
one coordinate per symbol could pass catastrophic coverage. V2 closes the source in `finally` on
every top-level success or failure and applies the strict-majority rule above. V1 remains immutable
review history.

The implementation accepts only finite synthetic responses and holds raw evidence in an unnamed
temporary file. It has no provider client, credential reader or presence check, activation path, or
persistent real evidence root. Every top-level synthetic execution closes the evidence source on
success or failure.

The exact next step is to create and independently review a separate one-use Program 010 raw SIP
structural qualification authority proposal that binds a fixed GET-only client and ignored persistent
evidence root. Do not derive an external authorization root, access credentials, or contact Alpaca in
the current phase.
