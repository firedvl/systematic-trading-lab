# Systematic Trading Lab

Research infrastructure for reproducible U.S. ETF data, backtests, qualification, and paper execution. Approved research and paper execution remain daily-only for SPY, QQQ, IWM, TLT, and GLD. The isolated intraday branch adds offline `1m` and `5m` SPY/QQQ data, replay, experiment, report, fixed-baseline, and research-gate foundations. Intraday holdout and paper authority remain absent. Live trading is disabled.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```console
uv sync --dev
uv run trading-lab doctor
uv run trading-lab data import-fixture
uv run trading-lab data import-intraday-fixture --timeframe 5m
uv run trading-lab data describe
TRADING_LAB_MODE=research trading-lab data import-alpaca --start 2025-01-01 --end 2025-01-31
TRADING_LAB_MODE=research trading-lab data import-alpaca --timeframe 5m --start 2025-01-06T14:30:00Z --end 2025-01-06T20:55:00Z
uv run trading-lab backtest fixture --strategy buy-and-hold
uv run trading-lab backtest fixture --strategy all --output .trading-lab/reports/baselines.json
uv run trading-lab experiment create-campaign baseline-v1 --name "Baseline campaign" --budget 20
uv run trading-lab experiment plan-training --spec PLAN.json
uv run trading-lab experiment run-planned candidate-1
uv run trading-lab experiment run-intraday --help
uv run trading-lab experiment assess-intraday --help
uv run trading-lab experiment run --help
uv run trading-lab experiment run-holdout --help
uv run trading-lab experiment compare candidate-1 candidate-2
uv run trading-lab experiment evaluate-qualification --evidence-manifest config/research/qualification-evidence-v3.json --proposal config/research/qualification-proposal.json
uv run trading-lab experiment review-holdout --help
uv run trading-lab paper initialize-storage
uv run trading-lab paper assess-startup --authorization AUTHORIZATION_ID --risk-config config/risk/alpaca-paper-v1.json
uv run trading-lab paper start-observation paper-week-1 --maximum-gap-seconds 900 --duration-hours 168
uv run trading-lab paper record-observation paper-week-1
uv run trading-lab paper assess-observation paper-week-1
uv run trading-lab paper record-equivalence paper-week-1 initial-entry --replay-plan REPLAY.json --shadow-plan SHADOW.json --paper-intent INTENT_KEY
```

Runtime state defaults to `.trading-lab/` and is not committed. Set `TRADING_LAB_HOME` to use another directory. `TRADING_LAB_MODE` defaults to `offline`; accepted modes are `offline`, `research`, `replay`, `shadow`, `paper`, and the deliberately non-operational `live-disabled`.

The CLI loads supported settings from an ignored repository-local `.env` file. Copy `.env.example`, set `TRADING_LAB_MODE=research`, and fill in the two Alpaca values. Existing process environment variables take precedence. The loader rejects unknown names and never enables live trading. Paper broker writes pass the outer runtime gate only when paper mode names both an exact activation fingerprint and full execution commit; transaction-bound authority checks still decide every attempt.

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

The isolated M5B workflow adds fixed intraday cash, previous-bar momentum, and 12-bar moving-average trend engineering baselines for SPY and QQQ. Controlled training and validation runs use exact catalog ranges, `XNYS-regular-session-flat-v1`, completed-bar decisions, and deterministic next-bar-open fills. `intraday-backtest-report-v1` records intraday exposure, activity, holding duration, cost, concentration, benchmark, and session-boundary evidence. `intraday-qualification-policy-v1` assesses frozen cost and delay variants as research evidence only; it grants no holdout, paper, or broker-write authority. See [docs/intraday-research.md](docs/intraday-research.md).

The strategic-allocation candidate holds 35% SPY, 25% QQQ, 25% IWM, 15% GLD, and 0% TLT with a
predeclared 21-session rebalance interval. Its controlled validation evidence passed the approved
gates; that result does not promise future returns or enable broker writes.

`paper initialize-storage` creates the empty paper execution schema without adding authority or
enabling broker writes. It is safe to repeat and rejects a symbolic-link database path.

`paper assess-startup` is read-only. It checks the journal, authorization, limits, activation,
installed runtime identity, unresolved mutations, emergency state, and attested risk context. Missing
evidence appears as a blocker. The command cannot enable or call the paper operator.

The paper observation commands are broker-read-only and require paper mode plus Alpaca credentials,
but no activation. A campaign binds its first production-attested snapshot, expected positions,
maximum sample gap, and end time. Later samples record healthy state, position or open-order drift,
or a sanitized read failure. Assessment reports current staleness, failure and drift counts, and the
largest completed sample gap. Observation evidence cannot submit, cancel, settle, or clear an
emergency.

`paper record-equivalence` compares strict replay and shadow action-plan files with immutable stored
paper quantity intents. It retains exact matches and mismatches under the observation campaign. The
command cannot submit, cancel, settle, or approve an action.

## Quality gates

```console
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python scripts/check_secrets.py
bash -n scripts/*.sh
```

Read [AGENTS.md](AGENTS.md), [CURRENT_STATE.md](CURRENT_STATE.md), and [docs/architecture.md](docs/architecture.md) before changing the system.
