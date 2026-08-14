# Contributing

Contributions are welcome. Systematic Trading Lab contains ordinary research code alongside protected execution, provenance, and risk boundaries, so the amount of review required depends on what a change touches.

## Before you start

Read:

- `README.md` for setup and project scope;
- `docs/strategy-development.md` for the public strategy interface and registry;
- `docs/rapid-research.md` for the ordinary research workflow;
- `CURRENT_STATE.md` for the current implementation state;
- `docs/architecture.md` for system boundaries;
- `docs/threat-model.md` for security assumptions;
- `docs/risk-policy.md`, `docs/paper-execution-plan.md`, and `docs/paper-write-readiness.md` before changing execution or risk behavior.

For a substantial change, open an issue first when practical. Small fixes, tests, documentation improvements, and clearly scoped refactors can go directly to a pull request.

## Development setup

```console
git clone https://github.com/firedvl/systematic-trading-lab.git
cd systematic-trading-lab
uv sync --dev
uv run trading-lab doctor
uv run trading-lab data import-fixture
```

The committed fixture is enough for most development and test work. Do not require contributors to provide broker credentials for code paths that can be exercised offline.

For a first strategy contribution, keep the class target-only, register only the parameters it uses, and include one deterministic unit test plus a fixture-backed Rapid Research command check.

## Pull requests

Keep each pull request focused. In particular, keep protected-control changes separate from strategy/research changes unless they cannot reasonably be separated.

A good pull request should explain:

1. what changed;
2. why the change is needed;
3. which safety or evidence boundaries it touches;
4. what tests prove the intended behavior and failure path;
5. any migration, compatibility, or operational impact.

Update durable documentation when a change modifies architecture, policy, evidence schemas, operating procedure, or the project's recorded state.

## Verification

Run the relevant focused tests while developing, then run the full local quality gates before requesting review:

```console
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python scripts/check_secrets.py
bash -n scripts/*.sh
```

If a change touches packaging or runtime provenance, also build the wheel and exercise the relevant manifest/attestation checks described in the repository documentation.

## Protected areas

Changes involving any of the following need explicit failure-path tests and careful review:

- paper broker writes or transport allowlists;
- authorization, activation, or execution identity;
- risk limits, capacity reservation, or emergency state;
- reconciliation and unknown-outcome recovery;
- dataset, experiment, qualification, or holdout provenance;
- journal or evidence schema changes;
- migrations and restart/recovery behavior;
- build provenance or installed-runtime verification.

Do not weaken a fail-closed boundary merely to make a test, workflow, or local environment more convenient.

## Data and secrets

Never commit:

- API keys, tokens, credentials, or `.env` files;
- private account or broker data;
- runtime databases or journals;
- downloaded market datasets unless explicitly approved as a small public fixture;
- generated reports that contain non-public evidence;
- raw broker responses;
- local runtime builds, caches, or temporary files.

Use synthetic or sanitized fixtures for regression tests.

## Research claims

Do not describe a strategy as profitable, safe, production-ready, or validated beyond the evidence actually recorded by the project. Backtests, validation results, and paper observations are historical evidence, not guarantees of future performance.

## Licensing

By submitting a contribution for inclusion in this repository, you agree that your contribution is provided under the Apache License 2.0, consistent with the repository `LICENSE`.
