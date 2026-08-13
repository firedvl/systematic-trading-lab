# Intraday research campaign v1 preregistration

Status: aborted before dataset publication and before any candidate execution. The immutable source review remains historical evidence. New sealing, dataset binding, source review, and candidate execution are blocked under this campaign ID.

Campaign ID: `intraday-research-v1`

Plan: `config/research/intraday-campaign-v1.json`

Plan fingerprint: `ce81be36d02cc15f421390bf3d3787714bb0b025797ccfb8de2c1d1236052c1a`

Reviewed M5B foundation reference: `b1774f547da2976348430b820faf2ebdacdf46af`

The sealed foundation reference identifies the code reviewed when Campaign V1 was registered. It is not proof of the checkout or build that would execute a candidate. The sealed value is unchanged and must not be replaced during reconciliation. Execution-source evidence is stored separately.

## Final disposition

The first real Training import requested adjusted Alpaca IEX SPY/QQQ `5m` data. Alpaca returned the complete expected XNYS regular-session grid plus premarket, postmarket, normal-close-boundary, and early-close-boundary bars. `DatasetService` correctly rejected 2,758 out-of-session records, with no missing intervals and no duplicates. It published no dataset. No Campaign V1 strategy candidate ran, so no strategy result was observed.

The defect was in `AlpacaHistoricalProvider.fetch()`: it used the XNYS grid to set Alpaca's exclusive request end but passed every returned bar to dataset validation. Campaign V1 remains unchanged as evidence of that aborted attempt. Campaign V2 carries the same research design under a new plan and reviewed execution surface that includes the corrected adapter. See [the Campaign V2 runbook](intraday-campaign-v2.md).

The plan tests the M5B data, replay, registry, report, stress, and research-gate path. It does not search for a profitable strategy. A passing assessment would remain research evidence only.

## Frozen data design

The provider request is read-only Alpaca IEX, adjusted for all provider-supported actions. Every dataset contains only SPY and QQQ `5m` bars from the XNYS regular session. Timestamps label bar opens in UTC. Each period must be sealed and validated as its own immutable dataset before any candidate can run.

| Role | New York sessions | Exact inclusive UTC bar-open range | Sessions | Expected bars per symbol | Early closes |
| --- | --- | --- | ---: | ---: | ---: |
| Training | 2025-07-01 through 2025-12-31 | 2025-07-01T13:30:00Z through 2025-12-31T20:55:00Z | 128 | 9,876 | 3 |
| Validation A | 2026-01-02 through 2026-02-27 | 2026-01-02T14:30:00Z through 2026-02-27T20:55:00Z | 39 | 3,042 | 0 |
| Validation B | 2026-03-02 through 2026-04-30 | 2026-03-02T14:30:00Z through 2026-04-30T19:55:00Z | 43 | 3,354 | 0 |
| Validation C | 2026-05-01 through 2026-06-30 | 2026-05-01T13:30:00Z through 2026-06-30T19:55:00Z | 41 | 3,198 | 0 |

These windows cover about six training months followed by three contiguous two-month validation windows. The dates were chosen before strategy results. Data after 2026-06-30 is outside this campaign. This exclusion does not create or designate a protected holdout.

A period with zero scheduled XNYS early closes satisfies early-close coverage only after full calendar validation proves that zero is the complete expected count. A missing, malformed, fractional, or negative count fails the gate.

Any missing interval, duplicate, invalid OHLCV record, out-of-session bar, unexpected symbol, range mismatch, or failed dataset validation remains evidence and stops the affected candidate. The campaign does not repair or fabricate bars.

## Frozen strategies

The strategy set and parameters are the M5B engineering baselines:

1. `intraday-cash`, with no parameters;
2. `intraday-previous-bar-momentum`, with `lookback = 1`;
3. `intraday-moving-average-trend`, with `window = 12`.

Every strategy is long-only, unlevered, limited to one-half weight per symbol, and flat at each normal or early XNYS close under `XNYS-regular-session-flat-v1`. The campaign has no opening-range breakout, parameter neighbors, parameter search, shorting, leverage, options, or extended-hours data.

## Frozen costs and delays

| Role | Model | Slippage | Commission | Whole-bar delay |
| --- | --- | ---: | ---: | ---: |
| Base | `conservative-bps-v1` | 5 bps | 1 bp | 1 |
| Increased cost | `intraday-increased-cost-bps-v1` | 10 bps | 2 bps | 1 |
| Harsher cost | `intraday-harsher-cost-bps-v1` | 20 bps | 5 bps | 1 |
| `plus-1-bar` | `conservative-bps-v1` | 5 bps | 1 bp | 2 |
| `plus-2-bars` | `conservative-bps-v1` | 5 bps | 1 bp | 3 |

The values cannot change in campaign v1. The stress roles must keep the exact order and parent lineage required by `intraday-qualification-policy-v1`, fingerprint `42481069d9d0295d40ff1ccc6c956632d852f58522040d01024d7798172fe127`.

## Candidate reservations

Each strategy-period pair reserves five consecutive candidates in this order: base, increased cost, harsher cost, `plus-1-bar`, and `plus-2-bars`. Every stress candidate names that pair's base candidate as its parent. The fixed search budget is 60.

| Strategy | Training | Validation A | Validation B | Validation C |
| --- | ---: | ---: | ---: | ---: |
| Cash | 1–5 | 6–10 | 11–15 | 16–20 |
| Previous-bar momentum | 21–25 | 26–30 | 31–35 | 36–40 |
| 12-bar moving-average trend | 41–45 | 46–50 | 51–55 | 56–60 |

The official M5B assessor will run once for each of the 12 base candidates with only its four reserved children. Reports remain separate; the campaign will not produce a composite ranking score. Pending, failed, rejected, and completed candidates all count against the fixed budget and remain visible.

## Change control and stop rules

The strict plan loader rejects changed strategies, parameters, XNYS ranges, role ordering, costs, delays, policy identity, candidate ordinals, parameter neighbors, or authority flags. Inspect it without creating runtime state:

```console
uv run trading-lab experiment inspect-intraday-plan --spec config/research/intraday-campaign-v1.json
```

The following command was V1's sealing procedure. Do not run it now; the registry keeps V1 read-only and rejects new sealing:

```console
uv run trading-lab experiment plan-intraday --spec config/research/intraday-campaign-v1.json
```

The sealed campaign rejects arbitrary `run-intraday` candidates. Import the four exact period datasets with the read-only Alpaca historical adapter. The plan names provider `alpaca`; the immutable manifests record the concrete adapter `alpaca-historical-v2`, feed `iex`, and the reviewed `liquid-etfs-intraday-5m-v1` universe identity.

Fully validate all four datasets, derive all 60 specs, and bind every reservation in one transaction:

```console
uv run trading-lab experiment bind-intraday-datasets \
  --campaign intraday-research-v1 \
  --training TRAINING_DATASET_ID \
  --validation-a VALIDATION_A_DATASET_ID \
  --validation-b VALIDATION_B_DATASET_ID \
  --validation-c VALIDATION_C_DATASET_ID
```

The command verifies provider adapter, IEX feed, timeframe, adjustment, XNYS and timestamp policies, symbols, requested and actual ranges, dataset identity, and the reviewed universe identity. It derives strategy, split, costs, delay, parent, reviewed foundation reference, reason, and ordinal from the stored plan. Missing, invalid, duplicated, substituted, partially bound, or previously bound state fails before any registry mutation; all 60 reservations remain pending and unbound if the transaction fails.

## Execution-source review

This section records V1's historical review contract. It does not authorize another review or execution attempt.

Campaign V1 uses the existing main-only GitHub build attestation as the application-code trust anchor. The assessment snapshots the supplied artifacts and verifies:

- the application wheel and manifest GitHub attestations come from `firedvl/systematic-trading-lab` and `.github/workflows/build-provenance.yml`; both checks execute one canonical absolute executable named `gh`, verify its bytes before and after each call, and retain its path and SHA-256 in the build identity;
- the manifest names the exact wheel SHA-256, package, version, and actual source commit;
- the application wheel contains only `systematic_trading_lab/` and its own `.dist-info/` tree; the running project package is one non-editable install from that wheel, every wheel-owned installed file is byte-identical, the package tree has no extra importable files, and loaded project modules resolve inside it;
- `uv.lock` has the fixed foundation SHA-256 `d6d60aa5d93644dd3bf932ef84f6793bab6d33992659ed48e968850c6673c00d`;
- the dependency wheelhouse contains exactly one wheel for each of the ten non-development runtime dependencies and no other artifact;
- each dependency wheel's filename, size, version, and SHA-256 match a wheel listed in that lockfile; its paths and `RECORD` are safe and complete; and its installed package, native library, metadata, and data files match the wheel bytes;
- the runtime is CPython 3.12 from `python -m venv --without-pip`, not `uv venv`, and starts only through the fixed `-I -B -S` bootstrap with absolute canonical runtime and site-package paths;
- `pyvenv.cfg`, the executable/symlink chain and bytes, prefixes and `sys.path`, the complete base Python tree (standard library, native libraries, and `libpython` included), exact site tree, import-hook identities, decimal context, `America/New_York` timezone bytes, dependency wheels, and installed files match the recorded runtime identity; every assessment also rejects an invalid six hook state or any loaded module outside those exact trees without treating legitimate lazy imports as identity drift;
- no loader environment, `.pth`, `sitecustomize.py`, `usercustomize.py`, user site, unexpected distribution or path, unowned site file, symlink, special file, cached bytecode, or altered hook is present; and
- every `.py` file in the application package matches the wheel-bound `intraday_campaign_v1_surface.json` manifest. The manifest has 48 module records classified as foundation-exact, exact reviewed delta, or reviewed new file. It performs exact byte comparison with no AST normalization. Added, missing, or mutated modules fail. The exact reviewed deltas include PR #114 dataset-feed identity patch `3a339ab7866a22a2e200aee617395d9cc05e45c9` / diff `4ac13c3d58d675544a11b4bb00ea9d52996e53b1dc6e84c21658fc0485ec7f92`, and domain patch `952fc104c15c25260b0e29488df7ab61ae4b9a50` / diff `c3ded022ed3c9a7a8841c09c8d8c32dac167227c4e4bd084b0ef0605b564a65d`.

Any missing, extra, malformed, substituted, changed, or ambiguous input fails the assessment. A source-surface mismatch is not reviewable under Campaign V1 and requires Campaign V2. The surface manifest is wheel-bound but inert: no verifier proves its own bytes or classification. The human review must inspect the full main-attested source commit and wheel, the recorded GitHub CLI path and hash, and the resulting assessment fingerprint before recording it. The GitHub CLI file and every install-path ancestor must be owned by another trusted account and non-writable by the execution account.

Prepare the dependency wheelhouse on the target Python 3.12 platform from the fixed lockfile. The wheelhouse is untrusted input; the assessment accepts only the lock-listed bytes:

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
```

Install the final main-only attested application wheel and those dependencies in a clean CPython 3.12 standard-library venv. Do not use `uv venv`:

```console
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

The application install must retain pip's wheel SHA-256 origin record and must not compile bytecode; the verifier rejects an empty archive digest or any cached bytecode.

Run every provenance and candidate command through that interpreter with the exact bootstrap below. `-I -B -S` and the absolute canonical `CAMPAIGN_RUNTIME` and `CAMPAIGN_SITE_PACKAGES` values are required. The runtime may contain only the application and the ten locked runtime dependencies.

Inspect the evidence without changing the registry:

```console
"$CAMPAIGN_RUNTIME/bin/python" -I -B -S -c "$CAMPAIGN_BOOTSTRAP" "$CAMPAIGN_SITE_PACKAGES" \
  experiment assess-intraday-source \
  --campaign intraday-research-v1 \
  --wheel APPLICATION.whl \
  --build-manifest runtime-build-manifest.json \
  --lockfile uv.lock \
  --dependency-wheelhouse DEPENDENCY_WHEELHOUSE
```

After an explicit review of the output, record that exact assessment fingerprint. This operation requires the sealed plan and all 60 candidates in `pending` state. It creates one immutable campaign review and grants no execution or broker authority by itself:

```console
"$CAMPAIGN_RUNTIME/bin/python" -I -B -S -c "$CAMPAIGN_BOOTSTRAP" "$CAMPAIGN_SITE_PACKAGES" \
  experiment record-intraday-source campaign-v1-source-review \
  --campaign intraday-research-v1 \
  --wheel APPLICATION.whl \
  --build-manifest runtime-build-manifest.json \
  --lockfile uv.lock \
  --dependency-wheelhouse DEPENDENCY_WHEELHOUSE \
  --assessment-fingerprint REVIEWED_ASSESSMENT_FINGERPRINT \
  --reviewer REVIEWER \
  --reason "reviewed Campaign V1 execution build"
```

`experiment run-planned-intraday CANDIDATE_ID` accepts no dataset, strategy, parameter, capital, cost, delay, window, or authority override. It requires the concrete registry and dataset service to share one storage root with the report directory, uses the foundation's `100000` initial cash, constructs the exact cost model from the stored sealed spec, and reassesses the supplied build and runtime internally. In one immediate transaction it verifies the immutable review, inserts an immutable per-candidate source binding, and changes that candidate from `pending` to `running`. A mismatch rolls back both the binding and claim before market-data access. After computation it reassesses the runtime before publishing the source-bound report. Qualification requires the report review and binding evidence to match the registry.

```console
"$CAMPAIGN_RUNTIME/bin/python" -I -B -S -c "$CAMPAIGN_BOOTSTRAP" "$CAMPAIGN_SITE_PACKAGES" \
  experiment run-planned-intraday CANDIDATE_ID \
  --source-review campaign-v1-source-review \
  --wheel APPLICATION.whl \
  --build-manifest runtime-build-manifest.json \
  --lockfile uv.lock \
  --dependency-wheelhouse DEPENDENCY_WHEELHOUSE
```

The V1 source review was recorded before the acquisition attempt and remains immutable. It cannot authorize a retry from changed code. Do not rerun, rebind, or replace it, and do not change `base_code_commit` to bridge the provenance gap.

The verifier assumes the host kernel, Python process, GitHub attestation service, and SHA-256 remain trustworthy. Snapshots, attestation-verifier checks, pre-claim verification, and pre-publication verification detect persistent artifact or installed-file changes. They do not prove that transient privileged memory or executable modification did not occur and get restored in the same process, or that the OS kernel or loader was not compromised. Remote attestation is only valid after merge. Keep the GitHub CLI installation owned by another trusted account, keep it, the installed runtime, and artifacts non-writable by the execution account, and run one candidate in a fresh single-purpose process.

After the first observed strategy result, any change requires a new campaign version. A software defect invalidates the affected campaign version; it must not be silently rerun under the same identity.

Keep the research registry, credentials, and data separate from daily paper runtime state. Dataset acquisition requires independent read-only historical credentials. The daily paper runtime, its authorization, activation, and broker-write controls remain outside scope.

No protected intraday holdout exists. This plan cannot create, authorize, inspect, or reveal one. It also grants no paper, broker-write, or live authority.
