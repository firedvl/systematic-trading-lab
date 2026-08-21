# Intraday Exposed 003 program

Status: runner implemented; strategy execution requires a clean exact merged implementation main.

Starting main: `9de63bfe3278091220ffbf88743daba7a24ddb1c`.

Plan SHA-256: `7d5edd0c52e80d42d322cfa2d3cf1d91ed10bc7c06cd5b418328ba8a3e649f22`.
Plan fingerprint: `ac8b3c029599fd912464020e57bbe3cdbde907f63d46f5a7ef748cab2655bc2e`.
Independent-review SHA-256: `ad9a2bb278cd98d3e74e7248cd12f8549b6e6bbecf4cd03d41f3bb9a7ba4665f`.
Independent-review fingerprint: `b3e3cad3a8489b1079b83b8f8fdf11dc93e96151ee8311603b3fdfe38fb637ab`.

## Purpose and non-adaptation rule

Intraday Exposed 002 remains terminally interrupted evidence. Exposed 003 is a new campaign that
will execute the exact frozen Exposed 002 exposed-research design under restart-safe attempt
semantics. It imports no Exposed 002 runtime row. Its new plan changes only campaign identities,
runtime locations, and interruption handling.

The Exposed 002 plan remains the research-design source of truth at exact SHA-256
`8acb778eec43dd53b56c65712b5a076bdc6126de3504d68114aa714e2474b17f` and fingerprint
`a255949e41c9776e82a04782c6183f5af1476a1dc97c36be4910e4d59424fb98`.
Its partial results may appear only as provenance. They did not change any family, parameter, grid,
chronology, cost, strategy mechanic, gate, cap, neighbor, or selection rule.

## Exact reused design

The plan loader verifies the complete Exposed 002 plan, amendment, data binding, reviews, and June
disposition before deriving any Exposed 003 configuration. It rekeys each `ie002-` candidate and
neighbor ID to `ie003-` and keeps every other configuration field exact.

- Ten families and 60 parent configurations remain unchanged.
- Each parent receives Normal and paired exact zero-cost discovery runs: 120 discovery rows.
- Discovery, four chronological walk-forward periods, stress, isolated delay, immediate-neighbor,
  concentration, cost-efficiency, and final-cohort gates remain unchanged.
- All 60 parents must finish discovery before the frozen uniform screen.
- The cohort remains zero to five candidates with at most one candidate per family.

The strategy source remains
`src/systematic_trading_lab/intraday_exposed_002_strategies.py` at SHA-256
`4c6cbc193b78d32a072ef5f71c1c179714c88d182887a97a2c5e031b54fc2ad4`. The engine source remains
`src/systematic_trading_lab/intraday_exposed_002_engine.py` at SHA-256
`bf62f6661b0beb2ac57b83668412b90a17255fd176fa559966ec0f5a64032c66`. A proven implementation
defect requires a stop and a separate documented decision before any strategy execution.

## Costs, data, and chronology

The cost model remains `intraday-execution-cost-model-001-v1`, SHA-256
`a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af`, fingerprint
`94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4`.

- Normal: SPY 0.09 bps, QQQ 0.17 bps, one five-minute delay bar, frozen SEC/TAF/CAT fees.
- Stress A: SPY 0.16 bps, QQQ 0.25 bps, two delay bars.
- Stress B: SPY 0.22 bps, QQQ 0.36 bps, three delay bars.
- Zero cost: no spread or monetary fees and one delay bar; diagnostic authority only.

The campaign reuses the four validated, physically pre-June SPY/QQQ datasets bound by Exposed 002.
No data reacquisition is allowed. Full artifact and catalog integrity must pass before runtime state
exists. Discovery starts on 2025-07-01. Later exposed folds end on 2025-12-31, 2026-02-27,
2026-04-30, and 2026-05-29 exactly as frozen.

## New identity and recovery boundary

- Program and campaign: `intraday-exposed-003`.
- Plan: `intraday-exposed-003-plan-v1`.
- Candidates: `ie003-f..`; reservations: `ie003q-..`; runs: `ie003r-..`.
- Runtime root: `.trading-lab/intraday-exposed-003`.
- Database: `intraday-exposed-003.sqlite3`.
- Reports: `run-reports/{run_id}.json` plus separate final freeze and report paths.

The campaign opts into `research-attempts-v1`. Each immutable run specification may receive at
most three append-only attempts. Only an expired no-result infrastructure lease permits the same
specification to retry. Completed results, candidate exceptions, data-integrity failures,
publication conflicts, failed gates, and an exhausted third attempt remain terminal. Active work
uses a 300-second lease and 60-second heartbeat. Canonical results are journaled once before
create-only publication and reconciled on restart.

Runner v1 subclasses the frozen Exposed 002 stage logic without changing an Exposed 002 file. Its
specifications, reservations, reports, runtime, and final evidence use Exposed 003 identities. It
passes each plan-bound `source_candidate_id` to the unchanged strategy factory and preserves the
existing evaluation-start wrapper, so strategy mechanics still receive the required `ie002-`
identity without importing an Exposed 002 result. Full dataset validation still precedes runtime
directory creation.

Attempt setup, output capture, heartbeat, and canonical publication errors do not become candidate
failures. Without a canonical result, they retain the active lease for expiry-based recovery.
Exceptions from strategy construction, replay, or report construction are terminal candidate
failures; bar-load failures are terminal data failures. A still-active lease produces no terminal
campaign report. Final evidence records every attempt and validates its database, freeze, JSON,
and create-only Markdown on restart.

## June disposition

June 2026 is ineligible before Exposed 003 strategy execution. The metadata-only disposition is
SHA-256 `af91ca3889327a402851e652592d842b43a31d04bba4aa2efe3305d855165efa`, fingerprint
`2c5b84269e255a78b41f591cbcfd79a684adb6159f6172733da4219e06ce5278`.

Committed exposure metadata records Intraday V2 real-market results through 2026-06-30. Zero June
rows and zero unconsumed authorizations in the active controlled registry do not restore freshness.
Exposed 003 must not read June or substitute another range. An empty cohort closes with no
controlled-qualified candidate. A nonempty cohort freezes as exposed-serious blocker evidence and
stops before controlled evaluation without claiming controlled qualification.

## Remaining gates

The independent prospective plan review passed with no findings. This plan grants no
strategy-result, controlled-evaluation, qualification, paper, broker-write, or live authority. The
isolated runner's independent review found and closed two issues: startup publication conflicts now
reach terminal evidence, and public status now verifies the final database and freeze. The final
review found no P0, P1, or P2 issue. Full local gates pass with 764 tests and four skips.
The first runtime state then requires a clean exact merged implementation main where `HEAD`, local
`main`, and `origin/main` match. Exposed 001/002, V1/V2/V3, Rapid-002/003/004, PAPER, broker/live,
and `strategic-allocation-21` evidence remain unchanged.
