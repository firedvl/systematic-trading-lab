# Systematic Trading Lab

Systematic Trading Lab is an open-source Python research platform for reproducible systematic-trading experiments, qualification, and tightly controlled paper execution.

The project is built around one principle: **research results and execution authority should be reproducible, reviewable, and difficult to grant by accident.** Dataset identity, experiment plans, qualification evidence, runtime provenance, risk decisions, and paper-account observations are recorded as explicit evidence instead of being inferred from ad-hoc scripts or mutable local state.

The current daily-bar research universe is SPY, QQQ, IWM, TLT, and GLD. Intraday research infrastructure is under active development. Real-money/live trading is intentionally unsupported.

> **Project status:** active development. Interfaces and evidence schemas may still change. The repository is suitable for research and paper-trading experimentation, not unattended real-money trading.

## Why this project exists

Systematic research can fail in ways that ordinary backtest code does not make obvious: accidental lookahead, changed datasets, unrecorded parameter searches, repeated holdout access, unverifiable runtime builds, stale broker state, and unsafe retry behavior.

This project treats those as software and evidence problems. It provides infrastructure for:

- immutable and fingerprinted research inputs;
- bounded training and validation runs;
- preregistered experiment campaigns and search budgets;
- protected holdout access and qualification evidence;
- conservative backtesting with explicit execution and cost assumptions;
- attested runtime builds and installed-runtime verification;
- transaction-bound paper-trading authority and risk controls;
- restart-safe paper observation and reconciliation;
- deterministic reports and durable operational evidence.

The goal is not to publish a supposedly profitable strategy. The goal is to make the path from data to research conclusion to paper execution inspectable and reproducible.

## Safety boundary

Real-money execution is disabled by design. Supported modes are:

- `offline`
- `research`
- `replay`
- `shadow`
- `paper`
- `live-disabled`

Paper broker writes require explicit paper mode plus separate activation, runtime identity, risk, authorization, and transaction-bound checks. Missing or ambiguous evidence fails closed. Read-only research and observation paths do not grant broker-write authority.

The project currently integrates with Alpaca for market data and paper-account workflows. Production trading hosts are not accepted by the paper execution boundary.

## Current capabilities

### Research and data

- Immutable cataloged datasets with provenance and fingerprints.
- Bounded reads that load only the declared training or validation interval.
- Corrections represented as parent-linked dataset versions.
- Baseline and candidate backtests with explicit execution assumptions.
- Durable experiment records, claims, failures, and bounded campaign budgets.
- Strict preregistered training plans that prevent run-time parameter or date overrides.
- Qualification evidence derived from controlled runs rather than caller-entered metrics.
- One-time, authorization-gated holdout evaluation.
- Research-only `1m` and `5m` SPY/QQQ data, replay, exact-range experiments, qualification evidence, closed V1/V2 campaigns, and a development-only V3 foundation.

### Paper execution and operations

- Append-only execution evidence and deterministic local order identities.
- Explicit paper authorization and reviewed risk configuration.
- Capacity reservation, order lifecycle, reconciliation, and recovery controls.
- Fixed-origin paper transport with bounded response handling and no blind retries.
- Runtime build manifests, GitHub attestations, and installed-runtime verification.
- Read-only startup assessment before broker mutation is permitted.
- Restart-safe paper observation campaigns and replay/shadow/paper equivalence evidence.
- Deployment and recovery runbooks for sustained observation.

For the exact current milestone and known limitations, see [`CURRENT_STATE.md`](CURRENT_STATE.md) and [`ROADMAP.md`](ROADMAP.md).

## Requirements

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- Git

Some data and paper workflows require an Alpaca account and credentials. The fixture-backed research path does not.

## Quick start

Clone the repository and install development dependencies:

```console
git clone https://github.com/firedvl/systematic-trading-lab.git
cd systematic-trading-lab
uv sync --dev
```

Check the local environment and import the committed synthetic fixture:

```console
uv run trading-lab doctor
uv run trading-lab data import-fixture
uv run trading-lab data import-intraday-fixture --timeframe 5m
uv run trading-lab data describe
```

Run the baseline suite:

```console
uv run trading-lab backtest fixture --strategy all --output .trading-lab/reports/baselines.json
```

Runtime state defaults to `.trading-lab/` and is intentionally not committed. Set `TRADING_LAB_HOME` to use another directory.

## Research workflow

A typical controlled workflow is:

1. Register or import immutable source data.
2. Create a bounded campaign or preregister an exact training plan.
3. Run candidates through the controlled experiment runner.
4. Generate and review qualification evidence.
5. Authorize protected holdout access only after qualification gates pass.
6. Keep any paper-execution authorization separate from research qualification.

Example commands:

```console
uv run trading-lab experiment create-campaign baseline-v1 --name "Baseline campaign" --budget 20
uv run trading-lab experiment plan-training --spec PLAN.json
uv run trading-lab experiment run-planned candidate-1
uv run trading-lab experiment inspect-intraday-plan --spec config/research/intraday-campaign-v2.json
uv run trading-lab experiment compare candidate-1 candidate-2
uv run trading-lab experiment evaluate-qualification \
  --evidence-manifest config/research/qualification-evidence-v3.json \
  --proposal config/research/qualification-proposal.json
```

The baseline suite includes cash, buy-and-hold, fixed-weight allocation, moving-average trend, time-series momentum, moving-average mean reversion, and volatility-targeted exposure. Baselines are system checks, not claims of profitability.

The repository also contains a predeclared strategic-allocation candidate whose controlled validation evidence passed the project's approved gates. That historical result is research evidence only; it does not promise future returns or by itself authorize broker writes.

The intraday workflow adds fixed cash, previous-bar-momentum, and 12-bar moving-average-trend engineering baselines for SPY and QQQ. Controlled runs use exact catalog ranges, flat-at-close sessions, completed-bar decisions, deterministic next-bar-open fills, and frozen cost and delay stress variants. The research-only qualification path cannot authorize holdout access, paper execution, or broker writes. See [`docs/intraday-research.md`](docs/intraday-research.md).

Campaign V1 was preregistered and source-reviewed, but its first real Alpaca Training acquisition exposed an extended-hours filtering defect before dataset publication. No candidate ran and no strategy result was observed. Its sealed plan, source review, runtime state, and quarantine evidence remain unchanged and read-only.

Campaign V2 completed all 60 controlled candidates and failed all 12 base research qualification groups under plan fingerprint `52db8a27fa4ff86865ab69b6bd7456899329ef3b861a582e59ab32904c03c122`. It remains closed immutable failed evidence. No intraday holdout was accessed or authorized. See [the V2 postmortem](docs/research-campaigns/intraday-campaign-v2-postmortem.md) and [historical runbook](docs/research-campaigns/intraday-campaign-v2.md).

The development-only V3 foundation uses state-transition trades and a FIFO N-bar delay so unchanged long states do not rebalance and pending transitions do not suppress later decisions. It adds fixed 12-bar MA, six-bar momentum, and six-bar opening-range breakout strategies plus a paired realistic/zero-cost diagnostic. The 60-candidate V3 design is a draft with no selected dates and cannot be sealed or executed. See [the V3 draft](docs/research-campaigns/intraday-campaign-v3-draft.md).

## Paper workflow

Paper execution is deliberately more cumbersome than ordinary research. Before any mutation, the system can assess the complete startup evidence surface without writing to the broker:

```console
uv run trading-lab paper initialize-storage
uv run trading-lab paper assess-startup \
  --authorization AUTHORIZATION_ID \
  --risk-config config/risk/alpaca-paper-v1.json
```

Read-only observation campaigns can then measure account continuity and drift:

```console
uv run trading-lab paper start-observation paper-week-1 \
  --maximum-gap-seconds 900 \
  --duration-hours 168
uv run trading-lab paper record-observation paper-week-1
uv run trading-lab paper assess-observation paper-week-1
```

See [`docs/operations.md`](docs/operations.md), [`docs/paper-execution-plan.md`](docs/paper-execution-plan.md), [`docs/paper-write-readiness.md`](docs/paper-write-readiness.md), and [`docs/risk-policy.md`](docs/risk-policy.md) before changing or operating paper-execution code.

## Configuration and credentials

Copy `.env.example` to `.env` for local workflows that require provider credentials. The repository-local `.env` is ignored.

The Alpaca data path requires `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`. Secrets must remain outside source control and must not appear in logs, reports, fixtures, prompts, or issue content.

The configuration loader rejects unknown names. Environment configuration alone cannot enable live trading.

## Development

Run the full local quality gates before opening a pull request:

```console
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python scripts/check_secrets.py
bash -n scripts/*.sh
uv build
```

Contributions are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md). Changes to protected controls, execution authority, risk semantics, evidence schemas, migrations, or security boundaries require especially careful tests and documentation.

Architecture and project history are intentionally kept in the repository:

- [`docs/architecture.md`](docs/architecture.md) — system boundaries and components
- [`docs/threat-model.md`](docs/threat-model.md) — security assumptions and protected controls
- [`DECISIONS.md`](DECISIONS.md) — durable architecture and policy decisions
- [`CURRENT_STATE.md`](CURRENT_STATE.md) — current operational/development state
- [`ROADMAP.md`](ROADMAP.md) — planned work and remaining gates

## Security

Please report vulnerabilities privately as described in [`SECURITY.md`](SECURITY.md). Do not open a public issue containing credentials, account data, sensitive broker responses, or exploitable details.

## License

Licensed under the Apache License 2.0. See [`LICENSE`](LICENSE).

## Disclaimer

This software is provided for research and software-development purposes. It does not provide financial advice, and historical or simulated results do not guarantee future performance.
