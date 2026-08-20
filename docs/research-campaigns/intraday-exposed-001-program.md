# Intraday Exposed 001 program

Status: closed with an empty final cohort and no controlled-qualified candidate.

Final report: [Intraday Exposed 001 final report](intraday-exposed-001-final-report.md)

Program ID: `intraday-exposed-001`

Plan: `config/research/intraday-exposed-001-plan-v1.json`

Starting main: `13039947fa7761c77a6b02c224c5cf16d55a34a8`

This program is separate from Intraday V1, V2, V3, Rapid-002, Rapid-003, Rapid-004, and
`strategic-allocation-21`. It does not read or write their campaign registries. It grants no
protected holdout, independent evaluation, paper, broker-write, or live authority.

## Foundation audit

The existing five-minute state-transition replay already evaluates every completed SPY/QQQ slice,
queues changed states FIFO, keeps each original signal timestamp, changes fill latency without
changing strategy evaluation cadence, and forces normal and early-close sessions flat. No
prospective execution change is needed.

The old controlled intraday contract is exact-weight V1/V2 evidence and remains immutable. The V3
campaign and its runtime state remain off limits. Daily Rapid campaign runners do not provide the
right intraday authority boundary. This program therefore needs one new plan, strategy set, isolated
runtime namespace, report contract, and controlled research adapter. It may import the generic
state-transition replay mechanics without reading or mutating V3 campaign state.

## Data freeze

The exposed archive contains four immutable Alpaca IEX SPY/QQQ five-minute datasets. Together they
cover 2025-07-01 through 2026-06-30: 38,940 bars, 19,470 bars per symbol, and 251 complete XNYS
sessions. Three sessions close early: 2025-07-03, 2025-11-28, and 2025-12-24. Full integrity checks
matched each catalog manifest, normalized fingerprint, raw fingerprint, universe, and expected XNYS
grid. The data has no missing intervals, duplicates, quarantined records, or zero-volume bars.
The frozen design uses the `XNYS-v1` research calendar; each intraday dataset manifest separately
binds the `XNYS-regular-session-bars-v1` bar-grid policy. The runner requires both exact values.

No exposed one-minute artifact was found. A new read-only Alpaca request failed with HTTP 401 before
publication. The frozen program therefore uses five-minute bars only. The universe remains SPY and
QQQ; it does not add IWM or another symbol.

## Chronology

Discovery uses 2025-07-01 through 2025-10-31. Four fixed rolling evaluations cover November and
December 2025, January and February 2026, March and April 2026, and May 2026. The last fold is the
final exposed stress block.

June 2026 is excluded from strategy inspection until the whole final cohort and its controlled plan
are frozen. It is exposed controlled research, not a protected holdout or independent evaluation.

## Search and rejection

The plan declares 325 parent configurations across 13 families. The ceiling remains 2,500. Each
configuration has at most four free parameters. Discovery can advance at most five configurations
per family; walk-forward can advance at most two. Weak families stop at the first failed stage.

Serious candidates receive paired zero-cost diagnostics, higher-cost and delayed-fill stress,
fixed-block checks, and one-parameter neighbor checks. The zero-cost run has no promotion authority.
The final screen requires positive walk-forward and stress returns, bounded drawdown and
concentration, cost retention, delay retention, activity, and a parameter plateau. Zero candidates
is an allowed result.

If more than six candidates pass, the plan uses the declared lexicographic order: worst-fold return,
Stress B return, turnover, then configuration fingerprint. It does not calculate a hidden score.

## Prospective implementation

The research-only strategy layer evaluates every completed, aligned SPY/QQQ slice and emits only
the frozen `0`, `0.5`, and `1` desired states. Opening-range, mean-reversion, VWAP-reversion, and
channel contracts reconstruct their entry/exit state from completed session bars, so declared exit
parameters affect behavior without mutable cross-run state. Relative-strength rotations insert one
flat decision between different full-weight winners; this lets the frozen FIFO executor sell before
the replacement full-weight buy. The parameter-free volatility cap in the simple
momentum-plus-volatility combination is 20 basis points of average absolute five-minute return.

The isolated runner stores exploratory and controlled lifecycle rows only under
`.trading-lab/intraday-exposed-001`. A controlled run cannot start until create-only cohort and
controlled-plan artifacts exist. The plan reserves every base, cost, delay, zero-cost, and neighbor
record before the first June replay, binds completed reports by path and SHA-256, retains failures,
and evaluates the exact reviewed policy fingerprint plus the plan's additional visible gates. One
OS file lock covers the campaign. After an interrupted claim, the runner never repeats that replay:
it reconciles an exact published controlled report or records a terminal failure and rejects the
affected configuration. Any terminal runtime failure stops the campaign at its next stage boundary,
before it can claim a complete outcome. Execution also requires a clean source where `HEAD`,
`main`, and `origin/main` match. The final JSON validates all frozen reporting fields for every
family winner and serious candidate, using explicit nulls when a later-stage measure is unavailable.

Run the reviewed, clean source from the isolated data root with:

```console
uv run python -m systematic_trading_lab.intraday_exposed_runner \
  --repository . \
  --data-home .trading-lab \
  --implementation-pr PR_NUMBER
```

## Controlled qualification

If the final cohort is empty, the program stops. Otherwise, it writes the complete cohort and
controlled plan before loading June strategy results. Each frozen candidate runs the base, two cost
stresses, two isolated delay stresses, exact zero-cost diagnostic, and declared parameter neighbors
once. `intraday-qualification-policy-v1` remains unchanged, and the plan adds positive-return,
retention, neighbor, and execution-trace gates.

Passing this controlled exposed-data screen can support a later request for independent intraday
evaluation. It cannot authorize paper trading or a broker call.
