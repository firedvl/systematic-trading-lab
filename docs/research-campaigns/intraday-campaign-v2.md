# Intraday research campaign v2 preregistration

Status: preregistered successor; no dataset has been acquired, no runtime state has been created, and no candidate has run.

Campaign ID: `intraday-research-v2`

Plan: `config/research/intraday-campaign-v2.json`

Plan fingerprint: `52db8a27fa4ff86865ab69b6bd7456899329ef3b861a582e59ab32904c03c122`

Reviewed foundation reference: `f3d7ee7d86c3a02b52c09270a6399aa1bf5f78b7`

Campaign V2 replaces the aborted V1 acquisition attempt. V1's plan, source review, runtime state, and quarantine evidence remain unchanged and read-only. No V1 candidate ran, so V2 carries forward the research matrix without using or reacting to a strategy result.

The foundation reference is not the execution commit. The execution-source review separately binds the final main-only attested wheel and installed runtime that may run V2.

## Frozen research design

The data contract is adjusted Alpaca IEX SPY and QQQ `5m` data from the XNYS regular session. Timestamps are inclusive UTC bar opens. Each role uses its own immutable dataset.

| Role | New York sessions | Exact inclusive UTC bar-open range | Expected bars per symbol |
| --- | --- | --- | ---: |
| Training | 2025-07-01 through 2025-12-31 | 2025-07-01T13:30:00Z through 2025-12-31T20:55:00Z | 9,876 |
| Validation A | 2026-01-02 through 2026-02-27 | 2026-01-02T14:30:00Z through 2026-02-27T20:55:00Z | 3,042 |
| Validation B | 2026-03-02 through 2026-04-30 | 2026-03-02T14:30:00Z through 2026-04-30T19:55:00Z | 3,354 |
| Validation C | 2026-05-01 through 2026-06-30 | 2026-05-01T13:30:00Z through 2026-06-30T19:55:00Z | 3,198 |

The fixed strategies are:

1. `intraday-cash`, with no parameters;
2. `intraday-previous-bar-momentum`, with `lookback = 1`;
3. `intraday-moving-average-trend`, with `window = 12`.

Each strategy-period pair reserves base 5/1 bps costs with one-bar delay, 10/2 bps and 20/5 bps cost stresses with one-bar delay, and base costs with two- and three-bar delays. The fixed search budget is 60. The plan authorizes no parameter neighbors, protected holdout, paper execution, broker writes, or live execution.

## Corrected acquisition boundary

For `1m` and `5m`, `AlpacaHistoricalProvider` derives the exact expected XNYS regular-session bar-open set. It maps each returned Alpaca bar and sends only requested-symbol records on that exact timestamp grid to normalization. A published dataset retains every mapped transport record in `raw.jsonl` and the raw fingerprint; a rejected import retains them and their fingerprint in quarantine evidence. Unexpected symbols remain in the validation stream so they still fail.

`DatasetService` and `validate_records` remain unchanged authorities for missing intervals, duplicates, unexpected symbols, ordering, and OHLCV validity. A malformed Alpaca payload or bar still aborts acquisition. An invalid mapped OHLCV record enters validation and fails even outside the requested grid. Transport extras cannot enter Parquet, but remain auditable raw evidence.

## Plan and dataset binding

Inspecting the plan creates no state:

```console
uv run trading-lab experiment inspect-intraday-plan \
  --spec config/research/intraday-campaign-v2.json
```

After this change reaches `main`, seal the plan once in the official registry:

```console
uv run trading-lab experiment plan-intraday \
  --spec config/research/intraday-campaign-v2.json
```

Acquire each exact period with independent read-only historical credentials. Record the dataset ID printed by each command:

```console
uv run trading-lab data import-alpaca \
  --timeframe 5m \
  --start 2025-07-01T13:30:00Z \
  --end 2025-12-31T20:55:00Z
```

Repeat only for the three exact Validation ranges in the table. Validate each published dataset, then bind all four in one transaction:

```console
uv run trading-lab data validate DATASET_ID

uv run trading-lab experiment bind-intraday-datasets \
  --campaign intraday-research-v2 \
  --training TRAINING_DATASET_ID \
  --validation-a VALIDATION_A_DATASET_ID \
  --validation-b VALIDATION_B_DATASET_ID \
  --validation-c VALIDATION_C_DATASET_ID
```

Binding checks the provider adapter, IEX feed, timeframe, adjustment, XNYS and timestamp policies, symbols, requested and actual ranges, dataset identity, and reviewed universe identity. Missing, invalid, duplicated, substituted, partial, or changed input leaves every reservation pending and unbound.

## Execution-source review

Campaign V2 preserves the V1 provenance controls:

- a main-only GitHub-attested application wheel and build manifest;
- one canonical trusted `gh` executable, retained by absolute path and SHA-256;
- exact wheel and non-editable installed-package checks;
- the fixed `uv.lock`, exact dependency wheelhouse, and exact installed dependency files;
- a startup-hook-free CPython 3.12 standard-library `venv --without-pip` runtime invoked through the fixed `-I -B -S` bootstrap;
- one immutable human-reviewed assessment while all 60 candidates are pending;
- a fresh matching assessment atomically bound to each candidate claim; and
- another assessment before immutable report publication.

The wheel-bound `intraday_campaign_v2_surface.json` manifest covers all 49 current application-package `.py` files by exact SHA-256, including `providers.py`, `datasets.py`, campaign admission, source review, runner, and qualification code. Added, missing, or changed modules fail. The manifest is inert; the reviewer must inspect the full main-attested source commit and wheel, verifier identity, and assessment fingerprint.

Prepare the fixed dependency wheelhouse and install the main-attested application wheel in a clean runtime:

```console
uv export --frozen --no-dev --no-emit-project \
  --format requirements.txt \
  --output-file runtime-requirements.txt
uvx --python 3.12 --from pip pip download \
  --only-binary=:all: \
  --require-hashes \
  --no-deps \
  --requirement runtime-requirements.txt \
  --destination-directory DEPENDENCY_WHEELHOUSE

CAMPAIGN_RUNTIME=/absolute/canonical/runtime
CAMPAIGN_SITE_PACKAGES=/absolute/canonical/runtime/lib/python3.12/site-packages
CAMPAIGN_BOOTSTRAP='import runpy,sys; sys.path.append(sys.argv.pop(1)); runpy.run_module("systematic_trading_lab.cli", run_name="__main__")'
python3.12 -m venv --without-pip "$CAMPAIGN_RUNTIME"
uv pip install \
  --python "$CAMPAIGN_RUNTIME/bin/python" \
  --no-index \
  --find-links DEPENDENCY_WHEELHOUSE \
  --requirement runtime-requirements.txt
uvx --from pip pip \
  --python "$CAMPAIGN_RUNTIME/bin/python" \
  --isolated install \
  --no-index \
  --no-deps \
  --no-compile \
  APPLICATION.whl
```

Assess without changing the registry:

```console
"$CAMPAIGN_RUNTIME/bin/python" -I -B -S -c "$CAMPAIGN_BOOTSTRAP" "$CAMPAIGN_SITE_PACKAGES" \
  experiment assess-intraday-source \
  --campaign intraday-research-v2 \
  --wheel APPLICATION.whl \
  --build-manifest runtime-build-manifest.json \
  --lockfile uv.lock \
  --dependency-wheelhouse DEPENDENCY_WHEELHOUSE
```

After a human reviews that exact output and the full attested source, record one immutable review:

```console
"$CAMPAIGN_RUNTIME/bin/python" -I -B -S -c "$CAMPAIGN_BOOTSTRAP" "$CAMPAIGN_SITE_PACKAGES" \
  experiment record-intraday-source campaign-v2-source-review \
  --campaign intraday-research-v2 \
  --wheel APPLICATION.whl \
  --build-manifest runtime-build-manifest.json \
  --lockfile uv.lock \
  --dependency-wheelhouse DEPENDENCY_WHEELHOUSE \
  --assessment-fingerprint REVIEWED_ASSESSMENT_FINGERPRINT \
  --reviewer REVIEWER \
  --reason "reviewed Campaign V2 execution build"
```

Only after the plan, all four datasets, and the source review exist may an operator run a reserved candidate:

```console
"$CAMPAIGN_RUNTIME/bin/python" -I -B -S -c "$CAMPAIGN_BOOTSTRAP" "$CAMPAIGN_SITE_PACKAGES" \
  experiment run-planned-intraday CANDIDATE_ID \
  --source-review campaign-v2-source-review \
  --wheel APPLICATION.whl \
  --build-manifest runtime-build-manifest.json \
  --lockfile uv.lock \
  --dependency-wheelhouse DEPENDENCY_WHEELHOUSE
```

Run one candidate per fresh single-purpose process. The command accepts no dataset, strategy, parameter, capital, cost, delay, window, or authority override. It grants no protected holdout, paper, broker-write, or live authority.
