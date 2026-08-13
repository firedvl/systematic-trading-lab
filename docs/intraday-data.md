# Intraday data foundation

The repository supports offline, research-only `1m` and `5m` OHLCV for U.S. equities and ETFs. The deterministic fixture covers SPY and QQQ across a normal XNYS session, a holiday, and an early-close session. Daily data support remains unchanged. Quotes, trades, extended hours, options, protected intraday holdout access, and broker execution remain out of scope.

## Architecture assessment

The existing system needed extension, not a second intraday stack:

1. `Timeframe`, the daily fixture, Alpaca acquisition, calendar validation, report metrics, sealed campaign plans, and qualification rules assumed daily bars. `OHLCVBar`, immutable storage, cataloging, and most portfolio accounting did not.
2. Dataset IDs and manifests already bound timeframe, provider, ranges, adjustment policy, schema, normalization, calendar, universe, raw evidence, and normalized data. This remains the dataset authority.
3. The Alpaca historical adapter was already read-only and paginated, but it rejected non-daily requests and discarded intraday clock time. It now supports `1Min` and `5Min`, derives the exact XNYS bar-open grid, and excludes transport-level extended-hours records from normalization without adding any order API.
4. Validation parsed OHLCV, duplicate, and ordering errors for every bar but checked missing coverage only for daily sessions. It now checks exact intraday intervals.
5. The XNYS dependency already supplied reviewed holiday and early-close schedules. The calendar boundary now derives bar opens from each actual regular-session open and close.
6. Per-symbol simulation was event-driven and reusable. Portfolio simulation assumed one complete timestamp group; that same boundary works for a complete multi-symbol intraday bar slice. Daily-only experiment and qualification contracts remain unchanged.
7. A timestamp alone did not state whether it meant bar open or bar close. Intraday manifests now bind `bar-open-utc-v1`; replay derives observability from timeframe duration.
8. Long-only weights, cash accounting, reductions-before-buys, basis-point costs, order events, trades, and equity ledgers are reused unchanged.
9. Experiment lifecycle, immutable provenance, chronological splits, range-limited reads, and holdout controls are structurally timeframe-neutral. Report annualization, regime evidence, sealed plan versions, and approved qualification gates still require an intraday-specific review before use.
10. Generic domain, calendar, provider, validation, dataset, Parquet, and simulator boundaries were extended. No separate intraday engine was created.

## Timestamp and range contract

An intraday bar timestamp is the bar's open time in UTC. A `1m` bar stamped `2025-11-26T14:30:00Z` covers `[14:30, 14:31)` and becomes observable at `14:31:00Z`. A `5m` bar with the same stamp covers `[14:30, 14:35)` and becomes observable at `14:35:00Z`.

Requested and actual dataset ranges use inclusive bar-open timestamps. Convert to exchange time with the `America/New_York` IANA zone; do not apply a fixed UTC offset. The XNYS calendar supplies DST, holidays, and early closes. Daily bars keep their existing `session-date-at-00:00-utc-v1` labels.

## Validation and evidence

For each expected symbol, validation derives every bar open from the actual XNYS regular-session bounds. The close boundary is exclusive, so no bar starts at the session close. This yields 390 one-minute or 78 five-minute intervals on a normal session and 210 or 42 on a 13:00 New York early close.

Missing intervals, duplicate timestamps, non-increasing per-symbol records, unexpected symbols, malformed OHLC, and invalid volume fail the import. For Alpaca, OHLCV validity applies to every mapped provider bar, including transport extras outside the requested grid. Evidence records the exact missing or invalid interval; no price is fabricated. Rejected imports write quarantine evidence and publish no dataset. Exact valid re-imports return the same content-addressed dataset and fingerprint.

The Alpaca adapter maps every returned bar before filtering. A malformed payload or bar therefore fails acquisition even when its timestamp is outside the requested grid. For a published dataset, every mapped transport record, including premarket, postmarket, and session-close-boundary extras, remains in immutable `raw.jsonl` and its fingerprint. If validation rejects the import, quarantine evidence retains the mapped acquisition records and their fingerprint instead. Valid requested-symbol records enter validation only when their UTC timestamp is an exact expected XNYS bar open. Invalid mapped records and unexpected symbols remain in the validation stream so they fail rather than disappear. Only valid requested-grid records can enter normalized Parquet. Raw transport extras are acquisition evidence, not members of the normalized requested dataset.

The manifest and dataset ID bind the timeframe, `bar-open-utc-v1` timestamp policy, `XNYS-regular-session-bars-v1` calendar policy, concrete provider adapter, provider feed when present, requested and actual range, adjustment policy, universe provenance, raw evidence, and normalized Parquet fingerprint.

## Acquisition boundary

`AlpacaHistoricalProvider` remains a GET-only historical stock-bars adapter. Manifests identify it as `alpaca-historical-v2` and record feed `iex`. It maps `1m` to `1Min` and `5m` to `5Min`, preserves provider bar-open timestamps in UTC, requests provider-adjusted IEX data, handles pagination, sets Alpaca's exclusive end to one duration after the last expected bar open, and filters normalized intraday input against that same exact XNYS grid. It has no submit or cancel method.

Provider credentials must remain outside the repository. `IntradayFixtureProvider` supplies deterministic offline evidence when credentials or network access are absent.

Committed `liquid-etfs-intraday-1m-v1` and `liquid-etfs-intraday-5m-v1` universe definitions bind issuer-sourced SPY and QQQ membership to each timeframe. Import deterministic evidence with `trading-lab data import-intraday-fixture --timeframe 1m|5m`. Read-only Alpaca imports use the same timeframe flag and require exact inclusive UTC bar-open bounds.
