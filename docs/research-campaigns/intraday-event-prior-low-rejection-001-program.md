# Intraday Event Prior-Low Rejection 001 program

Status: terminal exposed research; the exact four-worker launch completed once from source main `b470aaf7c4dd28d43102ff30fa898e8561344e4d` and froze an empty cohort.

Launch-control artifact SHA-256: `ac9cc921e6b60592bfd8dcc9181ff44126d63a929867566bb9aecd1c2a043d0a`.
Launch-control artifact fingerprint: `17d1ad7207bbc76264a2762f288e71f6445a7088e4d238aac004ada94b5214d1`.

Plan SHA-256: `2fe0339f498854a76a5fc4f52110290ca379117bad7387c2b0d87854ccadff41`.
Plan fingerprint: `ab4508dd2e70231b5d169bcf2a1bcbdc691abf1615764bacc463ebdab67bfbc6`.
Review SHA-256: `7c95767fae24004831c12941355fd80342f44a0bd47aed592e23c7419ff91928`.
Review fingerprint: `efa539340aa87ab1940ba40414d565027f034689d7cdc6b89853883815aa3c41`.
Starting main: `f0f75e91dec4144f2de1558486859ed44341d27c`.

## Terminal disposition

All six discovery specifications completed once with zero failures, retries, pending rows, or
active leases. All three confirmation candidates failed the frozen discovery gates; none reached
walk-forward, stress, delay, or neighbor stages. The final outcome is
`no-controlled-qualified-candidate`, with no controlled evaluation or qualification.

Runtime database SHA-256: `d4bb82b42fb2d643cde048dee11f3344913ce497a92b52e18d3bb90f036290ec`.
Final-report JSON SHA-256: `b860b8fde33d57be8fb04c3b9f5fd8a2ff563c8bbade2944fb6fda58f13a7aa1`.
Final-freeze JSON SHA-256: `083d479d392d8dec62a0f1d20f9abb265aa756af788c1304ab7ec070612c3ba5`.

The campaign is terminal and must not be relaunched, retuned, inverted, or rescued by weaker
gates. June, V3, daily 2018–2019, PAPER, broker, live, and `strategic-allocation-21` state remain
out of scope. A future hypothesis requires a new prospective plan and untouched evidence.

## Purpose

Intraday Event Opening Breakout 001 closed its completed first-30-minute range-high continuation
claim with no survivor. This successor asks a different prospective question: after a scheduled
pre-open BLS release, does an early SPY undercut of the preceding regular-session low followed by a
sustained reclaim continue upward through noon?

The plan does not invert, retune, or reuse an Opening Breakout candidate. Its outcome supplied no
numeric or structural input. The signal uses a prior-session support level and downside rejection,
not an opening-range high, positive opening gap, joint SPY/QQQ reaction, or relative leader rank.

## Frozen strategy

The strategy acts only on the 28 causally eligible Event Drift sessions. It remains flat on all
context-only, excluded, and ordinary sessions. Missing, incomplete, or SPY/QQQ-misaligned prior
session data is terminal.

For each eligible event, the strategy derives `prior_session_low` from every validated five-minute
SPY bar in the immediately preceding complete XNYS session. SPY must trade strictly below that
level during completed bars `0` through `5`. It then checks completed SPY closes at bars `6` through
`11`. The final bar of the first run of `1`, `2`, or `3` consecutive closes strictly above the
prior-session low activates one entry. The whole confirming run must lie inside the monitoring
window; equality does not qualify.

The target becomes SPY `0.5`, QQQ `0`. The exit decision follows completed bar `29`; the inherited
one-, two-, or three-bar delay fills at indices `30`, `31`, or `32`. The latest exit precedes the
final regular-session bar on every inherited early-close day. No resize or reentry is allowed.

QQQ remains a zero-weight passive input because the inherited engine and dataset require the
complete SPY/QQQ universe. It may appear in report-only benchmarks. QQQ price changes cannot affect
the reference low, breach, reclaim, target, or exit.

The three confirmation candidates form a line with two symmetric immediate-neighbor edges. The
`1`, `2`, and `3` values reuse an already-frozen generic confirmation convention, not predecessor
outcomes. The fixed noon horizon avoids a holding-period search axis.

## Inherited exposed evidence

The plan binds Event Drift plan SHA-256
`c0dade2573405ddcd38d88814c10a27c3caae11bfb925a21179f6741cc20233c` and fingerprint
`73933d470feb52c1135746ab57db742019077b8b39e8e2545e9aba37c9a8d838`. It inherits the exact
chronology, four read-only pre-June datasets, event calendar and source evidence, execution model,
cost model, controlled-range disposition, and protected boundaries. Event Drift strategy mechanics,
candidates, results, runtime, and reports do not carry forward.

The exposed event counts remain `10`, `4`, `6`, `5`, and `3`. The maximum market timestamp remains
`2026-05-29T19:55:00Z`. These bars are exposed research evidence, not controlled evidence.

## Screens and budget

Each immutable run specification binds one candidate, period, and scenario:

| Stage | Maximum specifications |
| --- | ---: |
| Discovery: 3 candidates × Normal/zero-cost | 6 |
| Walk-forward: cap 2 × 4 folds × Normal/zero-cost | 16 |
| Stress/delay: cap 1 × 4 folds × 4 scenarios | 16 |
| One additional immediate neighbor × 4 folds × Normal/zero-cost | 8 |
| Total | 46 |

The three-attempt infrastructure ceiling permits at most 138 attempts. The runner must deduplicate
candidate-period-scenario identities and reuse exact evidence. A second neighbor never adds more
than eight specifications: with three candidates and a walk-forward cap of two, at least one
neighbor of any serious candidate already has four-fold Normal and zero-cost evidence.

The plan preserves the prior campaign's gates without weakening them. Discovery requires positive
Normal and zero-cost return, minimum activity, bounded drawdown and cost, gross trade edge,
diversified positive event and release-class profit, an exact signal trace, and an exact accounting
identity. Walk-forward requires three positive Normal folds, positive May, activity, risk, cost,
concentration, and trace gates. The one serious candidate must then pass both stress levels, both
delay scenarios, and every immediate neighbor under Normal and zero cost. Undefined required
metrics fail. The final cohort contains zero or one candidate; result ranking and parameter
substitution are prohibited.

## Implementation and launch boundary

The implementation reuses only the existing engine, attempt store, executor, cost model, and explicit
Event Drift base payload. It adds campaign-owned plan loading, strategy, reporting, runner, CLI,
launch-control surface, and focused tests. Coordinator and worker dataset validation receive the
inherited Event Drift payload explicitly; the successor plan remains free of a duplicated `data`
section. Exact-main review passed all repository gates, synthetic one-worker/four-worker byte
equivalence, credential-boundary, authority, and source-lineage checks; the launch-control artifact
binds the reviewed source before the first reservation.

The four-worker spawned executor remains the default. Only an expired no-result infrastructure
lease may retry. Candidate, data, calendar, signal-trace, accounting, publication, and exhausted
attempt failures stay terminal.

This plan grants no strategy execution, qualification, controlled evaluation, holdout, PAPER,
broker-write, live, or promotion authority. June, Intraday V3, daily 2018–2019, PAPER/broker state,
`strategic-allocation-21`, and live execution remain untouched. A survivor must freeze and wait for
future untouched data; no June or substitute range may open.

Historical and simulated results do not establish future profitability.
