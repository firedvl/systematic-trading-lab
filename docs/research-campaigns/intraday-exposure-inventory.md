# Intraday exposure inventory

Machine inventory: `config/research/intraday-known-exposures-v1.json`.

Inventory fingerprint: `0666996faabb50abce0b8959c49980e36a655ea290618bc1463342d2ab5122f9`.

Candidate selection: `config/research/intraday-v3-period-selection-v2.json`.

Selection fingerprint: `c2718c3871bb95e22d4647e119f6bfb54cd51ec7b1b2cc472cfa1a7dfbcfc5d0`.

The superseded `intraday-v3-period-selection-v1.json` remains historical evidence.

## Audit boundary

The audit covered current source, configuration, documentation, tests, committed evidence metadata,
Git history, historical campaign files, and relevant issue and pull-request discussion at foundation
commit `d03be5eaa1e5d2d360424a6c0d06c1ce0bc6a723`. It fetched no prices or bars and did not inspect
protected holdout rows. Ignored runtime stores, CI artifacts, other clones, provider dashboards, and
human memory remain outside repository proof.

Real-market acquisition disqualifies validation even when no strategy result was read. Synthetic
fixtures and date-only examples do not become market exposure. Unknown or external evidence keeps
universal freshness unresolved, but it does not imply possession of market bars that did not yet
exist. Prospective freshness is a separate, narrower property.

## Findings

| Evidence | Range | Class | Validation effect |
| --- | --- | --- | --- |
| Validated Alpaca daily acquisition, SPY/QQQ/IWM/TLT/GLD | 2020-07-27–2026-07-31 | real-market-data-acquired-no-result | disqualifies |
| Committed daily training and validation results | 2020-07-27–2025-12-31 | real-market-result-observed | disqualifies |
| Strategic-allocation protected holdout result; exact subrange unavailable, so full acquired 2026 segment is used | 2026-01-02–2026-07-31 | real-market-result-observed | disqualifies |
| Intraday V1 SPY/QQQ `5m` Training acquisition rejected before publication | 2025-07-01–2025-12-31 | real-market-data-acquired-no-result | disqualifies |
| Intraday V2 SPY/QQQ `5m` 60-candidate results | 2025-07-01–2026-06-30 | real-market-result-observed | disqualifies |
| Paper holdings, account state, fills, and 1,008 healthy observations | 2026-08-04–2026-08-11 | real-market-data-acquired-no-result | disqualifies |
| Deterministic intraday unit fixtures | 2025-11-26–2026-01-05 | synthetic-fixture | does not disqualify or certify |
| Documentation and V3 unit-test date examples | 2025-01-02–2026-08-07 | date-only-reference | does not disqualify or certify |
| Dated production IEX quote-read activity | unknown | unknown-or-external | freshness unresolved |
| Ignored local state, CI artifacts, other clones, provider records, and human memory | unknown | unknown-or-external | freshness unresolved |

The daily acquisition envelope and observed-result entries stay separate because acquisition and
strategy observation are distinct exposure classes. The strategic-allocation range is deliberately
conservative: committed evidence proves a reviewed 2026 result but does not recover its exact
subrange. Source and policy prove IEX quote-read capability, not the complete dated set of executed
reads, so the inventory does not invent quote timestamps.

## Candidate periods

Calendar code derived all timestamps and counts from XNYS metadata. No market data was acquired or
inspected.

| Role | Dates | First and last UTC `5m` opens | Sessions | Opens per symbol | Two-symbol opens |
| --- | --- | --- | ---: | ---: | ---: |
| Training | 2025-07-01–2026-06-30 | `2025-07-01T13:30:00Z`–`2026-06-30T19:55:00Z` | 251 | 19,470 | 38,940 |
| Validation A | 2026-10-01–2026-12-03 | `2026-10-01T13:30:00Z`–`2026-12-03T20:55:00Z` | 45 | 3,474 | 6,948 |
| Validation B | 2026-12-04–2027-02-09 | `2026-12-04T14:30:00Z`–`2027-02-09T20:55:00Z` | 45 | 3,474 | 6,948 |
| Validation C | 2027-02-10–2027-04-15 | `2027-02-10T14:30:00Z`–`2027-04-15T19:55:00Z` | 45 | 3,510 | 7,020 |

Training deliberately reuses V2's exposed window and is training-only. Validation A moved from
August 14 to October 1 so review, merge, and main attestation need not race the first bar. Validation
B and C are the next two 45-session XNYS blocks. The choice used calendar metadata only. Each block
exceeds the unchanged 20-session floor. Session count does not prove activity, returns, or
qualification.

## Freshness decision

Independent review found no dated overlap in Validation A/B/C. Universal freshness remains false
because ignored runtime state, provider records, other clones, and human exposure cannot be fully
known. The exact inventory, selection, plan, and qualification binding were GitHub/main-attested with
trusted Sigstore transparency-log cutoff `2026-08-13T21:52:05Z`, before Validation A's first bar at
`2026-10-01T13:30:00Z`. The author-recorded selection date remains descriptive. The static selection
artifact records `prospective_market_data_freshness: false` and `approved_for_v3_validation: false`
for every validation block. The verified seal establishes the required prospective publication
timing without mutating that artifact; it does not prove universal freshness or approve validation
data. Local time, commit timestamps, file mtimes, and caller-entered verification time do not. The
seal paths use the strict inventory and selection parsers, so a known overlapping acquisition blocks
sealing even after dependent fingerprints change.

The final plan fingerprint is
`5e81cf8f0db1143f293a0f93900f1e797718443a559c1caaaa2e986851d5241a`.
Committing it alone created no runtime state. An operator later materialized the verified sealed
campaign with one seal row, one plan row, and 60 pending reservations. Dataset bindings, bound specs,
source reviews, source bindings, results, publications, and conflicts remain zero. The canonical
sealed checkpoint SHA-256 is
`ab42ef31e87e9c09b59aa417b33d6821e5e90eb05d7ada19e2a9dfed8001f6fb`. No V3 dataset has been
acquired, no V3 candidate has run, no V3 result has been observed, and no V3 qualification has passed.

All four datasets must validate and bind atomically before candidate 1. Validation C's final bar
opens at `2027-04-15T19:55:00Z` and completes at `2027-04-15T20:00:00Z`. Candidate 1 cannot legally
run before that completion time, and may run later only after dataset binding and source review.
