# Research policy

Research has two tracks:

- **Rapid Research** is exploratory and non-authoritative. It records enough local detail to repeat and compare ordinary backtests, sweeps, chronological walk-forward folds, and stress reruns without preregistration or approval. It uses a separate store, retains valid sweep configurations and runtime failures, reports no hidden score, blocks selected V3 windows, identifiable controlled catalog artifacts, and registered or reserved controlled holdout ranges in its active storage root, and cannot create qualification, holdout, paper, broker-write, live, or automatic-promotion authority. Detached user-supplied files carry no intrinsic catalog provenance; protected bars must not be copied or re-encoded for Rapid use.
- **Controlled research** owns official evidence, qualification, protected holdout access, and later paper-candidate review. The remaining policy applies to this track unless it explicitly names Rapid Research.

Research iteration is cheap; promotion and execution remain strict. A Rapid candidate export is a zero-authority review input, not controlled evidence. Promotion requires a separate human-reviewed controlled plan and untouched evaluation boundary.

Official research records every candidate, parameter set, failure, code revision, dataset fingerprint, universe ID and fingerprint, cost and execution model, random seed, data split, and artifact hash. Compare results with cash, SPY, relevant buy-and-hold instruments, a fixed-weight ETF portfolio, and approved baselines after costs and risk.

Create the experiment record before execution, claim it before work begins, heartbeat long runs, and complete or fail it explicitly. Campaign budgets count every created candidate. Recovery marks stale runs failed instead of guessing whether they completed.

Training and validation may guide development. Holdout evaluation is an explicit logged qualification event; once viewed for a decision, that holdout is retired or reclassified. Do not promote from one attractive backtest, hide search volume, optimize foundation baselines, promise profit, or combine a strategy change with weaker qualification controls.

Qualification proposals must name their evidence campaign, record each gate and rationale separately, and keep approval state machine readable. A proposed-unapproved artifact cannot authorize a holdout run even when all observed metrics pass. Approving or weakening gates requires a separate human-reviewed change; it cannot accompany a strategy or parameter change.

Qualification aggregation must use an explicit evidence manifest and completed registry records. Each source record must come from the controlled research runner and bind exactly one report location to one SHA-256 report fingerprint. Manual completions and historical records without controlled-run provenance remain readable but cannot qualify or authorize holdout access. The manifest assigns each record one reviewable role; the evaluator verifies provenance and parent links before calculating campaign metrics. A report must name every source experiment and bind its content to a fingerprint. Hand-copied summaries may explain results but cannot authorize holdout access.

Rapid-002 adds only two candidate-specific combined-stress roles to this format. Stress A and Stress B must each change both cost and execution model from the same named base record. Their positive-return and return-retention gates remain separate visible results. No other combined-stress role or campaign framework is implied.

Do not create a holdout experiment from a caller-supplied flag. Store a reviewed authorization from approved, passing registry evidence, bind it to the exact candidate and provenance, and consume it once when creating the holdout record. Refused or mismatched attempts must leave the authorization unused. After consumption, load only the authorized timestamp range; any failure remains recorded and leaves the authorization consumed. Do not return holdout results or write them to an ordinary report. Reading completed holdout metrics is a separate one-time reviewed event.

Walk-forward training must end before its validation window begins, and validation windows must be chronological and non-overlapping. Record each fold, cost assumption, and delayed-fill variant as a separate candidate linked to its parent. Comparison reports retain failures and missing metrics and do not calculate a hidden aggregate score. The ordinary runner and comparison APIs reject holdout experiments.

Multi-symbol portfolio research must make one decision from a complete session and history ending at that session. Treat its nonempty target set as one atomic full-universe decision: each session symbol must appear once, each weight must be long-only, and total target weight must not exceed one. Execute reductions before buys at the next eligible open. Do not use symbol processing order to obtain same-session information or allow part of an invalid allocation to trade.

Controlled `experiment` CLI runs use only immutable cataloged datasets and read only the declared training or validation range. Dataset manifests supply the dataset fingerprint and exact universe provenance; callers cannot override them. The command records that provenance, code commit, strategy parameters, cost version, execution version, split, and reason before reading bars. It rejects parameters the selected strategy would ignore.

Future official training campaigns must use a strict `training-campaign-plan-v1` artifact. The
registry stores its canonical content and fingerprint and atomically preregisters the exact candidate
set before execution. The plan budget equals its candidate count; candidate IDs, code revision,
dataset and universe provenance, strategies, parameters, dates, parents, costs, and fill model cannot
change at run time. V1 is training-only and permits the default conservative cost and next-bar models.
Historical unplanned campaigns remain immutable legacy evidence and are not rewritten into plans.

Rapid-002 alone uses `controlled-validation-campaign-plan-v1`. Its materialization command requires
the exact recovered candidate export, a fully valid exact dataset, the committed evidence manifest
and proposal, and a clean checkout at the same commit as local and remote `main`. It atomically
reserves the fixed 28 validation records before any candidate runs. `experiment run-planned` accepts
only a stored experiment ID and derives cash, strategy, parameters, range, data, numeric costs, and
delay from the sealed plan. A completed or failed reservation is terminal. Another daily campaign
needs its own reviewed schema; it cannot reuse or widen this candidate-specific plan.

Closed Campaigns V1/V2 use the separate `intraday-experiment-v1` and `intraday-backtest-report-v1` contracts. Every controlled run binds its timeframe, timestamp semantics, XNYS flat-at-close policy, session-return policy, benchmark policy, cost values, whole-bar delay, fixed campaign budget, and candidate ordinal. Intraday robustness reports remain linked children of one frozen parent. Their exact-weight and pending-order semantics remain unchanged for reproduction.

Campaign V3 uses separate `intraday-experiment-v2` and `intraday-backtest-report-v2` contracts. It records desired state after every completed five-minute slice, queues changed states under `state-transition-delayed-fifo-v1`, and does not rebalance unchanged states. Its paired zero-cost replay is fingerprinted diagnostic evidence, not a qualification input. The final plan fixes three strategies, four periods, five variants, 60 reservations, no parameter neighbors, and false authorities. Committing the plan alone creates no runtime state. The exact GitHub/main seal was attested before Validation A's first bar, so the sealed plan's pre-bar publication requirement passed. The campaign was then materialized with 60 pending reservations. No selected V3 dataset or result has been observed; universal freshness remains unproved, validation approval remains false, and no authority exists. The author-recorded selection date remains descriptive. The verified Sigstore transparency-log timestamp is the effective selection cutoff. The materialization boundary verifies the attestation of the exact inventory, selection, plan, and qualification binding, and the seal paths parse all four artifacts through their shared strict validators. A known overlapping acquisition still blocks sealing after dependent fingerprints change. Missing, late, wrong-ref, wrong-source, caller-constructed, or substituted evidence blocks materialization. The V3-only registry then resolves four dataset IDs through its catalog, requires all four full-integrity datasets in one atomic bind, and reruns the artifact assessment when recording the campaign-bound human source review. Its runner accepts only a candidate ID, one storage root, and fixed source artifacts; it loads the stored spec, owns a private claim token, heartbeats, and reverifies source before compute and publication. The registry first journals the canonical report under that token, then create-only publishes and directory-syncs its exact bytes before committing completion. Stale recovery atomically takes publication ownership; completed reconciliation can restore a missing exact report, while substituted bytes create immutable integrity-conflict evidence that qualification rejects. The V3 qualification binding keeps the unchanged thresholds, reads roles from the immutable stored plan, uses only `realistic.metrics`, verifies exact five-role lineage and all 60 terminal records, and grants no authority. The generic V1 runner remains separate and cannot produce V3 evidence.

`training-campaign-plan-v1`, daily report schema v2 qualification evidence, approved daily gates, holdout authorization, and paper execution remain daily-only.

`intraday-qualification-policy-v1` is research-only. Its result cannot authorize a holdout, paper execution, broker access, or promotion. A separate reviewed change must define and authorize any protected intraday holdout. Normal intraday commands must not inspect protected results.
