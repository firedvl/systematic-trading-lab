# Systematic Trading Lab

Research infrastructure for reproducible U.S. ETF data, backtests, qualification, and paper execution. The current scope is daily bars for SPY, QQQ, IWM, TLT, and GLD. Live trading is disabled.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```console
uv sync --dev
uv run trading-lab doctor
uv run trading-lab data import-fixture
uv run trading-lab data describe
```

Runtime state defaults to `.trading-lab/` and is not committed. Set `TRADING_LAB_HOME` to use another directory. `TRADING_LAB_MODE` defaults to `offline`; accepted modes are `offline`, `research`, `replay`, `shadow`, `paper`, and the deliberately non-operational `live-disabled`.

## Quality gates

```console
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python scripts/check_secrets.py
```

Read [AGENTS.md](AGENTS.md), [CURRENT_STATE.md](CURRENT_STATE.md), and [docs/architecture.md](docs/architecture.md) before changing the system.
