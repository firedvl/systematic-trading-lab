# Getting started

This path needs no broker account or network access after dependency installation.

## Install

Use Python 3.12 or newer, Git, and [uv](https://docs.astral.sh/uv/).

```console
git clone https://github.com/firedvl/systematic-trading-lab.git
cd systematic-trading-lab
uv sync --dev
```

## Check the runtime

```console
uv run trading-lab doctor
```

Every check should be `true`. Runtime state defaults to `.trading-lab/`. To use another location:

```console
export TRADING_LAB_HOME=/absolute/path/to/trading-lab-state
```

Do not point it at the repository root.

## Import fixture data

```console
uv run trading-lab data import-fixture
uv run trading-lab data list
```

The deterministic fixture contains five daily sessions for SPY, QQQ, IWM, TLT, and GLD. Its stable ID is:

```text
042e1e94eee7bbc1fe47c2f473bbbf93d773296a135486fa74fb34861c46e06d
```

## Run the first backtest

```console
uv run trading-lab research list-strategies
uv run trading-lab research backtest \
  --dataset 042e1e94eee7bbc1fe47c2f473bbbf93d773296a135486fa74fb34861c46e06d \
  --strategy moving-average \
  --parameter window=2
```

The JSON result includes a `run_id`, status, costs, net metrics, and report path. Repeating the same run under the same code identity returns the stored result.

Inspect it later:

```console
uv run trading-lab research list
uv run trading-lab research show RUN_ID
```

## Run a fixture walk-forward check

```console
uv run trading-lab research walk-forward \
  --dataset 042e1e94eee7bbc1fe47c2f473bbbf93d773296a135486fa74fb34861c46e06d \
  --strategy moving-average \
  --parameter window=2 \
  --training-window 2 \
  --test-window 2 \
  --step-size 2
```

This creates one chronological fold. It proves the command path, not a research conclusion. Use longer history for several folds and market regimes.

## Import Alpaca daily data

Copy `.env.example` to `.env`, set research mode and credentials, then choose an exposed historical range outside the protected V3 windows:

```console
cp .env.example .env
```

```dotenv
TRADING_LAB_MODE=research
TRADING_LAB_HOME=.trading-lab
APCA_API_KEY_ID=
APCA_API_SECRET_KEY=
```

Fill the two empty credential values only in your ignored local `.env` file.

```console
uv run trading-lab data import-alpaca \
  --start 2020-07-27 \
  --end 2025-06-30 \
  --timeframe 1d
uv run trading-lab data list
```

Alpaca imports cover the repository's fixed daily ETF universe and record provider, feed, adjustment, universe, range, raw, normalized, and validation evidence.

## Import local data

CSV and Parquet files must contain exactly these daily OHLCV fields:

```text
timestamp,symbol,open,high,low,close,volume
2025-01-06T00:00:00Z,SPY,100,102,99,101,1000000
2025-01-07T00:00:00Z,SPY,101,103,100,102,1001000
```

Timestamps must be UTC dates or midnight UTC. Rows must be increasing per symbol and cover every XNYS session between the first and last date for every included symbol.

```console
uv run trading-lab data import-local path/to/bars.csv
uv run trading-lab data import-local path/to/bars.parquet
uv run trading-lab data list
```

Local data stays in the Rapid Research namespace. It is labeled `user-supplied` with adjustment policy `user-supplied-unknown-v1`; it cannot become controlled evidence by import alone.

Next: [develop a strategy](strategy-development.md) or read the full [Rapid Research guide](rapid-research.md).
