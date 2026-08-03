# Data policy

Initial scope is adjusted regular-session daily OHLCV for SPY, QQQ, IWM, TLT, and GLD. Preserve provider, request and actual ranges, retrieval time, raw hashes, schema and normalization versions, adjustment and calendar policy, validation evidence, missing and duplicate intervals, conflicts, quarantine counts, parent version, and final fingerprint.

Raw and normalized evidence is immutable. A dataset version ID binds the provider, sorted symbol set, timeframe, requested range, adjustment policy, schema, normalization and calendar versions, raw artifact hash, and normalized-bar fingerprint. A changed snapshot for the same stable request links to its latest cataloged parent; an exact repeat returns the existing version after its stored artifacts pass validation. Identical bars from different providers or requests remain separate versions.

Normalize timestamps to UTC, reject non-finite or non-positive prices, negative volume, impossible OHLC, duplicates, and non-increasing order. Record missing sessions from the XNYS exchange calendar rather than treating every weekday as a trading day. Never infer a price or corporate action. Raw provider records are retained as canonical JSON Lines and normalized bars as deterministic Parquet; prices remain exact decimal strings in Parquet.

The read-only Alpaca adapter requests `adjustment=all`, declares `provider-adjusted-all-v1`, uses the historical stock-bars API, and paginates with `next_page_token`. Synthetic fixtures declare `synthetic-no-actions-v1`. Unadjusted data is rejected before acquisition until a reviewed local processor covers splits, dividends, symbol changes, and delistings. Point-in-time membership remains future work.
