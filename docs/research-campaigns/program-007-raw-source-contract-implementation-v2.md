# Program 007 raw source contract implementation v2

## Status and correction

Program 007, `multi-hour-sector-etf-research-006`, remains
`PROPOSED-NOT-AUTHORIZED`. The raw-first source implementation is complete for synthetic use, but
the public unit-changing action ledger is not complete enough for dataset admission.

This report supersedes the ledger-coverage and next-gate claims in v1 without changing the v1
artifact or report. V1 treated eight no-action conclusions as complete. Independent review found
that the cited identity records and selected filings did not prove full-period forward-split
coverage. V2 records the evidence that can be defended, marks IWM, MDY, and SPY unresolved, and
blocks ledger-backed normalization, dataset admission, and any one-use authority proposal.

Program 006 remains `TERMINAL-FAIL-CONSUMED-NO-RETRY`. No Program 006 private observation was read
or copied for this correction.

## Raw-first implementation

The offline module still fixes the future request identity to raw Alpaca SIP five-minute bars:

- `GET https://data.alpaca.markets/v2/stocks/bars`
- `feed=sip`, `timeframe=5Min`, `adjustment=raw`, `sort=asc`, and `limit=10000`
- `asof=2026-07-31` with the exact inclusive frozen bounds
- redirects disabled and zero retries

The module has no provider client, credential API, or CLI activation path. It accepts only an
injected page source. Each invocation first creates an immutable request intent. A bounded response
is then retained byte-for-byte with its SHA-256 receipt before JSON parsing or row-semantic
validation. A process restart validates a retained page without another source call; an ambiguous
send cannot be retried.

Raw validation accepts valid in-bounds pre-market and after-hours rows on an XNYS session date. It
rejects malformed JSON, foreign symbols, invalid timestamps or OHLCV, weekend or holiday rows,
misalignment, out-of-bound rows, duplicate coordinates, oversized pages, pagination cycles, and
budget overruns after safe retention. The authoritative XNYS calendar then projects exact regular
session bar opens. Extended-hours rows remain private raw evidence and never enter the canonical
research projection. Missing any required symbol/bar coordinate fails the selected session; early
closes use their shorter calendar-derived grid.

The six frozen chains remain unchanged. They require seven responses in the expected synthetic
shape, allow at most eleven responses, cap each page at 8 MiB and the run at 16 MiB, allow one future
credential load, and permit zero retries. The frozen sample has 14,742 canonical coordinates.

## Public action evidence

Ledger v2 covers the required `2020-06-26` through `2026-07-31` chronology but resolves only ten of
thirteen symbols:

| Symbol | Coverage | Conclusion | Applicable action or evidence basis |
| --- | --- | --- | --- |
| IWM | Incomplete | Coverage unresolved | iShares identity page; 1,038-file SEC Trust candidate manifest, 383 IWM subject documents; NYSE `corpax` screen |
| MDY | Incomplete | Coverage unresolved | 54-file SEC corpus; NYSE `corpax` screen |
| SPY | Incomplete | Coverage unresolved | 68-file SEC corpus; NYSE `corpax` screen |
| XLB | Complete | Action recorded | 2-for-1 forward split effective 2025-12-05 |
| XLE | Complete | Action recorded | 2-for-1 forward split effective 2025-12-05 |
| XLF | Complete | No applicable action found | 51-file Select Sector SPDR SEC corpus; NYSE `corpax` screen |
| XLI | Complete | No applicable action found | 51-file Select Sector SPDR SEC corpus; NYSE `corpax` screen |
| XLK | Complete | Action recorded | 2-for-1 forward split effective 2025-12-05 |
| XLP | Complete | No applicable action found | 51-file Select Sector SPDR SEC corpus; NYSE `corpax` screen |
| XLRE | Complete | No applicable action found | 51-file Select Sector SPDR SEC corpus; NYSE `corpax` screen |
| XLU | Complete | Action recorded | 2-for-1 forward split effective 2025-12-05 |
| XLV | Complete | No applicable action found | 51-file Select Sector SPDR SEC corpus; NYSE `corpax` screen |
| XLY | Complete | Action recorded | 2-for-1 forward split effective 2025-12-05 |

State Street's issuer notice, a MIAX corporate-action alert, and Select Sector SPDR Trust SEC Note
13 agree on all five split symbols, the 2-for-1 ratio, and the effective boundary:

- [State Street issuer notice](https://investors.statestreet.com/investor-news-events/press-releases/news-details/2025/State-Street-Investment-Management-Announces-Share-Splits-for-Five-Select-Sector-SPDR-ETFs/default.aspx)
- [MIAX corporate-action alert](https://www.miaxglobal.com/alert/2025/12/04/miax-exchange-group-options-markets-corporate-action-alert-spdr-stock-1)
- [Select Sector SPDR Trust March 2026 report](https://www.sec.gov/Archives/edgar/data/1064641/000119312526256847/d128483dncsrs.htm)

The public NYSE `corpax` crawl used 319 non-overlapping date intervals and 326 exchange queries. It
retained response hashes and counts for 11,345 unique dated events, found no out-of-window dated
record, and found twelve target name or product-name records. Those twelve records support identity
continuity and do not change share units. The NYSE client specification states that this public
scope excludes forward splits, which belong to the separate Ex-Date Corporate Actions product.
The crawl therefore cannot close IWM, MDY, or SPY forward-split coverage.

The SEC corpus digests are:

- Select Sector SPDR Trust, 51 documents:
  `c99870acd2ae8360c9c99c4e0abbc44318f787cf412096e8676324d9eda9c752`
- iShares Trust, 1,038 candidate filings and 383 IWM subject documents:
  `3eea92ce0d8af4be24671e6fabe49ab560c99b68b5230847666e8018233247c1`
- SPY, 68 documents:
  `6d5e8853788fa245b40daa3f47583da2f05b70212c68380b929a155f8ea5e16a`
- MDY, 54 documents:
  `6322b7a15c642e4c376e383b3b14ee883ac101b5312302bf9bf2a9ccdc6839be`

The IWM corpus is Trust-wide, and the SPY and MDY corpora do not close forward-split and late-period
coverage. V2 therefore makes no no-action claim for those three symbols. Any unresolved symbol
blocks the entire Program 007 dataset before normalization or strategy use.

## Unit semantics and controls

For a transformable split, the feature basis is the share unit in effect on the session being
computed. A source-session share count maps across each effective boundary by the exact
`new_shares / old_shares` `Fraction`; mapping backward divides by the same ratio. The effective
session is already in post-action units. Ratios multiply for sequential actions. The synthetic
tests cover 2-for-1, 3-for-2, 1-for-5 reverse, and multiple-action cases.

Only prior-20-session same-clock relative-volume share counts require this transform. Raw
same-session prices remain unchanged because `(f*p1)/(f*p0)-1 = p1/p0-1`, and raw dollar volume is
unchanged because `(p/r)*(v*r) = p*v`. A spin-off, identity break, or other action without an
authoritative deterministic share-unit map fails dataset admission; the code does not invent a
volume transform.

The 2025-11-28 early-close control remains pre-split for XLB, XLE, XLK, XLU, and XLY. The
2025-12-15 control remains post-split. A 2025-11-28 same-clock share count maps to the 2025-12-15
basis by exactly `2`. These controls remain valid, but the unresolved IWM, MDY, and SPY coverage
still blocks use of the complete thirteen-symbol dataset.

## Immutable bindings

- Implementation source commit:
  `81926c6d05d40a506b3ff624e566ca5a232ffd2e`
- Implementation root:
  `e89876761fe584f36a59b2dae30d418305b556f750b2163e413f483fd84e916d`
- Implementation artifact SHA-256/fingerprint:
  `8f8183b8e18b6f5347e7a995924ef004b7c7d3b8c4c7a0d135368189a242bad4` /
  `668c9c099477d4895f417eec7536c7eb7ddc83c4957ab8cefe7a4375c042e72d`
- Ledger v2 SHA-256/fingerprint:
  `3b815581d0da66db427243bce34f9ced5021f73719acd2b5d5e277d57065d53a` /
  `0ec39d6f38d469e099862173ff710c0e737b39b464e233e291c9e9b20c089c25`
- Ledger schema SHA-256:
  `36b74f6b8facd55176eba8d08075d6eb3276ae938bf424c3af75adaba81c8d78`
- NYSE retrieval manifest SHA-256/fingerprint:
  `48b85bb63c02e59b8538eed741237d9d9a386dc36caa4c3cc1e7b5856bd735f5` /
  `b0fc71436088824df6126bbfd950232e0b55da6233b34c11b40480c3495dcbeb`

Ledger v1, its schema, implementation artifact v1, and report v1 remain byte-identical historical
records. They are not admissible sources of current no-action conclusions.

## Authority and next gate

Focused synthetic tests, Ruff, strict mypy, the secret scan, and Draft 2020-12 schema validation
pass. These checks made zero Alpaca or market-data provider requests, read no credential value or
presence state, read no Program 006 private page, and generated or read no strategy return. The 326
NYSE calls were authorized public exchange research and are recorded separately.

Provider contact, subscription purchase, credential access, source request, source qualification,
acquisition, dataset admission, strategy work, research qualification, controlled evaluation,
protected holdout, PAPER, broker write, and live execution remain false.

The next step is not an authority proposal. First obtain complete public issuer or exchange
unit-changing-action coverage for IWM, MDY, and SPY over the frozen chronology, bind it in a new
strict ledger version, pass independent review, and merge that correction. Only then may a separate
reviewed one-use Program 007 raw Alpaca SIP structural source-qualification authority proposal be
created for a new explicit user grant. This work does not create, authorize, or execute that
proposal.
