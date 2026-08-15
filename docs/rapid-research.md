# Rapid Research

Rapid Research is the non-authoritative daily strategy loop. Use it to explore historical ideas, reject weak variants, test fixed parameters across time, and package a result for later review.

It does not write controlled experiment, qualification, holdout, risk, order, paper, execution, reconciliation, or V3 state. It grants no authority.

## Commands

```console
trading-lab research list-strategies
trading-lab research backtest --dataset DATASET_ID --strategy STRATEGY
trading-lab research sweep --dataset DATASET_ID --strategy STRATEGY --parameter NAME=1,2,3
trading-lab research walk-forward --dataset DATASET_ID --strategy STRATEGY
trading-lab research stress RUN_ID
trading-lab research list
trading-lab research show RUN_ID
trading-lab research compare RUN_A RUN_B
trading-lab research export-candidate RUN_ID
```

Run these through `uv run` in a checkout.

## Backtest

```console
uv run trading-lab research backtest \
  --dataset DATASET_ID \
  --strategy moving-average \
  --parameter window=50 \
  --initial-cash 100000 \
  --slippage-bps 5 \
  --commission-bps 1 \
  --fill-delay-bars 1
```

Dates are optional and inclusive:

```console
  --start 2020-07-27 --end 2024-12-31
```

Signals observe a completed daily bar. Orders can first fill at a later bar open after the configured whole-bar delay. Results are net of slippage and commission.

Rapid-004 runs must add `--campaign rapid-004-expanded-universe`. This binds the campaign identity
into the run specification, verifies the complete frozen dataset, and rejects any dataset, universe,
symbol set, range, provider, or adjustment policy that differs from its committed freeze before
strategy execution. A run without this option is ordinary Rapid evidence and cannot count toward
Rapid-004.

## Parameter sweep

```console
uv run trading-lab research sweep \
  --dataset DATASET_ID \
  --strategy moving-average \
  --parameter window=10,20,50,100,200 \
  --max-runs 100
```

Multiple `--parameter` flags form a deterministic Cartesian product. The command prints the configuration count before execution and rejects a grid above the cap. The default cap is 100. Every valid configuration creates a run record; simulation failures stay in the ledger. Sweep output is exploratory and in-sample.

## Walk-forward

```console
uv run trading-lab research walk-forward \
  --dataset DATASET_ID \
  --strategy moving-average \
  --parameter window=50 \
  --training-window 252 \
  --test-window 63 \
  --step-size 63
```

Defaults are 252 training sessions, 63 test sessions, a 63-session step, and rolling training. Add `--expanding` to keep the first training session fixed. Step size must be at least the test window, so test folds cannot overlap.

Each fold:

- ends training before testing starts;
- makes no trade during training;
- passes training bars only as strategy warmup history;
- uses fixed caller-supplied parameters rather than fitting on the test window;
- stores its own dates, metrics, status, error, and parent link.

The parent reports fold returns, drawdowns, trade and cost totals, profitable-fold rate, compounded out-of-sample return, and fold-return dispersion. It reports no composite strategy score.

## Stress

```console
uv run trading-lab research stress RUN_ID \
  --slippage-bps 10 \
  --commission-bps 2 \
  --fill-delay-bars 2
```

Each stress assumption must be no better than the source run, and at least one must be worse. Stress creates a linked run. It rejects walk-forward parents and folds because a fold needs its recorded training warmup; stress a standalone backtest, sweep result, or prior stress run. `survives_worse_execution` means only that its stressed net return stayed above zero; it is not a qualification result.

Skipped-fill simulation is not implemented. Add it only with a reviewed deterministic fill policy.

## Metrics

Completed runs report, where defined:

- total and annualized return;
- maximum drawdown;
- annualized volatility, Sharpe ratio, and Sortino ratio;
- turnover and explicit slippage and commission paid;
- trade count;
- session win rate and session profit factor;
- average and maximum gross exposure;
- active and total sessions;
- best and worst session return;
- top-five session and top-instrument profit concentration.

Short samples can produce extreme annualized values. Treat the fixture as a command check, not evidence.

## Compare and inspect

```console
uv run trading-lab research list
uv run trading-lab research show RUN_ID
uv run trading-lab research compare RUN_A RUN_B RUN_C
```

Comparison keeps the requested runs, failures, missing metrics, parameters, costs, and dates visible. It does not rank with a hidden score.

## Storage

Rapid state is separate under `TRADING_LAB_HOME`:

```text
rapid-research.sqlite3
rapid-research/
├── datasets/
├── reports/
└── candidates/
```

The SQLite store indexes datasets and runs. Reports and candidate files are canonical, fingerprinted, and create-only. A run records dataset identity, strategy and parameters, range, timeframe, cash, costs, delay, Git commit when available, working-tree state, timestamps, metrics, error, and report path.

It never uses `experiments.sqlite3` or `execution.sqlite3`.

## Local data

`data import-local` accepts complete daily CSV or Parquet OHLCV files. It validates exact columns, UTC midnight timestamps, XNYS session coverage, ordering, duplicates, symbols, finite positive prices, OHLC relationships, and nonnegative integer volume.

Local imports are `user-supplied` with unknown adjustment policy. They stay Rapid-only. See [Data policy](data-policy.md).

The importer rejects identifiable controlled catalog artifacts even when they live under another `TRADING_LAB_HOME`. It also rejects local rows that overlap a protected range in the active controlled registry. Do not copy, detach, or re-encode protected bars for Rapid use; an arbitrary user-supplied file has no intrinsic provenance that this process can verify.

## Protected V3 windows

Rapid runs reject any inclusive overlap with:

- Validation A: 2026-10-01 through 2026-12-03;
- Validation B: 2026-12-04 through 2027-02-09;
- Validation C: 2027-02-10 through 2027-04-15.

There is no CLI or API override. V3's exact main seal was attested before Validation A, and the sealed campaign has been materialized with 60 pending reservations. No selected V3 dataset or result has been observed. V3 now waits for its future validation periods and does not block normal historical research. Do not acquire or inspect its selected periods through ordinary research.

Catalog and local reads reject ranges reserved by an unused controlled-holdout authorization and ranges stored as controlled holdout experiments. Rapid checks the read-only controlled registry before protected bars. Local Rapid imports remain outside controlled evidence.

## Candidate export and promotion

```console
uv run trading-lab research export-candidate RUN_ID
```

The create-only export binds the selected run and its complete sweep or walk-forward ledger. Its authority map sets controlled research evidence, qualification, protected holdout, paper execution, broker writes, live execution, and automatic promotion to `false`.

Promotion is a later human-reviewed action: create a separate controlled plan with new untouched evidence, run qualification, then use the existing guarded paper path if every independent gate passes. Rapid Research never performs that action.
