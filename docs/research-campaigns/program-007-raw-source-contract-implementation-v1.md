# Program 007 raw source contract implementation

## Status

Program 007, `multi-hour-sector-etf-research-006`, remains
`PROPOSED-NOT-AUTHORIZED`. This slice implements and tests the reviewed raw-first architecture. It
does not add an Alpaca client, credential API, CLI activation command, authority root, provider
request, source result, dataset, or strategy path.

Program 006 remains `TERMINAL-FAIL-CONSUMED-NO-RETRY`. None of its private observations were read
or copied for this work.

The non-authorizing implementation artifact is
`config/research/program-007-raw-source-contract-implementation-v1.json`. It binds the unchanged
proposal, exact public ledger, schema, source, tests, and implementation commit.

## Raw-only request contract

The offline module fixes this future request identity:

- `GET https://data.alpaca.markets/v2/stocks/bars`
- `feed=sip`
- `timeframe=5Min`
- `adjustment=raw`
- `sort=asc`
- `limit=10000`
- `asof=2026-07-31`
- inclusive frozen `start` and `end`
- redirects disabled

The module accepts only an injected page source. It cannot load credentials or create network
transport. The six frozen chains remain seven to eleven total responses, 16 MiB total, 8 MiB per
page, 120 requests per minute, one future credential load, and zero retries. The eleven-request
total is itself below the 120-per-minute ceiling.

## Raw-first ordering

For each response, the code performs this sequence:

1. Create an immutable request intent before invoking the injected source.
2. Enforce response and byte ceilings.
3. Atomically retain the exact body and SHA-256 receipt in a create-only private page directory.
4. Parse the retained bytes.
5. Write a separate immutable validation outcome.
6. Continue pagination only after the page passes structural and token checks.

If an invocation has no retained response, restart treats the send as ambiguous and refuses to
retry. If a process stops after raw retention, restart validates the retained bytes without another
source call. A malformed or semantically invalid retained response keeps its exact body, receipt,
and non-secret failure outcome.

## Raw and canonical validation

Raw validation requires unique JSON keys, the expected top-level and bar fields, one of the thirteen
symbols, UTC five-minute bar-open alignment, inclusive request bounds, an XNYS session date, finite
positive OHLC and optional VWAP, nonnegative volume and trade count, valid OHLC ranges, unique
symbol/timestamp coordinates, no more than 10,000 rows, and a null or nonempty next-page token.

A valid pre-market or after-hours row on an XNYS session date may pass raw validation. It remains in
the private raw body and is excluded only when the repository XNYS calendar projects exact regular
session bar opens. Weekend, holiday, malformed, misaligned, out-of-bound, duplicate, and foreign
rows fail after retention.

Canonical completeness is the Cartesian product of all thirteen symbols and every authoritative
XNYS five-minute bar open inside the frozen bounds. Normal sessions have 78 opens. Early closes use
the shorter calendar-derived grid. A missing required coordinate makes the whole session ineligible
and fails source qualification; extended-hours data cannot fill it.

## Pagination and manifests

Page indexes and incoming tokens are contiguous. The code rejects token reuse, token cycles,
repeated page hashes, repeated coordinates across pages, a nonterminal empty page, an outgoing token
at the page ceiling, and global request, response, page-byte, or total-byte overruns. Page identity
binds the chain, page index, incoming and outgoing token, and raw response SHA-256.

The future private manifest records request identity, page index, tokens, response hash and byte
count, parse and projection status, and raw, canonical, and extended-hours row counts. The public
summary contains only aggregate counts, an aggregate private-evidence fingerprint, and the public
ledger identity. It excludes request URLs, tokens, filenames, timestamps, and market values.

## Public unit-changing action ledger

The strict ledger covers `2020-06-26` through `2026-07-31`. The start supplies the twenty-session
prehistory needed by the first feature session. Conclusions are limited to that chronology.

| Symbol | Bounded conclusion | Applicable Program 007 action |
| --- | --- | --- |
| IWM | No applicable action found | None; its 2-for-1 split effective 2005-06-09 is outside scope |
| MDY | No applicable action found | None |
| SPY | No applicable action found | None |
| XLB | Action recorded | 2-for-1 forward split effective 2025-12-05 |
| XLE | Action recorded | 2-for-1 forward split effective 2025-12-05 |
| XLF | No applicable action found | None; the 2016 XLRE distribution changed no XLF unit count |
| XLI | No applicable action found | None |
| XLK | Action recorded | 2-for-1 forward split effective 2025-12-05 |
| XLP | No applicable action found | None |
| XLRE | No applicable action found | None |
| XLU | Action recorded | 2-for-1 forward split effective 2025-12-05 |
| XLV | No applicable action found | None |
| XLY | Action recorded | 2-for-1 forward split effective 2025-12-05 |

State Street announced all five splits on 2025-11-20. Holders of record at the 2025-12-02 close
received the additional shares after the 2025-12-04 close, and split-adjusted trading began before
the 2025-12-05 open. The issuer notice, MIAX exchange alert, and SEC Note 13 agree on the symbols,
ratio, and boundary:

- [State Street issuer notice](https://investors.statestreet.com/investor-news-events/press-releases/news-details/2025/State-Street-Investment-Management-Announces-Share-Splits-for-Five-Select-Sector-SPDR-ETFs/default.aspx)
- [MIAX corporate-action alert](https://www.miaxglobal.com/alert/2025/12/04/miax-exchange-group-options-markets-corporate-action-alert-spdr-stock-1)
- [Select Sector SPDR Trust March 2026 report](https://www.sec.gov/Archives/edgar/data/1064641/000119312526256847/d128483dncsrs.htm)

The eight no-applicable-action conclusions use bounded issuer identity, early and current SEC
financial or registration records, and the NYSE Arca public-notice rule. They do not claim that an
ETF has never had an action. Evidence is explicit per symbol in the ledger. Shared records include:

- [NYSE corporate-action notification policy](https://www.nyse.com/regulation/corporate-actions-market-watch-proxy-compliance)
- [IWM issuer page](https://www.ishares.com/us/products/239710/ishares-russell-2000-etf)
- [MDY 2026 registration](https://www.sec.gov/Archives/edgar/data/936958/000119312526026958/d77156d485bpos.htm)
- [SPY 2025 audited financial statements](https://www.sec.gov/Archives/edgar/data/884394/000119312526023648/d935960d497.htm)
- [Select Sector SPDR Trust 2025 annual report](https://www.sec.gov/Archives/edgar/data/1064641/000119312525308890/d66357dncsr.htm)

The ledger SHA-256 is
`d04c1c356cd4e5d56a8be7bd7ae81d168e69a43e287f928579c90a5700e04d21`; its canonical
fingerprint is `eb61c7a117973977bd2f7947c965f5f0d3061beee43635bd39f893da738ea921`.
The schema SHA-256 is
`183b3b0a103839efb177924ca80cab73b7335ebe582e4a17a7ba5450a40270e8`.

## Share-unit normalization

The basis is the share unit in effect on the session whose relative-volume feature is computed. For
each crossed action, map a source-session share count by the exact `new_shares / old_shares`
`Fraction`. The effective session is already in post-action units. Multiple actions multiply in
effective-date order. Mapping in the other direction divides by the same ratios. The rule therefore
handles 2-for-1, 3-for-2, 1-for-5 reverse, and sequential splits without floating-point rounding.

Only prior-20-session same-clock relative-volume share counts use this transform. Raw prices stay
unchanged. A same-session return is invariant because `(f*p1)/(f*p0)-1 = p1/p0-1`. Raw dollar
volume is also invariant because `(p/r)*(v*r) = p*v`. Program 007 therefore needs no historical
price-normalized view.

Spin-offs, identity breaks, and other actions without an authoritative deterministic share-unit
mapping do not receive an invented reciprocal volume rule. They fail dataset admission before any
strategy calculation, and missingness tolerance cannot override that failure.

## Frozen split control

The 2025-11-28 early-close session is pre-split for XLB, XLE, XLK, XLU, and XLY. The 2025-12-15
session is post-split. A prior-session same-clock volume from 2025-11-28 maps to the 2025-12-15 basis
by a factor of `2`. The dates and frozen sample remain unchanged.

The exact synthetic sample covers three normal sessions, the ten-session pagination range, the
early-close pre-split control, and the post-split control. It produces 14,742 canonical coordinates
in seven responses. One valid after-hours row in the pagination fixture remains raw-only.

## Authority and next gate

Provider contact, credential access, source requests, source qualification, acquisition, dataset
admission, strategy work, research qualification, controlled evaluation, protected holdout, PAPER,
broker writes, and live execution all remain false. No real provider request, credential read or
presence check, private observation read, or strategy calculation occurred.

After a finding-free independent implementation review and merge to clean synchronized `main`, the
next permitted step is to create and independently review a separate exact one-use Program 007 raw
Alpaca SIP structural source-qualification authority proposal. That proposal must bind the merged
implementation and ledger, retain the existing limits, and still requires a new explicit user grant.
This implementation does not create, authorize, or execute that proposal.
