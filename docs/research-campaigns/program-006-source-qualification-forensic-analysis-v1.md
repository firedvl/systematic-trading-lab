# Program 006 source-qualification forensic analysis v1

Status: **OFFLINE FORENSIC REVIEW COMPLETE**. Program 006 remains
`TERMINAL-FAIL-CONSUMED-NO-RETRY`.

This review used the immutable public failure records, the 22 retained private pages, local source
and control code, and current public provider documentation. It made no provider request, accessed
no credential, generated or read no strategy return, and touched no controlled, protected, PAPER,
broker, or live state.

The machine record is
[`program-006-source-qualification-forensic-analysis-v1.json`](../../config/research/program-006-source-qualification-forensic-analysis-v1.json).
Its SHA-256 and fingerprint are
`490b813bd20d3c98249a9f0c88580bfad3fc4607e94b1f0e5cec134caac166f0` and
`f1198d0aaaba0f17f7e806c8268bf6081aba1a1746b308be58cc53489b546d6b`.

## Terminal state

Program 006 made exactly 23 requests and received 23 responses totaling 2,503,402 bytes. It used
zero retries. Twenty-two private response pages totaling 2,251,275 bytes remain. Response 23 was
252,127 bytes, but its body was not retained. No qualification receipt, source manifest, or dataset
exists.

The public failure artifact remains unchanged at SHA-256
`3c693b2a31c5d5eef11388b55e41f38b9203c21e7f8ce604fc8f89c9c15e9687` and fingerprint
`acbbbf0f28cc5d555224e05fb8d34cf4e9ae1a60fe75020ca2fee03da91180e5`. Its finding-free
terminal review remains unchanged at SHA-256
`7e79c4534ad2df67c99d70de013033f823ad650d8e35c3bdf9a8d782bba0adf9` and fingerprint
`59533d3b6c151865d304ed11aaf1a9917050625ed736b7d5edb1b38995b35359`.

Every current authority flag is false. Program 006 cannot be retried, repaired in place, or given
replacement authority. The private pages remain Git-ignored and no private OHLCV or reconstructable
snippet appears in this report.

## Failure A: response 23 outside the XNYS grid

Classification: **INDETERMINATE**.

Validator assessment: **QUALIFICATION-SPECIFICATION-DEFECT**.

Response 23 was the first page of
`pagination-split-2025-12-01-to-2025-12-12--raw` with this exact request contract:

- `GET https://data.alpaca.markets/v2/stocks/bars`
- 13 symbols: IWM, MDY, SPY, XLB, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, and XLY
- `start=2025-12-01T14:30:00Z`
- `end=2025-12-12T20:55:00Z`
- `timeframe=5Min`, `feed=sip`, `adjustment=raw`, `sort=asc`
- `limit=10000`, `asof=2026-07-31`, no first-page token, six-page ceiling

The parser had already accepted the containing symbol, UTC RFC-3339 timestamp parsing,
whole-minute timestamp, and five-minute alignment when it raised
`Alpaca bar timestamp is outside the exact XNYS grid`. It did not retain the body, offending
timestamp, symbol, row, or continuation token. The row therefore cannot be classified as
pre-market, after-hours, overnight, weekend, holiday, out of bounds, or otherwise malformed.

If Alpaca followed its documented symbol-then-time ordering, the earliest plausible extended-hours
coordinate would be `IWM@2025-12-01T21:00:00Z`. That is an inference, not recovered evidence.

### Why the old grid rule was wrong

`parse_bars_page` required every returned row to be a member of the exact XNYS regular-session
five-minute grid before it stored the response. The rule conflated two separate questions:

1. Is the provider row structurally valid and inside the request interval?
2. Does the row belong in the regular-session research projection?

Alpaca's current [historical-bars reference](https://docs.alpaca.markets/us/reference/stockbars)
documents inclusive start and end bounds, a 10,000-point page limit across symbols,
symbol-then-timestamp ordering, continuation tokens, and no regular-hours-only query parameter.
Its [market-data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq) says minute bars use
left-edge timestamps and that extended-hours trade condition `T` updates minute OHLC and volume.
Longer minute bars aggregate those minute bars. A valid extended-hours row can therefore exist in a
historical `5Min` response.

The single-session requests ran only from the XNYS open through the last RTH bar open. Those bounds
excluded pre-market and after-hours bar opens. The multi-day request was one continuous interval
from the first session open through the last session's final RTH bar open. Intersession post-market
and pre-market timestamps fell inside that interval. With symbol-first ordering and a global page
limit, those rows could appear before later symbols were reached. This explains why the defect was
specific to the pagination range without proving which row caused response 23.

### Correct prospective invariant

A successor must keep these gates separate:

1. Store and hash each bounded response before semantic rejection.
2. Validate response shape, expected symbols, UTC five-minute timestamps, inclusive request bounds,
   unique coordinates, valid OHLCV, fixed request identity, and nonrepeating pagination tokens.
3. Keep structurally valid in-bounds extended-hours rows in immutable private raw evidence.
4. Project only timestamps on the authoritative XNYS RTH five-minute grid.
5. Apply canonical completeness to that projection, under the unchanged predeclared whole-session
   missing-data policy.

Malformed, out-of-bounds, foreign-symbol, duplicate, invalid-OHLCV, token-invalid, or canonically
incomplete data must still fail. The correction changes the placement of the RTH gate; it does not
remove the gate.

## Failure B: paired adjustment factors

Classification: **QUALIFICATION-SPECIFICATION-DEFECT**.

The old check did not require one global factor across every symbol. For each matched row it:

1. derived a price factor from adjusted open divided by raw open;
2. required adjusted high, low, and close to equal raw values times that exact factor;
3. required adjusted volume times that same factor to equal raw volume;
4. required the exact factor to stay constant within each symbol/session; and
5. required the factor to match the frozen combined split-and-spin-off ledger.

That contract assumed exact adjusted-bar arithmetic and inferred volume behavior from a combined
price factor. Alpaca's current historical-bars reference documents `raw` as unadjusted, `split` as
price-and-volume adjustment, and `spin-off` as price adjustment. It permits
`split,spin-off`. The [spin-off changelog](https://docs.alpaca.markets/us/changelog/optionally-adjust-bars-after-spin-offs)
confirms combined adjustments. Neither page defines exact Decimal rounding, aggregation order, or a
reciprocal volume rule for a combined split-and-spin-off price factor.

### Retained-page results

The offline review hash-verified all 22 pages and their metadata without publishing values. The safe
aggregate page digest is `48acd83903b7ec28d7fdca8a2487cb35a9cd75a6e1c696647e7b07b918c742b3`.

- 11 completed raw/adjusted pairs contained 10,677 rows per view and 21,354 rows in total.
- Raw and adjusted coordinate sets matched in all 11 pairs.
- Eight symbols had one exact unit open ratio in every retained session.
- All 55 nonconstant symbol/session groups belonged to XLB, XLE, XLK, XLU, or XLY.
- Those are exactly the five ETFs in State Street's public 2-for-1 split effective
  December 5, 2025.
- Exact ledger-factor equality held for 32,557 of 42,708 OHLC observations.
- Fixed field-local display quantization explained 39,608 observations and left 3,100 unmatched.
- The old exact per-row OHLC factor passed 6,711 rows and failed 3,966.
- Volume matched the frozen public split factor in all 10,677 observations.
- Volume matched the varying row-specific open ratio in only 8,190 observations.
- Exact open-ratio segmentation produced 3,491 contiguous segments; 2,958 held one bar. Segmenting
  until a ratio becomes constant would not be a useful validation rule.

The issuer evidence is State Street's
[November 20, 2025 split announcement](https://investors.statestreet.com/investor-news-events/press-releases/news-details/2025/State-Street-Investment-Management-Announces-Share-Splits-for-Five-Select-Sector-SPDR-ETFs/default.aspx).
It names 2-for-1 splits for XLB, XLE, XLK, XLU, and XLY, payable after the December 4 close and
effective for trading on December 5.

The retained volume behavior is fully consistent with that public split ledger. The retained price
behavior does not reduce to one exact scalar under the tested combined provider view, and ordinary
display precision does not explain every difference. Public documentation does not supply the
missing internal adjustment and rounding contract. The paired-factor failure therefore does not
establish bad Alpaca data.

The frozen ledger had no realized spin-off control. The paired views cannot separate a split
component from a spin-off component. Any provider spin-off contribution remains **INDETERMINATE**.
The review also did not establish a complete 2020-2026 action history for all 13 ETFs. A successor
must close that ledger gap from issuer or exchange evidence before authority.

## Economic requirement and future action design

All price lookbacks, entries, exits, and holds occur within one session. For a constant positive
session factor `f`, `(f * p1) / (f * p0) - 1` equals `p1 / p0 - 1`. Same-session symbol returns and
SPY-relative returns therefore need no cross-session price adjustment. Raw entry and exit prices
also preserve the actual share and fee units.

The prior-20-session same-clock relative-volume feature does compare share counts across a split.
It needs one share unit. The prior-session capacity feature uses price times volume; for split ratio
`r`, `(p / r) * (v * r) = p * v`, so raw dollar volume is already split-unit invariant.

The selected future design is therefore:

- request and retain raw bars only;
- keep prices raw;
- bind a complete issuer/exchange ledger of unit-changing actions;
- use exact rational split factors only for share counts entering the cross-session relative-volume
  feature;
- make no cash-dividend or spin-off price or volume adjustment; and
- fail on missing, ambiguous, or conflicting unit-changing action evidence.

An overnight position, cross-session price return, total-return feature, or other new economic use
would require a new prospective action contract.

## Source disposition

Program 006 remains **FAIL under its frozen contract**. Its source suitability remains
**INDETERMINATE**. The review did not prove Alpaca raw bars suitable, but it also did not prove them
incompatible. A fresh raw-only qualification is scientifically justified because the corrections
come from provider semantics and feature algebra, not strategy performance. Zero strategy return
was generated or read.

Program 006's 22 sessions are now exposed source-engineering evidence. They may support private
forensics and regression work. They cannot serve as an unseen qualification sample or support a
strategy claim.

## Proposed Program 007

The non-authorizing proposal is
[`program-007-alpaca-raw-source-qualification-proposal-v1.json`](../../config/research/program-007-alpaca-raw-source-qualification-proposal-v1.json).
Its SHA-256 and fingerprint are
`5e92effb829e70d7bbf4636d88519c104565a10bd6f57235169419542cb05b34` and
`d0ec31e7b6947ed6fe3e1118a6f5536daddae34ebbe9dffcc3b3f932dd9d41c0`.

Program 007 is `multi-hour-sector-etf-research-006`. It is `PROPOSED-NOT-AUTHORIZED`. It has no
external authorization root, active authority, credentials, provider request, dataset, or strategy
permission.

### Freshness audit and selection

Programs 002-006 exposed 185 distinct XNYS sessions in the eligible chronology:

- Program 002 made real Alpaca market-data requests covering every XNYS session from
  June 26, 2020 through February 26, 2021: 169 distinct sessions. Its four one-minute
  reconstruction sessions fall inside that range.
- Programs 003 and 004 made no provider request.
- Program 005 made no provider request before its credential failure.
- Program 006 observed 22 sessions, six of which overlap Program 002.

The full June 26, 2020 through July 31, 2026 chronology contains 1,531 XNYS sessions. Removing the
185-session union leaves 1,346 unobserved sessions. A hash-bound public metadata inventory excludes
145 sessions inside the chronology for protected or controlled ranges; one is already in the
observed union. The complete 329-session exclusion union leaves 1,202 eligible unobserved,
unprotected sessions. No protected market data or result was read to construct the inventory.

With seed `program-007-source-qualification-sample-v1`, the fixed procedure:

1. selects the nearest eligible sessions before and after the public December 5, 2025 split;
2. hashes each remaining 10-consecutive-full-session window as
   `seed|pagination|first|last` and selects the lowest SHA-256 digest;
3. hashes each remaining full session as `seed|normal|date` and selects the three lowest digests;
4. sorts and fingerprints the result before provider observation.

The 15 selected sessions have zero overlap with prior provider observations and zero overlap with
controlled or protected ranges:

```text
normal:      2021-07-08  2022-01-25  2022-11-15
pagination:  2023-05-16  2023-05-17  2023-05-18  2023-05-19  2023-05-22
             2023-05-23  2023-05-24  2023-05-25  2023-05-26  2023-05-30
early-close and pre-split: 2025-11-28
post-split:                 2025-12-15
```

The sample contains 14 full sessions, one early close, and 14,742 expected RTH symbol/timestamp
coordinates. Its session-list fingerprint is
`6ef4f2ae14416050e198df2394dec4c20aca01d3bcb985bdeb4a8d1c718c00ed`.

### Proposed budget and gates

The proposal contains six raw logical chains. It requires at least seven and permits at most 11
requests and responses, 16 MiB total, 8 MiB per page, 120 requests per minute, one credential load,
and zero retries. The 10-session range contains 10,140 canonical RTH rows before extended-hours
records, so it must use at least two pages and reach all 13 symbols.

PASS would require immutable raw-first response retention, raw-bound validation, extended-hours
tolerance only inside the request bounds, deterministic RTH projection, exact canonical
completeness, exhausted nonrepeating pagination, a complete independently reviewed unit-changing
action ledger, and exact synthetic share-unit controls. Those gates remain capable of failing.

## Independent review

The [independent review](../../config/research/program-006-source-qualification-forensic-analysis-independent-review-v1.json)
passed all eleven required challenges with no findings. It binds the terminal failure, terminal
review, forensic analysis, and Program 007 proposal by exact SHA-256 and fingerprint. Its own
SHA-256/fingerprint is
`103c58c47b0c07c768bd5b3efc577704a74f83cdd223f9945b2df00a3b6f099a` /
`0d389c0209753a64dbe0362dba9b817f33103e3a0b7c7ed89164e2c2747d32fe`.

Before any authority, Program 007 still needs the complete public action ledger, a raw-first
implementation, focused synthetic checks, a finding-free implementation review, full quality gates, clean
synchronized main, a new exact one-use authority proposal, and separate explicit user authorization.
This report and proposal authorize none of those actions.
