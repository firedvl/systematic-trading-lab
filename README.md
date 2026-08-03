# Systematic Trading Lab

Research infrastructure for reproducible U.S. ETF data, backtests, qualification, and paper execution. The current scope is daily bars for SPY, QQQ, IWM, TLT, and GLD. Live trading is disabled.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```console
uv sync --dev
uv run trading-lab doctor
uv run trading-lab data import-fixture
uv run trading-lab data describe
TRADING_LAB_MODE=research trading-lab data import-alpaca --start 2025-01-01 --end 2025-01-31
uv run trading-lab backtest fixture --strategy buy-and-hold
uv run trading-lab backtest fixture --strategy all --output .trading-lab/reports/baselines.json
uv run trading-lab experiment create-campaign baseline-v1 --name "Baseline campaign" --budget 20
uv run trading-lab experiment plan-training --spec PLAN.json
uv run trading-lab experiment run-planned candidate-1
uv run trading-lab experiment run --help
uv run trading-lab experiment run-holdout --help
uv run trading-lab experiment compare candidate-1 candidate-2
uv run trading-lab experiment evaluate-qualification --evidence-manifest config/research/qualification-evidence-v3.json --proposal config/research/qualification-proposal.json
```

Runtime state defaults to `.trading-lab/` and is not committed. Set `TRADING_LAB_HOME` to use another directory. `TRADING_LAB_MODE` defaults to `offline`; accepted modes are `offline`, `research`, `replay`, `shadow`, `paper`, and the deliberately non-operational `live-disabled`.

The CLI loads supported settings from an ignored repository-local `.env` file. Copy `.env.example`, set `TRADING_LAB_MODE=research`, and fill in the two Alpaca values. Existing process environment variables take precedence. The loader rejects unknown names and never enables live trading.

The Alpaca command is read-only, requires research mode and the `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` environment variables, requests fully provider-adjusted bars, and writes only immutable local data artifacts. Imports enforce issuer-sourced point-in-time membership before provider access. Corrections create parent-linked dataset versions; unadjusted inputs are rejected. It never submits orders.

Experiment commands create durable pending records before work begins, require an explicit claim before completion, retain failures, enforce campaign search budgets, and recover stale runs as failed evidence. The bounded `experiment run` command reads and validates only the declared timestamp range from an immutable cataloged dataset before executing a training or validation candidate. Manual and executed experiments take dataset and universe provenance from the catalog, but only controlled runner completions with one fingerprinted report can supply qualification evidence. `experiment evaluate-qualification` verifies the named registry records and their roles, aggregates the approved gate metrics, and writes a content-addressed report without loading market data. `experiment authorize-holdout` reruns that evaluation and can store one authorization only for approved, passing evidence. `experiment run-holdout` consumes that authorization before reading Parquet, loads only the bound timestamp range, and stores metrics without returning them or writing a report. The approved gates reject both current validation candidates, so no holdout is authorized. Ordinary commands cannot create or reveal holdout results.

`experiment plan-training` loads a strict `training-campaign-plan-v1` JSON file and atomically
preregisters every declared candidate under one immutable plan fingerprint. Its budget must equal
the candidate count. V1 accepts training splits, explicit strategy parameters, default conservative
costs, and next-bar fills only. `experiment run-planned` takes only a preregistered candidate ID, so
callers cannot override its strategy, dates, parameters, provenance, parent, or models.

The baseline suite includes cash, buy-and-hold, fixed-weight allocation, moving-average trend,
time-series momentum, moving-average mean reversion, and volatility-targeted exposure. These are
system checks, not optimized or financially qualified strategies.

## Quality gates

```console
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python scripts/check_secrets.py
```

Read [AGENTS.md](AGENTS.md), [CURRENT_STATE.md](CURRENT_STATE.md), and [docs/architecture.md](docs/architecture.md) before changing the system.
