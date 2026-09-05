# Systematic Trading Lab

Systematic Trading Lab is an open-source Python framework for U.S. ETF data, strategy backtests, parameter sweeps, walk-forward evaluation, and guarded paper-trading research.

> **Status:** active development. Research and paper workflows exist. Live trading is disabled. Backtests do not establish future profitability.

## What you can do

- Import synthetic, Alpaca, CSV, or Parquet daily OHLCV data.
- Add a strategy through one typed interface and registry.
- Run net-of-cost backtests and bounded parameter sweeps.
- Evaluate fixed parameters through chronological walk-forward folds.
- Stress results with higher costs and longer fill delays.
- Store, inspect, compare, and export exploratory candidates.
- Use separate controlled qualification and paper systems when a candidate is ready for review.

Research iteration is cheap; promotion and execution remain strict.

## Quick start

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), and Git.

```console
git clone https://github.com/firedvl/systematic-trading-lab.git
cd systematic-trading-lab
uv sync --dev

uv run trading-lab doctor
uv run trading-lab data import-fixture
uv run trading-lab data list
uv run trading-lab research list-strategies
```

The fixture has a stable dataset ID. Run a small smoke backtest:

```console
uv run trading-lab research backtest \
  --dataset 042e1e94eee7bbc1fe47c2f473bbbf93d773296a135486fa74fb34861c46e06d \
  --strategy moving-average \
  --parameter window=2
```

Inspect stored results and run one fixture-sized walk-forward fold:

```console
uv run trading-lab research list
uv run trading-lab research walk-forward \
  --dataset 042e1e94eee7bbc1fe47c2f473bbbf93d773296a135486fa74fb34861c46e06d \
  --strategy moving-average \
  --parameter window=2 \
  --training-window 2 \
  --test-window 2 \
  --step-size 2
```

The five-session fixture checks installation and command flow. Use longer history before interpreting research metrics. Runtime data defaults to `.trading-lab/` and is not committed.

Program 005 provides a credential-free preflight for its private Alpaca SIP dataset recipe:

```console
uv run trading-lab data acquire program-005 preflight --scope qualification
```

See [Program 005 private Alpaca data](docs/program-005-alpaca-data.md) for the private storage,
credential, authority, and reproduction rules. No Program 005 source request is active by default.

Program 006 was the credential-safe one-use successor. Its repeatable presence check reports only
missing environment-variable names and never contacts Alpaca:

```console
uv run trading-lab data acquire program-006 credential-preflight
```

See [Program 006 Alpaca source qualification](docs/program-006-alpaca-qualification.md). Its exact
one-use qualification is consumed and failed. Do not activate or run it again.

Program 007's exact one-use corporate-action metadata qualification is consumed and failed. The
endpoint returned HTTP 200, but the first symbol-chain page contained cash-dividend records with
empty required `cusip` values. Frozen schema validation stopped before the CUSIP chain or
reconciliation.

```console
uv run trading-lab data acquire program-007-metadata credential-preflight
```

See [Program 007 corporate-action metadata qualification](docs/program-007-corporate-action-metadata-qualification.md).
Do not activate or run Program 007 metadata again. Do not proceed to its OHLCV qualification.

Offline analysis found that Alpaca's current `data_quality=complete` contract permits processed
records with missing CUSIP or ISIN. [Program 008](docs/research-campaigns/program-007-corporate-action-metadata-offline-forensics-v1.md)
then completed its exact one-use CUSIP-only qualification with a terminal PASS. The consumed run
made one request, retained one 83,338-byte HTTP 200 page privately, parsed 354 unique events, and
recovered all five required split controls without a relevant ledger discrepancy.

Do not activate or run Program 008 metadata again. Its consumed authority grants no OHLCV,
dataset, strategy, controlled/protected, PAPER, broker, or live authority.

Program 009, `multi-hour-sector-etf-research-008`, is terminally consumed and failed. The exact
one-use run retained nine raw SIP HTTP 200 pages, but the sixth allowed page of the frozen pagination
chain still had a continuation token. The executor stopped without requesting page seven or the two
remaining chains. Its repeatable preflight still checks only the existing Program 006 credential
names and does not load values or contact Alpaca:

```console
uv run trading-lab data acquire program-009-ohlcv credential-preflight
```

See [Program 009 raw OHLCV structural qualification](docs/program-009-raw-ohlcv-qualification.md).
Do not activate or run Program 009 again. It admitted no dataset and ran no strategy.

Offline forensics classify Program 009's six-page ceiling as a qualification-specification defect,
confirm one completed-domain MDY source gap, and classify the truncated XLY tail as unobserved.
Program 010, `multi-hour-sector-etf-research-009`, is terminally consumed and failed after one
105,852-byte HTTP 200 page. Its frozen parser incorrectly treated unordered JSON object-member
encounter order as global symbol order. Offline forensics found all 1,000 retained coordinates unique
and expected and every per-symbol bar array timestamp-ascending, so the stop is a
qualification-specification defect rather than provider incompatibility. See
[Program 010 raw OHLCV structural qualification](docs/program-010-raw-ohlcv-qualification.md).
Do not activate or run Program 010 again. It admitted no dataset and ran no strategy. Program 011,
its source-qualification successor, is terminally consumed and passed. Its exact one-use run retained
nine HTTP 200 responses totaling 490,879 bytes across five fresh sessions. All 4,602 expected
coordinates were present, with no source-missing or unobserved coordinates. See
[Program 011 raw OHLCV structural qualification](docs/program-011-raw-ohlcv-qualification.md).
Do not activate or run Program 011 again. It admitted no dataset and ran no strategy. Full exposed
acquisition and structural dataset admission require a separate reviewed standing child authority.

Program 012 limited that acquisition to the unprotected context and exposed prefix through
`2025-12-31`. Its reviewed one-use child is now consumed and sealed as `FAIL-CONSUMED-NO-RETRY`.
The redacted public terminal records a runtime failure, no structural admission, no dataset lineage,
and no strategy work. Dynamic acquisition state and private content identity remain private. A
finding-free independent terminal review confirmed the closeout and replay guard. Do not run its
credential preflight, activation, or acquisition again. See
[Program 012 exposed-prefix acquisition](docs/program-012-exposed-prefix-acquisition.md).

Program 013's reviewed one-use child is consumed and sealed as `FAIL-CONSUMED-NO-RETRY`. The
redacted public terminal records a runtime failure, no structural admission, no dataset lineage, and
no strategy work. Dynamic acquisition state and detailed failure evidence remain private. Current
code rejects credential preflight, authority derivation, activation, loading, and execution before
credential or private-root access. A finding-free independent terminal review confirmed the exact
terminal bytes and replay guard. Do not run Program 013 again. See
[Program 013 exposed-prefix recovery](docs/program-013-exposed-prefix-recovery.md).

Program 014's recovery runtime is implemented and independently reviewed, but it has no active child
authority. Do not run its credential preflight or acquisition yet. The next gate is to merge the
exact runtime binding, freeze clean synchronized main, then add and review only the one-use child and
its review. See [Program 014 exposed-prefix recovery](docs/program-014-exposed-prefix-recovery.md).

## Using historical data

Alpaca imports are read-only and require research mode plus credentials:

```console
export TRADING_LAB_MODE=research
export APCA_API_KEY_ID=your-key
export APCA_API_SECRET_KEY=your-secret

uv run trading-lab data import-alpaca \
  --start 2020-07-27 \
  --end 2025-06-30 \
  --timeframe 1d
```

Use `--universe-config PATH` to acquire a different versioned daily universe without changing the
default five-ETF definition.

An explicit versioned universe can use the read-only Yahoo fallback when Alpaca credentials are
unavailable:

```console
TRADING_LAB_MODE=research uv run trading-lab data import-yahoo \
  --start 2020-07-27 \
  --end 2026-07-31 \
  --universe-config config/research/rapid-004-seed-universe-v1.json
```

You can also import daily CSV or Parquet data:

```console
uv run trading-lab data import-local path/to/bars.csv
uv run trading-lab data list
```

Required columns:

```text
timestamp,symbol,open,high,low,close,volume
2025-01-06T00:00:00Z,SPY,100,102,99,101,1000000
```

Local files are labeled `user-supplied`; their adjustment policy is unknown. See [Getting started](docs/getting-started.md) and [Data policy](docs/data-policy.md).

## Developing a strategy

Strategies return target positions and never call a broker. Add the class to `rapid_strategies.py`, declare its public parameters in `strategy_registry.py`, add a focused test, then run it by registry name.

See [Strategy development](docs/strategy-development.md) for the interface and a complete example.

## Research workflow

```text
Data
  ↓
Explore: backtest + sweep
  ↓
Robustness: walk-forward + stress
  ↓
Zero-authority candidate export
  ↓
Human-reviewed controlled plan + untouched evidence
  ↓
Controlled qualification
  ↓
Guarded paper evaluation
  ↓
Live: unsupported
```

Rapid Research is exploratory. It uses a separate SQLite database and artifact directory, never writes controlled campaign or execution registries, and cannot grant protected holdout, paper, broker-write, or live authority. V3 is a separately sealed long-horizon forward-validation benchmark. Its exact main seal was attested before Validation A, and the sealed campaign has been materialized with 60 pending reservations. No selected V3 dataset or result has been observed. Rapid Research rejects those windows, so V3 does not block normal historical research.

See [Rapid Research](docs/rapid-research.md) for backtests, sweeps, walk-forward defaults, metrics, stress tests, storage, and candidate export.

## Safety

- Strategies and research code have no broker-write path.
- Candidate export grants zero authority and never promotes automatically.
- Paper writes require separate authorization, activation, runtime, risk, reconciliation, and transaction checks.
- Live trading is prohibited by repository policy and configuration.
- Credentials and local market data must stay outside source control.

Read [Security](SECURITY.md) and the [Threat model](docs/threat-model.md) before changing a protected boundary.

## Documentation

| Area | Start here |
| --- | --- |
| Installation and first backtest | [Getting started](docs/getting-started.md) |
| Strategies and research | [Strategy development](docs/strategy-development.md), [Rapid Research](docs/rapid-research.md) |
| Paper trading | [Paper execution plan](docs/paper-execution-plan.md), [Operations](docs/operations.md) |
| Architecture and research integrity | [Architecture](docs/architecture.md), [Research policy](docs/research-policy.md) |
| Full index | [Documentation](docs/README.md) |

Campaign history, V1/V2/V3 provenance, attestation mechanics, and detailed paper procedures live in `docs/`, not in this onboarding page.

## Contributing

Run the local gates before opening a pull request:

```console
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python scripts/check_secrets.py
bash -n scripts/*.sh
uv build
```

See [Contributing](CONTRIBUTING.md) and [Open-source guidance](docs/OPEN_SOURCE.md).

## License and disclaimer

Licensed under the [Apache License 2.0](LICENSE).

This software is for research and software development. It is not financial advice. Historical, simulated, and paper results do not guarantee future performance.
