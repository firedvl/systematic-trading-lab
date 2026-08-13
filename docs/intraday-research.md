# Intraday research foundation

M5B adds offline experiment, report, and research-gate contracts for cataloged `1m` and `5m` SPY/QQQ data. It does not add a protected intraday holdout, paper execution, broker writes, strategy promotion, or live authority.

## Architecture

M5B reuses the experiment registry lifecycle, campaign search budgets, exact-range catalog reads, deterministic simulator, versioned basis-point costs, complete-slice portfolio decisions, and immutable report storage. Daily `ExperimentSpec`, `training-campaign-plan-v1`, `backtest-report-v2`, daily qualification, daily holdout authorization, and paper controls remain unchanged.

`intraday-experiment-v1` is a separate contract stored by the shared registry. It binds:

- experiment and research campaign IDs, fixed search budget, and candidate ordinal;
- strategy ID, version, family, parameters, parent candidate, and creation reason;
- sealed reviewed-foundation reference and random seed;
- dataset and universe IDs and fingerprints;
- `1m` or `5m` timeframe and exact inclusive UTC bar-open range;
- `bar-open-utc-v1`, `XNYS-regular-session-flat-v1`, and `XNYS-session-close-equity-v1`;
- benchmark, cost, and execution model versions;
- slippage and commission values;
- `completed-bar-next-bar-open-v1` earliest-fill semantics and whole-bar delay;
- training or validation split.

The registry creates and claims the candidate before data loading. Dataset, replay, strategy, or report failures remain failed campaign evidence. Completed runs store one immutable report location and fingerprint. Candidate ordinals must be unique and fit the campaign's fixed search budget.

Run a fixed baseline with:

```console
uv run trading-lab experiment create-campaign m5b-baselines-v1 --name "M5B fixed baselines" --budget 5
uv run trading-lab experiment run-intraday candidate-001 \
  --campaign m5b-baselines-v1 \
  --candidate-ordinal 1 \
  --strategy previous-bar-momentum \
  --code-commit REVISION \
  --dataset DATASET_ID \
  --timeframe 5m \
  --split training \
  --start 2025-01-02T14:30:00Z \
  --end 2025-03-31T19:55:00Z \
  --reason "fixed engineering baseline"
```

The controlled intraday runner accepts training and validation only. It rejects daily data, unsupported dataset calendar or timestamp policies, mismatched costs, and any holdout authority.

## Fixed baseline strategies

The initial strategies are deterministic, long-only, unlevered, regular-session portfolio strategies over SPY and QQQ:

- `intraday-cash`: no targets and no trades;
- `intraday-previous-bar-momentum`: one-bar directional momentum with at most one-half weight per symbol;
- `intraday-moving-average-trend`: 12-bar close-versus-average trend with at most one-half weight per symbol.

These parameters are engineering baselines, not optimized values or profitability claims. The CLI does not expose parameter overrides. Opening-range breakout is deferred because a reviewed opening-range and late-entry contract would enlarge this slice.

## Causal execution and session close

At a bar-open timestamp, the engine first fills orders created from earlier completed bars. It then observes the current bar at `bar_open + duration`, creates the decision and order, and permits the next eligible bar open as the earliest fill. For a contiguous `10:00–10:05` bar, the decision and the `10:05` next-bar-open fill can share a timestamp. The order already exists at that timestamp and the engine processes the fill before observing the new `10:05–10:10` bar. It never uses the `10:05` open or later bar contents to create that fill.

This is a deterministic bar-level approximation with zero additional latency at the eligible open. `execution_delay_bars` adds whole same-symbol bars. It does not model quotes, queue position, spread paths, partial fills, market impact, halts, or network latency.

All M5B strategies use `XNYS-regular-session-flat-v1`. The engine schedules a flattening target early enough for its configured delay to fill at the final validated bar open. It rejects entries and pending orders that cannot enter and flatten safely. It derives normal and early closes from XNYS data validation and fails if any session ends with a position or pending order. It does not invent a close-price fill after observing the close.

## Report contract

`intraday-backtest-report-v1` is deterministic and self-contained. It binds the full experiment provenance, replay artifact fingerprint, and report fingerprint. Campaign V1 reports retain the sealed foundation reference in experiment provenance and add separate immutable execution-source review and per-candidate binding evidence. Qualification checks that evidence against the registry. It records failed runs in the registry and reports zero-trade runs without dropping them.

The report exposes:

- total return, maximum drawdown, turnover, 252-session annualized volatility, and zero-reference-rate Sharpe ratio;
- cash return and per-symbol continuous-underlying return from first bar open to last bar close before costs;
- fill count, completed FIFO round trips, winning, losing, and flat round trips;
- average and median holding duration;
- fills and round trips per session, sessions in range, sessions traded, and percentage traded;
- average and maximum gross and net exposure;
- P&L by symbol;
- positive-profit concentration in the best trade, best session, best five trades, and best symbol;
- commission, slippage, and total cost paid;
- configured execution delay and its resulting return;
- final positions, per-session overnight-position violations, outside-session fills, and early-close coverage.

Risk-adjusted metrics use the final New York equity point from each session and 252 sessions per year. A small sample can produce undefined Sharpe, holding-duration, or concentration values. The report retains `null` rather than manufacturing confidence. A continuously held benchmark can carry overnight exposure and is labeled separately from the flat intraday strategy.

## Research-only qualification

`intraday-qualification-policy-v1` contains reviewed initial research parameters. They are not financial validation or universal trading standards. The evaluator emits `intraday-qualification-evidence-v1`, lists each gate, source status, threshold, observation, reason, lineage error, and search count, and never creates a composite score.

The current policy checks controlled registry provenance, complete fixed-budget accounting, sample activity, session coverage, drawdown, trade/session/best-five/symbol concentration, flat session boundaries, regular-session fills, early-close evidence, lineage identity, two higher-cost variants, and `+1` and `+2` whole-bar delay variants. Zero scheduled early closes satisfy coverage only after complete XNYS validation; a missing, malformed, fractional, or negative count fails. The assessor loads each report through its experiment ID, verifies completed `controlled-run` status and the stored artifact location and fingerprint, and lists every campaign record, including failures. Missing, failed, rejected, malformed, mismatched, or unaccounted evidence fails the relevant gate. Parameter-neighbor reports can be linked to one frozen parent without selecting a new parameter from validation results.

Assess frozen reports with:

```console
uv run trading-lab experiment assess-intraday \
  --policy config/research/intraday-qualification-policy-v1.json \
  --base BASE_EXPERIMENT_ID \
  --higher-cost increased-cost=INCREASED_EXPERIMENT_ID \
  --higher-cost harsher-cost=HARSHER_EXPERIMENT_ID \
  --whole-bar-delay plus-1-bar=DELAY_1_EXPERIMENT_ID \
  --whole-bar-delay plus-2-bars=DELAY_2_EXPERIMENT_ID
```

The CLI requires an explicit policy path and verifies its content against the committed v1 policy fingerprint; callers cannot substitute thresholds at assessment time. The result is a content-addressed research artifact. It cannot authorize or inspect a holdout, create paper authority, or call a broker.

## First campaign preregistration

`intraday-research-campaign-plan-v1` freezes the first real campaign's reviewed M5B foundation reference, exact XNYS ranges, fixed strategies, costs, delays, qualification policy, search budget, and candidate ordinals before any result is observed. The reference is not proof of the source that would execute the campaign. The strict loader fingerprints the plan and rejects changed fields, reordered roles, parameter neighbors, or any holdout, paper, broker-write, or live authority. `experiment inspect-intraday-plan` validates the file without creating runtime state. `experiment plan-intraday` atomically stores the sealed plan in the registry. The sealed campaign rejects caller-defined `run-intraday` candidates.

Campaign `intraday-research-v1` reserves 60 candidates: three fixed strategies across one training and three chronological validation periods, with base, increased-cost, harsher-cost, `+1`-bar, and `+2`-bar variants for every strategy-period pair. `experiment plan-intraday` creates all 60 pending reservation records in the plan-sealing transaction. `experiment bind-intraday-datasets` takes the four explicit dataset IDs, fully validates every immutable artifact, checks the concrete `alpaca-historical-v2` adapter, IEX feed, exact period, and reviewed universe, then binds all 60 specs atomically. Failed preflight or binding leaves every reservation pending and unbound.

Campaign V1 execution uses a separate source review. The assessment verifies the main-only GitHub-attested application wheel and exact non-editable install, binds the canonical GitHub CLI path and SHA-256 used for both attestation checks, requires its file and every install-path ancestor to be owned by another trusted account and non-writable by the execution account, verifies the fixed `uv.lock` and one lock-hashed wheel and exact installed files for each runtime dependency, and requires a CPython 3.12 standard-library `venv --without-pip` runtime invoked only through the fixed `-I -B -S` bootstrap. It records the runtime's `pyvenv.cfg`, executable symlink chain and bytes, prefixes and `sys.path`, complete base Python tree (including standard library, native libraries, and `libpython`), exact site tree, import-hook identities, timezone and decimal state, and dependency wheels and files. Every assessment validates the current six hook state and loaded module origins against those exact trees; it does not treat later legitimate lazy imports as identity drift. It rejects loader environment variables, `.pth`, `sitecustomize.py`, `usercustomize.py`, cached bytecode, unexpected distributions or paths, unowned site files, symlinks, special files, changed hooks, and a changed attestation-verifier path or hash.

The wheel-bound `intraday_campaign_v1_surface.json` manifest covers every `.py` file in the application package (48 modules). It classifies each as foundation-exact, an exact reviewed delta, or a reviewed new file. It compares exact bytes without AST normalization. Added, missing, or mutated modules fail and require Campaign V2. The manifest is part of the wheel but is inert: no verifier proves its own bytes or classification. A human must review the full main-attested source commit and wheel and assess the resulting fingerprint before it is recorded. The runner requires the concrete registry and dataset service to share one storage root with reports, fixes initial cash at the foundation's `100000`, and constructs the exact cost model from the stored sealed spec. One explicit assessment fingerprint may be recorded only while all 60 candidates remain pending. `experiment run-planned-intraday` reassesses the runtime, atomically inserts the per-candidate binding and claims the candidate before data access, then reassesses again before report publication. Any review, build, environment, or surface mismatch fails closed; a surface mismatch requires a new campaign version. See [the campaign preregistration](research-campaigns/intraday-campaign-v1.md).

## Deferred work

M5B does not run broad parameter search, autonomous strategy generation, opening-range breakout, protected intraday holdout evaluation, paper execution, options, shorting, leverage, extended hours, tick replay, or market-microstructure simulation. Campaign V1 is technically ready for dataset acquisition and binding only after merge. Its first candidate still needs a main-attested wheel, clean non-writable runtime, explicit human source and assessment review, independent read-only historical credentials, and four exact validated and bound datasets. A later review must approve any holdout policy and separately build M5C market-data, risk, order, reconciliation, operational, and authority controls.
