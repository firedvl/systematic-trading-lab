# Intraday Event Repricing 001 program

Status: dataset-validation repair implemented; launch-control re-review required; no reservation or result exists.

Plan SHA-256: `f24cae1372f346be02c0079b931c77d5efb5105a06cf26631b783010851bd8b8`.
Plan fingerprint: `2f98e0cc4565435c9974f65791fd830f7fb9509730f31872f97d77484c00c489`.
Review SHA-256: `0c17f683d21e0e365a730f6e267029d5be64eb62691e1a3bbacf6ead678048ca`.
Review fingerprint: `2351e230df1f6618247bbd91bed19ac6444baf09b8573ced2af9c6f937513ab5`.
Launch-control SHA-256: `11572b8f61d797b2a664866eb88d8b39be2ae07cbb57f9891899725b0a7293c2`.
Launch-control fingerprint: `3d35f8d088e11ad6f07d81015c1b037b457e00b824ea908f37cef64a8fbf4a6b`.

## Purpose

Intraday Event Drift 001 closed empty because its joint positive opening-gap and reaction rule
activated at most two of ten discovery events. Calibrated friction did not cause that failure. This
successor tests a different question: after a scheduled pre-open BLS release, does the signed
completed-bar QQQ-minus-SPY reaction identify a long-only leader that both earns a positive net
return and continues to outperform a matched long laggard control?

The design does not rescue or retune Event Drift. It removes the joint-positive and opening-gap
mechanics, uses one symbol instead of two, measures signed cross-sectional divergence, fixes one
two-hour hold, and requires a separate matched control. Earlier every-session relative-strength
research did not test this external-event, one-entry, no-rotation contract.

## Long-only paired design

A true dollar-neutral pair would require short inventory, margin, borrow, short-side fees, risk,
order, reconciliation, and PAPER controls that do not exist. This plan preserves the audited
long-only boundary.

After `N` completed regular-session five-minute bars:

```text
relative reaction bps = 10,000 × (
  QQQ close[N-1] / QQQ open[0]
  - SPY close[N-1] / SPY open[0]
)
```

The event activates when the absolute reaction reaches the frozen floor. A positive sign selects
QQQ as leader; a negative sign selects SPY. The leader arm targets only that symbol at `0.5`. A
separate laggard-control run targets the opposite symbol at `0.5`. Both remain flat otherwise and
permit no resize, reentry, or target change.

The entry fills at index `N-1+d` under scenario delay `d`. The exit decision follows completed bar
index `N+23` and fills at `N+23+d`, exactly 24 five-minute intervals later. The latest `N=12`,
`d=3` exit fills at index 38, before the 13:00 ET early-close final bar-open index 41.

The primary relative observation uses matching market timestamps:

```text
10,000 × (
  leader exit market price / leader entry market price
  - laggard exit market price / laggard entry market price
)
```

Leader net return remains the implementable long-only result. Leader net return minus laggard-control
net return is labeled only as a long-arm comparison. It is not dollar-neutral pair P&L.

## Frozen search

The nine parents cross:

- reaction bars: `3`, `6`, `12`;
- minimum absolute relative reaction: `5`, `10`, `20` basis points.

Immediate neighbors change one adjacent axis value. The graph has 12 undirected edges. The lowest
threshold exceeds the calibrated severe combined two-arm displayed-spread round-trip cost by several
times. No relative-strategy result informed the thresholds or the fixed 24-bar hold.

The campaign inherits the exact Event Drift chronology, four pre-June dataset bindings, event
calendar and source evidence, calibrated cost model, engine, cost/delay scenarios, protected
boundaries, and no-controlled-range disposition through the exact base-plan hash. The exposed event
counts remain `10`, `4`, `6`, `5`, and `3`; the maximum market timestamp remains
`2026-05-29T19:55:00Z`.

## Stages and maximum budget

Each run specification binds one candidate, period, arm, and scenario:

| Stage | Maximum specifications |
| --- | ---: |
| Discovery: 9 candidates × 2 arms × Normal/zero-cost | 36 |
| Walk-forward: cap 4 × 4 folds × 2 arms × Normal/zero-cost | 64 |
| Stress/delay: cap 2 × 4 folds × 2 arms × 4 scenarios | 64 |
| Deduplicated immediate neighbors: at most 5 additional × 4 folds × 2 arms × 2 scenarios | 80 |
| Total | 244 |

The inherited three-attempt infrastructure ceiling permits at most 732 attempts. Retries do not
create new research specifications. The runner must reuse an existing exact
candidate-period-arm-scenario report and reject any reservation that exceeds the frozen ceiling.

All nine parents finish before discovery screening. At most four enter walk-forward; at most two
enter stress, delay, and neighbor checks. Screens require positive leader results, positive matched
relative continuation, visible activity, cost and drawdown limits, chronology, event and release
concentration, direction balance, paired selection traces, accounting identities, stress/delay
retention, and exact neighbor stability. Undefined required metrics fail. Every all-gate survivor
freezes simultaneously; zero survivors remains valid.

## Execution and recovery controls

The implementation reuses the existing long-only Exposed 002 engine, restart-safe attempt
store, four-worker spawned executor, one-claim workers, stage barriers, leases, heartbeats,
create-only reports, and terminal deterministic failure classes. Each arm has its own immutable run
and report. A cost-independent selection trace binds event, parameters, signed reaction, active
flag, direction, and decision times across both arms and every scenario. A mismatch is terminal.
Runner and worker initialization and every worker task claim reject populated `APCA_*` and
`TRADING_LAB_PAPER_*` environment variables before source, data, runtime, or worker access, so
spawned research workers cannot inherit broker credentials or PAPER write opt-in.

Only an expired no-result infrastructure lease may retry. Any candidate, data, calendar,
selection-trace, accounting, publication, or exhausted-attempt failure remains terminal. Existing
Event Drift and Exposed runtimes do not change.

## Launch and authority boundary

This plan grants no strategy execution. The implementation adds the strict inherited-plan loader,
strategy arms, selection trace, paired report, budget enforcement, runner, CLI, and focused tests.
It routes the console entry point through a small campaign wrapper so the immutable Event Drift
`public_cli.py` launch hash remains unchanged; every other command delegates to the existing CLI.
Reviewed implementation main `94bc182efe952839d7e3384ea8a148554dd0149d` passed all seven quality
gates, four-fixture one-worker/four-worker equivalence, and a finding-free independent launch review.
The launch-control artifact and constants bind that exact evidence. Runtime lineage permits only the
reviewed launch artifact, constants, tests, and status documents to change before clean exact-main
execution.

June, Intraday V3, daily 2018–2019, PAPER/broker state, `strategic-allocation-21`, and live execution
remain untouched. The reused pre-May bars are exposed research data, not controlled evidence. A
nonempty cohort must freeze and wait for future untouched data; it cannot use June or a substitute
range.

Historical and simulated results do not establish future profitability.
