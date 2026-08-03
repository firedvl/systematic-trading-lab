# Data policy

Initial scope is adjusted regular-session daily OHLCV for SPY, QQQ, IWM, TLT, and GLD. Preserve provider, request and actual ranges, retrieval time, raw hashes, schema and normalization versions, adjustment and calendar policy, validation evidence, missing and duplicate intervals, conflicts, quarantine counts, parent version, and final fingerprint.

Raw and normalized evidence is immutable. Corrections create a linked version. Normalize timestamps to UTC, reject non-finite or non-positive prices, negative volume, impossible OHLC, duplicates, and non-increasing order. Record determinable gaps. Never infer a price or corporate action. The fixture format is canonical JSON Lines; adopt Parquet before storing material provider history. Future design must cover splits, dividends, symbol changes, delistings, point-in-time membership, sessions, and provider corrections.
