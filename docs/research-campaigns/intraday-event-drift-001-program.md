# Intraday Event Drift 001 program

Status: prospectively frozen, independently reviewed, and implemented; launch control and execution
have not started.

Source-evidence SHA-256: `c5f1ab34c92b10ac9c75d86a3c33c9f2a445eed022a48697edaa7dfd9eabee0a`.
Source-evidence fingerprint: `6616ed631b3d7e8e727b8cde85bf26e4c2cb5800812db745c327a71bf62192fd`.
Calendar SHA-256: `fa413a30234c6b82394fcdbf99df94aa31ae38e2df12d58296bcbc03162a34ee`.
Calendar fingerprint: `9992ee0a430abc0b59f49f6dd9e5178ff22d13a9dec5ad5de1d8578896ed2a78`.
Plan SHA-256: `c0dade2573405ddcd38d88814c10a27c3caae11bfb925a21179f6741cc20233c`.
Plan fingerprint: `73933d470feb52c1135746ab57db742019077b8b39e8e2545e9aba37c9a8d838`.
Review SHA-256: `25e92a85cee47aa261b4a85dce57666effbfbe329c203d3ac78df7b5bba9df96`.
Review fingerprint: `0a464aca264ad4a8583d12fc4912898461ecf9e6121a1119322229e12bfb4077`.

## Why this program exists

Intraday Exposed 005 completed with an empty final cohort. Generic every-session signals were often
weak, concentrated, or unstable across chronological folds and parameter neighbors. Its only
serious candidate traded less often and held for several hours, but failed the frozen neighbor
gate. That candidate remains closed and is not reused.

Event Drift 001 tests a new economic hypothesis: a large positive move shared by SPY and QQQ after
a scheduled pre-open macro release may continue for several hours because broad risk repricing can
be gradual. The schedule is external to market returns. The strategy does not read release values,
surprises, consensus estimates, revisions, or headlines. This design does not assert that the
hypothesis is profitable.

## Event source and eligibility

The source artifact binds 30 BLS CPI, PPI, and Employment Situation rows from July 2025 through May
2026. It uses archived official annual-schedule rows captured before the same-date 09:30 ET XNYS
open and hashes each exact source excerpt.

Twenty-eight events are eligible. Two remain visible but excluded:

- `bls-empsit-2026-02-11` has a dated official occurrence page but no independently time-bound
  pre-open capture, so its disposition is `excluded-source-causality-unproven`.
- `bls-empsit-2026-04-03` fell on an XNYS-closed date and is not moved to another session.

Independent review recomputed all local hashes, matched the 30 evidence and calendar IDs, checked
the 28 eligible capture timestamps against XNYS opens, and found no duplicate eligible session. It
did not independently re-fetch BLS or Internet Archive pages; the review artifact records that
proof limit.

## Frozen strategy

The strategy uses existing read-only SPY and QQQ five-minute datasets through
`2026-05-29T19:55:00Z` and the unchanged calibrated execution-cost model.

On an eligible event session it:

1. Reads each symbol's prior XNYS-session close and the current 09:30 ET open.
2. Waits for 3, 6, or 12 fully completed bars.
3. Requires each opening gap to be at least 10 basis points.
4. Requires each opening-to-reaction move to be at least 10, 20, or 40 basis points.
5. Atomically targets SPY and QQQ at 0.5 weight each only when both symbols pass.
6. Targets both symbols flat after completed zero-based bar index 60.

Normal delay fills at the next eligible bar open. The plan also fixes higher-cost and two- and
three-bar delay stress. An early close uses the engine's final eligible bar-open flatten. Joint
entries and exits must share decision and fill timestamps. Normal and zero-cost decision traces
must match for parent and neighbor runs.

The Cartesian grid contains nine explicit candidates. Immediate neighbors differ by one adjacent
value on one axis, producing 12 symmetric undirected edges.

## Chronology and stages

| Period | Role | Eligible events |
| --- | --- | ---: |
| July–October 2025 | discovery | 10 |
| November–December 2025 | walk-forward | 4 |
| January–February 2026 | walk-forward | 6 |
| March–April 2026 | walk-forward | 5 |
| May 2026 | final exposed fold | 3 |

Every parent completes paired Normal and zero-cost discovery before screening. At most four advance
to walk-forward. At most two complete the fixed stress, delay, and immediate-neighbor stages. Stage
barriers block screening until all required same-stage runs finish.

The machine-readable plan fixes activity, return, drawdown, friction, gross-edge, concentration,
accounting, chronological stability, stress-retention, delay-retention, and exact parameter-neighbor
gates. Event sessions, not individual symbol trades, are the observation unit. Reports must
reconcile event P&L and daily regulatory fees to portfolio accounting. Undefined gate metrics fail.

Every candidate that passes every gate freezes simultaneously, sorted by candidate ID, up to the
predeclared maximum of two. No result ranking may discard an all-gate survivor.

## Execution and recovery boundary

The runner reuses the existing bounded `spawn` executor with four workers. One worker
owns one claimed run. The plan keeps 300-second leases, 60-second heartbeats, three maximum
infrastructure attempts, create-only publication, stage barriers, and short SQLite transactions.
Only an expired no-result infrastructure lease may retry. Candidate, data, calendar, publication,
and exhausted-attempt failures are terminal.

The implementation adds strict loaders, the event strategy, report attribution, runner, CLI,
recovery tests, and one-worker versus four-worker deterministic equivalence. Its launch-control
hashes remain intentionally unbound. It has created no reservation, runtime database, market-data
read, report, or strategy result. Launch requires a second review bound to the exact merged
implementation main before the first reservation.

## Boundaries

June remains ineligible, and no substitute controlled range exists. A nonempty exposed cohort must
freeze and wait for future untouched data. An empty cohort closes as negative exposed evidence and
can lead only to another separately frozen hypothesis.

Intraday V3, daily 2018–2019, PAPER and broker state, `strategic-allocation-21`, and live execution
remain untouched. The plan, calendar, evidence, and review grant no strategy-execution,
qualification, controlled-evaluation, protected-holdout, PAPER, broker-write, or live authority.
