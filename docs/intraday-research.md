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

`intraday-backtest-report-v1` is deterministic and self-contained. It binds the full experiment provenance, replay artifact fingerprint, and report fingerprint. Source-reviewed campaign reports retain the sealed foundation reference in experiment provenance and add separate immutable execution-source review and per-candidate binding evidence. Qualification checks that evidence against the registry. It records failed runs in the registry and reports zero-trade runs without dropping them.

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

## Campaign succession and provenance

`intraday-research-campaign-plan-v1` freezes a campaign's reviewed foundation reference, exact XNYS ranges, fixed strategies, costs, delays, qualification policy, search budget, and candidate ordinals before any result is observed. The reference is not proof of the source that would execute the campaign. The strict loader accepts only the closed V1 and V2 identities and rejects changed fields, reordered roles, parameter neighbors, or any holdout, paper, broker-write, or live authority. `experiment inspect-intraday-plan` validates either file without creating runtime state. The registry reserves both campaign IDs against caller-defined `run-intraday` candidates.

Campaign V1 was preregistered and its source review was recorded, but its first real Training acquisition exposed the extended-hours filtering defect before dataset publication. Dataset validation rejected 2,758 out-of-session records with no missing intervals and no duplicates. No candidate ran and no strategy result was observed. V1's sealed plan, stored review, runtime state, and quarantine evidence remain unchanged and readable. New V1 sealing, dataset binding, source review, and execution are blocked.

Campaign V2 carried forward the same 60-candidate matrix under plan fingerprint `52db8a27fa4ff86865ab69b6bd7456899329ef3b861a582e59ab32904c03c122`. Its planner created all reservations atomically, and its dataset binder fully validated four immutable artifacts before binding all 60 specs. V2 completed 60/60 candidates and failed 12/12 base research qualification groups.

V2 used a separate execution-source review. The assessment verified the main-only GitHub-attested application wheel and exact non-editable install, bound the canonical trusted `gh` path and SHA-256, verified the fixed `uv.lock` plus exact dependency wheel and installed-file closure, and required the isolated CPython 3.12 `-I -B -S` runtime. The immutable wheel-bound `intraday_campaign_v2_surface.json` manifest covers the 49 application-package Python modules in the reviewed V2 source by exact hash, including the corrected provider. The runner fixed initial cash at `100000`, derived costs from the stored spec, bound a fresh matching assessment to each claim, and reassessed before report publication. See [the V1 disposition](research-campaigns/intraday-campaign-v1.md), [the V2 historical runbook](research-campaigns/intraday-campaign-v2.md), and [the V2 postmortem](research-campaigns/intraday-campaign-v2-postmortem.md).

## Campaign V2 closeout and V3 development

Campaign V2 completed all 60 controlled candidates and failed all 12 base research qualification
groups. It remains closed immutable failed evidence. No intraday holdout was accessed or authorized,
and no paper, broker-write, or live authority exists. The confirmed postmortem mechanism is repeated
exact-weight scheduling: unchanged 0.5 targets caused drift-driven rebalances, while longer pending
orders suppressed later target applications and confounded the delay stress. See
[the V2 postmortem](research-campaigns/intraday-campaign-v2-postmortem.md).

The development-only V3 foundation adds separate `intraday-experiment-v2`,
`intraday-backtest-report-v2`, `state-transition-delayed-fifo-v1`, and
`XNYS-regular-session-state-transition-flat-v2` contracts. It includes fixed event-driven 12-bar MA,
six-bar momentum, and six-bar opening-range breakout strategies. It also emits a fingerprinted paired
realistic/zero-cost diagnostic. The V3-only qualification binding retains every v1 threshold, reads
only `realistic.metrics`, requires exact five-role lineage and complete 60-candidate registry
accounting, and keeps the zero-cost result diagnostic-only. It grants no authority and has no
controlled V3 reports to assess.

The final V3 plan fixes 60 candidates: three strategies, four periods, and five cost/delay variants.
Its fingerprint is `5e81cf8f0db1143f293a0f93900f1e797718443a559c1caaaa2e986851d5241a`.
Training reuses the exposed V2 window. Validation A/B/C are three chronological 45-session forward
blocks from 2026-10-01 through 2027-04-15. Unknown historical state still prevents a universal
freshness claim, but it cannot contain market bars that did not yet exist. The narrower prospective
property requires no known overlap, no selected-period data in the design, immutable dates and
parameters, and a GitHub/main attestation of the exact selection and plan before Validation A's first
bar. See [the V3 plan](research-campaigns/intraday-campaign-v3-draft.md) and
[exposure inventory](research-campaigns/intraday-exposure-inventory.md).

On each main push, the provenance workflow builds the whole-package surface, wheel, runtime manifest,
and preregistration seal. The seal binds the inventory, selection, plan, qualification binding,
source commit, first validation bar, and false authorities. Verification requires the exact
repository, main ref, signer workflow, source commit, seal digest, trusted `gh` identity, and a
verified Sigstore transparency-log timestamp before `2026-10-01T13:30:00Z`. Commit dates, file mtimes,
local clocks, the author-recorded selection date, and caller-entered timestamps are not trusted. The
verified transparency-log timestamp is the sole effective selection cutoff. The artifact
preassessment remains non-authoritative until a human records the campaign-bound review.

The V3 registry owns only `intraday_v3_*` tables. Its materialization boundary verifies the attested
seal and trusted timestamp before atomically storing the exact seal bytes, plan, and 60 pending
reservations. Adding the plan file alone creates no state. Dataset binding resolves four IDs through
the shared catalog and fully validates all raw and normalized artifacts before one transaction binds
the role datasets and 60 stored specs. Source review reruns the fixed artifact assessment and requires
the explicitly reviewed fingerprint. The runner accepts only a candidate ID, one storage root, and
the fixed source artifacts. It derives the review, spec, dataset, costs, dates, delay, cash, and report
path from stored state, reverifies source before compute and publication, and terminally fails only an
invocation that acquired the claim. Running candidates heartbeat. Publication commits a canonical
report intent before its create-only final file and completion; stale recovery takes that intent's
ownership or records failure when no intent exists, and completed intents can restore a missing file.
Registered qualification reads its five roles from the immutable stored plan. Candidate 1 cannot run
before Validation C completes at `2027-04-15T20:00:00Z`, and then only after the four-dataset bind and
source review.

## Deferred work

M5B does not run broad parameter search, autonomous strategy generation, protected intraday holdout
evaluation, paper execution, options, shorting, leverage, extended hours, tick replay, or
market-microstructure simulation. V3 still needs the post-merge pre-bar GitHub attestation, explicit
runtime materialization, four independently acquired and validated datasets, a human source review,
and the end of Validation C before any candidate. Caller-configured V1 runs remain separate V1
evidence; using selected validation dates before the trusted seal would invalidate this campaign. A
later review must approve any holdout policy and separately build M5C market-data, risk, order,
reconciliation, operational, and authority controls.
