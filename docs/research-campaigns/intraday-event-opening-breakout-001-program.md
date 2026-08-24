# Intraday Event Opening Breakout 001 program

Status: implemented without results; exact-main launch-control review remains unbound.

Plan SHA-256: `73ea48a3e2c250db93aca0c7ebef16b5480e118ab9577684089147bb318dfd27`.
Plan fingerprint: `3164757c9f91a1318d48607b24bdaa1c4f3e5439a9657d1b31b0cc32d8163b68`.
Review SHA-256: `c3c581503fca8f78af0bafb30402ac78a2b6dce06f46b16c39a5e72efd26c550`.
Review fingerprint: `92f20b1648dba189130c0980e427e1364d0f7fecb8f52166ddc933ac165db540`.
Starting main: `b268b5d8e8eb1abb7334458b2abf554b7f0809f2`.

## Purpose

Intraday Event Repricing 001 closed its signed QQQ-minus-SPY continuation claim with no survivor.
This successor tests a different prospective claim: after a scheduled pre-open BLS release, does a
close-confirmed SPY breakout above the completed first 30-minute range continue through noon?

The plan does not invert, retune, or reuse a Repricing candidate. Repricing results supplied no
numeric input. The new signal uses only SPY's own opening range and close. It has no relative rank,
leader, laggard, opening-gap floor, release contents, shorting, leverage, resize, or reentry.

## Frozen strategy

The strategy acts only on the 28 causally eligible Event Drift sessions. It remains flat on all
context-only, excluded, and ordinary sessions.

After SPY bars `0` through `5` complete, the strategy freezes their maximum high. It then checks
completed SPY closes at bars `6` through `11`. The first close at or above the opening-range high
plus the candidate's buffer activates one entry. The target becomes SPY `0.5`, QQQ `0`. The exit
decision follows completed bar `29`; the inherited one-, two-, or three-bar delay fills at indices
`30`, `31`, or `32`. The latest exit precedes the final regular-session bar on every inherited
early-close day.

QQQ remains a zero-weight passive input because the inherited engine and dataset require the
complete SPY/QQQ universe. It may appear in report-only benchmarks. QQQ price changes cannot affect
the opening range, activation, target, or exit.

The three candidates fix breakout buffers of `2`, `4`, and `8` basis points. They form a line with
two symmetric immediate-neighbor edges. The values form a prospective doubling sequence. The
2-basis-point floor exceeds four times the calibrated severe SPY two-fill displayed-spread cost of
0.44 basis points.

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
than eight specifications: with only three candidates and a walk-forward cap of two, at least one
neighbor of any serious candidate already has four-fold Normal and zero-cost evidence.

Discovery requires positive Normal and zero-cost return, minimum activity, bounded drawdown and
cost, gross trade edge, diversified positive event and release-class profit, an exact signal trace,
and an exact accounting identity. Walk-forward requires three positive Normal folds, positive May,
activity, risk, cost, concentration, and trace gates. The one serious candidate must then pass both
stress levels, both delay scenarios, and every immediate neighbor under Normal and zero cost.
Undefined required metrics fail. The final cohort contains zero or one candidate; no result ranking
or parameter substitution is allowed.

## Implementation and launch boundary

The implementation reuses only the existing engine, attempt store, executor, cost model, and
explicit Event Drift base payload. Campaign-owned plan loading, strategy, event reporting, runner,
CLI, launch control, and focused tests now exist. Candidate, period, and scenario alone define one
run identity, so later stages reuse exact evidence. Launch-control constants remain unbound. A
separate exact-main review must pass all repository gates and synthetic one-worker/four-worker byte
equivalence before a binding PR can make the first reservation.

The four-worker spawned executor remains the default. Only an expired no-result infrastructure
lease may retry. Candidate, data, calendar, signal-trace, accounting, publication, and exhausted
attempt failures stay terminal.

This plan grants no strategy execution, qualification, controlled evaluation, holdout, PAPER,
broker-write, live, or promotion authority. June, Intraday V3, daily 2018–2019, PAPER/broker state,
`strategic-allocation-21`, and live execution remain untouched. A survivor must freeze and wait for
future untouched data; no June or substitute range may open.

Historical and simulated results do not establish future profitability.
