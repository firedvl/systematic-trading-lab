# Intraday exposure inventory

Machine inventory: `config/research/intraday-known-exposures-v1.json`.

Inventory fingerprint: `0666996faabb50abce0b8959c49980e36a655ea290618bc1463342d2ab5122f9`.

Candidate selection: `config/research/intraday-v3-period-selection-v1.json`.

Selection fingerprint: `d371488a56a1b960ebb54c9d5a1cfe46e043523e21c99a49da392e69cc75d0b1`.

## Audit boundary

The audit covered current source, configuration, documentation, tests, committed evidence metadata,
Git history, historical campaign files, and relevant issue and pull-request discussion at foundation
commit `d03be5eaa1e5d2d360424a6c0d06c1ce0bc6a723`. It fetched no prices or bars and did not inspect
protected holdout rows. Ignored runtime stores, CI artifacts, other clones, provider dashboards, and
human memory remain outside repository proof.

Real-market acquisition disqualifies validation even when no strategy result was read. Synthetic
fixtures and date-only examples do not become market exposure, but they also do not certify
freshness. Unknown or external evidence keeps freshness unresolved.

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
| Validation A | 2026-08-14–2026-10-16 | `2026-08-14T13:30:00Z`–`2026-10-16T19:55:00Z` | 45 | 3,510 | 7,020 |
| Validation B | 2026-10-19–2026-12-18 | `2026-10-19T13:30:00Z`–`2026-12-18T20:55:00Z` | 44 | 3,396 | 6,792 |
| Validation C | 2026-12-21–2027-02-26 | `2026-12-21T14:30:00Z`–`2027-02-26T20:55:00Z` | 46 | 3,552 | 7,104 |

Training deliberately reuses V2's exposed window and is training-only. Validation A begins after the
2026-08-13 review cutoff and the last dated paper-account observation. Validation B and C continue as
chronological, non-overlapping forward blocks. Each validation block exceeds the unchanged policy's
20-session coverage floor. Session count does not prove active-session, trade-count, return, or
freshness gates; those remain unknown until later controlled execution.

## Freshness decision

Independent review found no dated repository-known overlap in Validation A/B/C. It did not establish
universal freshness because ignored runtime state, provider records, other clones, and human exposure
remain unresolved. All three periods therefore have status
`repository-known-overlap-safe-pending-external-attestation` and
`approved_for_v3_validation: false`.

No final V3 plan or plan fingerprint exists. No V3 dataset has been acquired, no V3 candidate has
run, no V3 result has been observed, and no V3 qualification has passed. A separate external
attestation must approve or reject each validation period before a campaign can be sealed.
