# Intraday Exposed 004 program

Status: implementation, merged-main equivalence, health-only Intraday Exposed 003 disposition, and independent launch-control review complete; launch remains blocked on the launch-control PR, CI, merge, and final clean-main check.

Plan SHA-256: `760df9db4b9be9b2d8eecaa0287713e3e341c7437523b01d0fef47b830f43c8e`.
Plan fingerprint: `a122cbba4fa76ed1d65236637f52308398306d72a62b0ba4d1836792203b2ddc`.
Prospective-review SHA-256: `f4d5d01a52d290374d54ab5944aee80047377e224e9ab3453e1237559b56833a`.
Prospective-review fingerprint: `f92b48f4d0c5e30f230af786ef3f5dbb05ad2e2bb10022332e585cd4dfbb98db`.
Launch-control SHA-256: `a5a7107d803efb468c1946b1c66244e163c29f27b7f4e1bc7ba93e045c21c5fc`.
Launch-control fingerprint: `fc0eb76457eb4fc7b752323b69cba602eb0cceb9f84f585c05f68e9fff511a0b`.

## Scope

Intraday Exposed 004 changes scheduling only. It cleanly recomputes the exact frozen Intraday
Exposed 003 and Intraday Exposed 002 design under new evidence identities. It imports no prior
runtime row and does not use partial Exposed 003 strategy results to change a family, parameter,
chronology, cost, strategy mechanic, gate, cap, neighbor, stage, or selection rule.

The strict plan loader verifies:

- all 60 parents across ten families;
- 120 paired Normal and exact zero-cost discovery runs;
- all five periods and chronology through 2026-05-29;
- the frozen calibrated cost model, engine, strategy, data bindings, and evaluation wrapper;
- discovery, walk-forward, stress, isolated-delay, neighbor, concentration, cost-efficiency, and
  final-cohort rules;
- 140 exact neighbor links;
- no Intraday Exposed 002 or 003 runtime import; and
- false qualification, controlled-evaluation, holdout, paper, broker-write, and live authority.

## Coordinator and workers

One coordinator holds the campaign lock, reserves immutable specifications, expires stale leases,
reconciles canonical reports, advances stages, applies frozen screening, creates the final freeze,
and publishes the final report. It never overlaps dependency stages.

Within each stage, `run_process_stage` starts a bounded local pool with the multiprocessing `spawn`
method. Four workers are the default. `--workers N` selects another positive count without changing
any run specification or fingerprint. Each worker:

- initializes one private read-only dataset service per catalog and one period cache for the stage;
- accepts one task at a time and owns at most one active claim;
- opens its own short-lived SQLite connections;
- heartbeats its own 300-second lease every 60 seconds;
- runs replay outside database transactions; and
- publishes once through `research-attempts-v1`.

The process executor returns results in input order. The coordinator then reloads every canonical
report in frozen specification order. Completion timing cannot influence screening or selection.

## Failure and restart rules

An abrupt worker exit affects only its claimed run. The executor drains work assigned to unaffected
workers and does not reassign the interrupted run. Only expiration of its no-result lease can return
that exact specification to pending. The same specification may receive at most three append-only
infrastructure attempts.

A worker process also exits after any reported task exception. This prevents one PID from retaining
an uncertain lease and claiming another run; the coordinator starts a replacement only for work that
was still pending and never resubmits the errored task.

Completed canonical reports cannot be reclaimed. Candidate exceptions and data-integrity failures
are terminal after one attempt. A different file at a canonical path creates terminal publication-
conflict evidence. Publication journals canonical bytes before create-only materialization, so a
restart restores the same bytes instead of recomputing the run.

SQLite retains rollback journaling, `BEGIN IMMEDIATE` claim/publication guards, immutable triggers,
and a 30-second busy timeout. WAL is not enabled because the final evidence contract hashes one
database file; an uncheckpointed WAL would make that hash incomplete. Output sealing occurs before
the short terminal publication or failure transaction.

## Stage barriers

The inherited frozen stage methods enforce this order:

1. Reserve and run all discovery rows in parallel.
2. Wait for the complete discovery stage and apply the frozen discovery screen.
3. Reserve and run selected walk-forward rows in parallel.
4. Wait for the complete walk-forward stage and apply the frozen screen.
5. Reserve and run selected stress, delay, and neighbor rows in parallel.
6. Wait for the complete serious stage, then apply deterministic cohort processing.

No worker advances a stage or screens a result.

## Identities

- Program: `intraday-exposed-004`.
- Candidates: `ie004-f..`.
- Reservations: `ie004q-..`.
- Runs: `ie004r-..`.
- Attempts: `ie004a-..`.
- Runtime root: `.trading-lab/intraday-exposed-004`.
- Database: `intraday-exposed-004.sqlite3`.
- Runner: `intraday-exposed-004-runner-v1`.
- Run report: `intraday-exposed-004-backtest-report-v1`.
- Final freeze: `intraday-exposed-004-final-freeze-v1`.
- Final report: `intraday-exposed-004-final-report-v1`.

The unchanged strategy still receives the exact `ie002-` source candidate. The 004 specification
also records the corresponding `ie003-` identity for provenance without importing a 003 result.

## Launch gates

The run command remains fail closed until the reviewed launch-control artifact exists and binds the
merged implementation source, executor, attempt store, 004 runner, full quality evidence, read-only
equivalence evidence, and health-only Exposed 003 disposition.

The loader rejects a control artifact unless its raw SHA-256 and canonical fingerprint match fixed
reviewed constants. It also validates the reviewed plan, current executor/attempt-store/runner file
hashes, all seven repository gates, detailed one/four-worker fixture evidence, the three allowed 003
disposition branches, and a finding-free independent review. The binding constants were fixed only
after merged-main evidence and independent review passed, so an unreviewed `status: passed` file
cannot launch 004. The final clean-main commit must descend from the reviewed implementation
commit, and its diff may contain only the control artifact, fixed binding constants, their test, and
disposition documents.

Before any 004 launch, the read-only Exposed 003 equivalence action must select completed canonical
specifications by configuration and scenario only, run them with one and four workers, and prove
exact equality for specification, run fingerprint, fill trace, round trips, metrics, canonical
report bytes, SHA-256, and report fingerprint. It must also prove that the source database and
dataset bytes did not change by comparing their SHA-256 values before and after replay. Any mismatch
stops the workflow.

Merged implementation main `88f2e2d8696c737e90063e8a9a3578c0f46dd6a1` passed all seven
repository gates. Because Exposed 003 was still publishing progress, the live-file proof stopped
when its before/after database hash changed. A consistent read-only SQLite snapshot then completed
the exact proof without changing the live runtime: four fixtures matched for every required field,
the snapshot database SHA-256 was
`ee3ee9662c37f73d46be5808fc53240d29db72eb34a25467446dcc8ff462adde`,
sequential time was `4105.462651` seconds, four-worker time was `1253.082018` seconds, and speedup
was `3.276`.

The final health-only Exposed 003 disposition recorded 55 completed, 0 failed, 64 pending, and 1
running leased row across 57 attempts. The materially incomplete coordinator received `SIGTERM` at
`2026-08-22T20:47:32Z` and exited without escalation. Its 283 files and database remain preserved;
no partial strategy merit was inspected. Independent launch-control review
`codex-independent-launch-control-review-2026-08-22` passed with no findings.

```console
uv run trading-lab research intraday-exposed-003 equivalence --workers 4 --fixtures 4
```

Then inspect only Exposed 003 health and progress metadata:

- Preserve a valid completed terminal outcome and do not launch 004.
- Preserve an incomplete or invalid terminal outcome, record infrastructure supersession, and
  launch 004 only from clean exact merged main.
- If active and materially incomplete, stop it cleanly, preserve all evidence, record infrastructure
  supersession, then launch 004 from clean exact merged main.

The eventual launch and status commands are:

```console
uv run trading-lab research intraday-exposed-004 run --workers 4
uv run trading-lab research intraday-exposed-004 status
```

## Worker-count evaluation

Benchmark the same frozen fixtures with one, four, and only then six workers. Record wall time,
speedup, per-attempt duration, worker RSS and peak RSS, available memory, system load, heartbeat
continuity, and SQLite busy or lock failures. Keep four as the default unless six improves throughput
without swap or memory pressure, missed heartbeats, or material database contention.

June remains ineligible because committed Intraday V2 results already expose it. No June read,
substitute range, controlled plan, PAPER, broker, live, V3, or `strategic-allocation-21` access is
allowed.
