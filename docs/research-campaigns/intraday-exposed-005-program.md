# Intraday Exposed 005 program

Status: terminal negative result; empty final cohort and no controlled evaluation.

Closeout: [Intraday Exposed 005 final report](intraday-exposed-005-final-report.md).

Plan SHA-256: `622d3ad769b12dad857bfe8ee60be4fa1a75b3f3d68becb9b750b323102fd811`.
Plan fingerprint: `8d30af60d84f1baaa2365096b898960bef759fbafc5215eba68bb81061819ba3`.
Prospective-review SHA-256: `e1ef2d6bb5651281aa6d757d9af12260fc51ce0114a8ca54e49626946507f838`.
Prospective-review fingerprint: `cdd8d0e3714a3bafead13869d5785c6f2a83b2e3fb33e3ab06e3829ff26457c3`.
June-disposition SHA-256: `af6aea5e8d7bd8360aa6af4ddc31e1e67a1be48476f6c8ab13197fe12515b3c0`.
June-disposition fingerprint: `6dad6480dc3b0379017d582bb2f29fc562f41379bb3065855c55eadf51f025dd`.

## Why this program exists

Intraday Exposed 004 stopped before any attempt or strategy execution because nested frozen
`MappingProxyType` values could not cross the spawned task queue. Its 120 reservations, database,
and failure evidence remain immutable. Exposed 005 is a clean successor with new identities. It
does not retry, reset, rebind, import, or reinterpret any Exposed 003 or 004 runtime row.

The transport correction has two parts:

1. The 005 runner canonicalizes each complete specification before reservation and dispatch.
2. The generic executor synchronously tests each task with the spawn pickler before it starts a
   worker.

Canonicalization changes only the in-memory transport representation. Canonical JSON and
fingerprints remain unchanged. An unsupported task or worker factory now fails before reservation,
worker start, claim, or campaign attempt.

## Frozen research design

The strict plan loader follows the 005 to 004 to 003 to 002 source chain and verifies:

- the same 60 parents across ten families and all 140 neighbor links;
- 120 paired Normal and exact zero-cost discovery runs;
- the same five periods and chronology through 2026-05-29;
- the same calibrated cost model, data bindings, engine, strategy mechanics, and event rules;
- the same discovery, walk-forward, stress, isolated-delay, neighbor, concentration,
  cost-efficiency, and final-cohort rules; and
- no prior runtime-row import or result-dependent design change.

Each 005 specification records its `ie005-`, source `ie004-`, source `ie003-`, and underlying
`ie002-` candidate identities. The unchanged strategy receives only the frozen `ie002-`
configuration.

## Coordinator and workers

One coordinator owns the campaign lock, deterministic stage order, reservation, barriers,
screening, freeze, and final report. It runs independent work in parallel only within one stage.

The bounded executor uses the multiprocessing `spawn` method and four workers by default.
`--workers N` accepts another positive count without entering any run identity. Each worker:

- owns at most one claimed run;
- constructs private read-only dataset services and a private period cache once per stage;
- heartbeats its 300-second lease every 60 seconds;
- runs the backtest outside database transactions; and
- publishes once through `research-attempts-v1`.

Results return in frozen input order. Completion timing cannot change screening or selection. A
worker exits after any task exception. The coordinator may replace that process for still-pending
work, but it never resubmits the errored task in the same stage.

## Restart and failure rules

Only an expired no-result infrastructure lease can make one exact run pending again. One run may
receive at most three append-only infrastructure attempts. Completed reports cannot be reclaimed.
Candidate exceptions, data-integrity failures, publication conflicts, and exhausted infrastructure
attempts are terminal.

SQLite keeps short `BEGIN IMMEDIATE` claim and publication transactions, rollback journaling, and
a 30-second busy timeout. Workers do not use SQLite as a computation workspace. WAL remains off so
the final single-file database hash covers all authoritative state.

## Identities

- Program: `intraday-exposed-005`.
- Candidates: `ie005-f..`.
- Reservations: `ie005q-..`.
- Runs: `ie005r-..`.
- Attempts: `ie005a-..`.
- Runtime root: `.trading-lab/intraday-exposed-005`.
- Database: `intraday-exposed-005.sqlite3`.
- Runner: `intraday-exposed-005-runner-v1`.
- Run report: `intraday-exposed-005-backtest-report-v1`.
- Final freeze: `intraday-exposed-005-final-freeze-v1`.
- Final report: `intraday-exposed-005-final-report-v1`.

## Launch gates

The launch-control artifact is bound at raw SHA-256
`6b431eb34de1cce4a0126fa10d42685bc55abf28587a15ade466912c0cbe3b94` and canonical
fingerprint `f05a789b5e4bcc71d21485d8c95237ac29fc864013521cd7a4b1e8383fbded1d`. It binds:

- the exact merged implementation commit and named source-file hashes;
- all seven repository quality gates;
- exact one-worker and four-worker equivalence on completed Exposed 003 specifications selected
  without metrics;
- unchanged source database and dataset bytes;
- the health-only Exposed 003 stop and preservation evidence;
- the hash-bound Exposed 004 pre-attempt failure disposition; and
- an independent finding-free control review.

Fresh equivalence from implementation main `1d6744432ed2635ce6ae19268b64b1c89fc0017d`
replayed four fixtures in `3936.880792` seconds with one worker and `1149.137974` seconds with
four, a `3.426` speedup. Every specification, fingerprint, fill sequence, round trip, metric,
canonical report, report hash, and report fingerprint matched. Source database and dataset inputs
remained byte-identical.

The binding change altered only the control artifact, fixed binding constants, their tests, and
listed state documents. Launch required a clean commit where `HEAD`, local `main`, and
`origin/main` matched. The campaign ran from exact merged main
`789d0f260a43555e5ef2d62e4e74e626b6c4e933`.

## Worker-count evaluation

Four workers remain the default. Evaluate six or more only with the same non-merit equivalence
fixtures and frozen inputs. Record wall time, speedup, per-worker peak RSS, host load, worker exits,
and SQLite contention. Keep a larger count only when it improves elapsed time without memory
pressure, severe contention, failed heartbeats, or changed output. Changing the default requires a
separate reviewed infrastructure decision.

## Commands

Plan and terminal status remain available without runtime authority:

```console
uv run trading-lab research intraday-exposed-005 plan
uv run trading-lab research intraday-exposed-005 status
```

The campaign is terminal and its runtime is immutable. Do not launch, reset, retry, or delete it.

## Boundaries

June remains ineligible and unread. No substitute controlled range exists. All 272 required runs
completed across 284 attempts, the final cohort froze empty, and no controlled evaluation occurred.
The program has no qualification, protected-holdout, PAPER, broker-write, live, V3, or
`strategic-allocation-21` authority.
