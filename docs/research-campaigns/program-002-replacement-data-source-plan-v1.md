# Program 002 replacement data-source plan v1

Status: **PROSPECTIVE**. Source requests, acquisition, and strategy execution are **NOT AUTHORIZED**. Only the separate independent-review artifact can mark this plan reviewed.

## Decision

Recommend Massive Stocks Business as the sole prospective replacement source. It is the only evaluated product that documents both SIP-derived U.S. stock bars/trades and historical NBBO. No fallback is named. If Massive fails its legal, adjustment, entitlement, structural, completeness, or quote-density qualification, Program 002 stops and needs a new user-authorized prospective plan.

This decision does not buy a subscription, load a credential, request data, implement a connector, admit a dataset, or run a strategy.

## Frozen requirements

The machine-readable source-neutral requirements are in `config/research/program-002-replacement-data-source-plan-v1.json`. They were fixed before the recommendation and preserve:

- the thirteen-symbol universe and SPY's context/benchmark role;
- UTC bar-open five-minute OHLCV over XNYS regular sessions;
- 78 bars per full session and 42 per early close for every symbol;
- all six five-minute components for each required thirty-minute bucket;
- provider-adjusted-all-v1 compatibility for splits, cash dividends, and spin-offs;
- historical consolidated NBBO for all 73 sessions and nine clocks;
- at least 57 of 60 eligible quote observations in every symbol/window;
- immutable raw bytes, hashes, deterministic normalization, and private retention rights;
- the frozen whole-session missing-data disposition, chronology, and search budget.

The requirements reject force fill, interpolation, synthetic prices, symbol omission, replacement dates, candidate exceptions, delayed-fill workarounds, and result-driven source changes.

## Provider comparison

| Provider | Bars | Historical quotes | Market definition | Decision |
|---|---|---|---|---|
| Massive | SIP-derived qualifying-trade aggregates and raw trades; 20+ years | Historical NBBO since 2003 | CTA/UTP SIP | Conditional primary |
| Databento | Direct venue and derived consolidated products | Venue or synthetic BBO; later consolidated products do not cover 2020 | Proprietary direct feeds, not SIP | Reject |
| Tiingo | Beta consolidated historical bars; IEX production alternative is one venue | No documented historical consolidated quote-event endpoint | Derived consolidated metrics or IEX | Reject |

Databento would require reconstructing a national market from proprietary venue feeds. Its own documentation distinguishes that synthetic market from official SIP NBBO. Tiingo cannot meet the historical quote contract, and its paid-plan terms require deletion after subscription ends absent a separate agreement. Neither is a scientifically neutral fallback.

## Massive semantics

The proposed bars are Massive's provider-generated five-minute custom aggregates. Massive documents that the aggregates use qualifying trades and emit no bar when no qualifying trade occurs. An absent required aggregate remains missing under the frozen whole-session disposition.

Raw SIP trades are qualification evidence only. A bounded audit may apply a separately frozen Massive condition, correction, timestamp, and bucketing contract and compare the result with provider aggregates. Raw trades may diagnose an omission; they may never fill one. Aggregating all prints would change OHLCV and volume to escape the missing-data rule.

Massive documents only split adjustment for REST aggregates and no adjustment for flat files. Program 002 requires the frozen all-adjusted semantics, including cash dividends and spin-offs. Before any market-data request, authoritative documentation or written terms must define exact factor, price, volume, and as-of behavior. A later implementation plan must freeze that mapping. Failure ends qualification before transport.

Historical quotes come from Massive's per-ticker NBBO endpoint. Sampling uses the nanosecond SIP timestamp. Participant timestamps remain raw provenance. The existing sixty-instant causal window and 57/60 gate stay unchanged.

## Known MDY checks

Qualification checks all thirteen symbols on the five affected full sessions:

- 2020-12-04;
- 2021-02-03;
- 2021-02-05;
- 2021-02-10;
- 2021-02-22.

All nine exposed MDY coordinates must exist as provider aggregates. If Massive also omits a coordinate and its raw feed has no eligible trade, confidence increases that the interval had no eligible market observation, but the session still fails Program 002. If an eligible raw trade exists while the aggregate is absent, qualification fails for aggregate inconsistency.

## Source qualification

The future one-use sample contains nine bar sessions: the five known-gap sessions, full controls on 2020-07-27, 2023-07-17, and 2026-07-15, and the 2022-11-25 early close. This is 8,658 expected aggregate rows.

The raw-trade audit is limited to MDY on the five known-gap sessions and SPY on 2023-07-17. Quote density is checked on 2020-07-27, 2021-02-16, 2023-07-17, and 2026-07-15 at all nine clocks for all thirteen symbols: 468 symbol/windows and 28,080 possible one-second observations.

The one-use authority must cap the run at exactly 630 allowed logical request chains: 117 aggregate symbol-sessions, six raw-trade symbol-sessions, 468 quote symbol-windows, and 39 corporate-action symbol-endpoint pairs. It also caps the run at 5,000 HTTP pages, 5 GiB of response bytes, one credential load, HTTPS GET to `api.massive.com`, and no redirects. Any failure consumes the authority and permits no fallback. A pass receipt contains only structural source evidence, not candidate output.

## Acquisition design

A future Massive adapter stays behind the existing dataset/acquisition boundary and imports no strategy, PAPER, order, broker, or live module. It uses the provider-specific `PROGRAM_002_MASSIVE_API_KEY`; the key never reaches research workers. Massive is a data vendor, so a dedicated unused broker account is unnecessary. A dedicated Program 002 API key under the licensed account is required.

Raw response bytes, request identities, request IDs, cursor chains, timestamps, corporate-action records, and condition specifications are stored create-only and hashed. Normalized Decimal OHLCV is sorted by symbol and UTC timestamp. Publication is content-addressed, create-only, and independently reviewed before later use.

The future exposed authority may bind only:

- 2020-06-26 through 2020-07-24 context-only bars;
- 2020-07-27 through 2022-07-25 exposed block 1;
- 2022-07-26 through 2024-07-26 exposed block 2;
- 2024-07-29 through 2026-07-31 exposed block 3;
- the frozen 73-session by nine-clock quote grid.

Controlled A and B remain sealed and outside this plan's acquisition authority.

## Price and license

Massive lists Stocks Business at $2,499 per month with 20+ years of historical trades and quotes, minute aggregates, flat files, and business use. Expected source qualification plus exposed acquisition is $2,499 to $4,998 if later approvals take one or two billing months. Taxes, negotiated terms, and future prices are excluded.

The $199 individual Advanced plan has the technical history but is not admissible under the public individual terms for this workflow. Before spend or transport, the Business contract must expressly permit internal non-display research, automated retrieval, immutable raw and normalized retention after subscription ends, deterministic derived bars, internal hashes/manifests/backups, and reproducible backtests. No raw data will be redistributed.

Official documentation was retrieved on 2026-08-27. Exact titles, URLs, and facts used are recorded in the machine artifact.

## Next authority

After finding-free independent review and merge, the next possible authorization is **ONE-USE SOURCE QUALIFICATION ONLY** for the exact Massive sample above. That later authority must bind the implementation, semantic contract, credential identity hash, request/byte ceilings, one-use claim, and all-false strategy authorities.

It must not authorize full acquisition or strategy execution.
