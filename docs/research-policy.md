# Research policy

Official research records every candidate, parameter set, failure, code revision, dataset fingerprint, universe ID and fingerprint, cost and execution model, random seed, data split, and artifact hash. Compare results with cash, SPY, relevant buy-and-hold instruments, a fixed-weight ETF portfolio, and approved baselines after costs and risk.

Create the experiment record before execution, claim it before work begins, heartbeat long runs, and complete or fail it explicitly. Campaign budgets count every created candidate. Recovery marks stale runs failed instead of guessing whether they completed.

Training and validation may guide development. Holdout evaluation is an explicit logged qualification event; once viewed for a decision, that holdout is retired or reclassified. Do not promote from one attractive backtest, hide search volume, optimize foundation baselines, promise profit, or combine a strategy change with weaker qualification controls.

Qualification proposals must name their evidence campaign, record each gate and rationale separately, and keep approval state machine readable. A proposed-unapproved artifact cannot authorize a holdout run even when all observed metrics pass. Approving or weakening gates requires a separate human-reviewed change; it cannot accompany a strategy or parameter change.

Qualification aggregation must use an explicit evidence manifest and completed registry records. Each source record must come from the controlled research runner and bind exactly one report location to one SHA-256 report fingerprint. Manual completions and historical records without controlled-run provenance remain readable but cannot qualify or authorize holdout access. The manifest assigns each record one reviewable role; the evaluator verifies provenance and parent links before calculating campaign metrics. A report must name every source experiment and bind its content to a fingerprint. Hand-copied summaries may explain results but cannot authorize holdout access.

Do not create a holdout experiment from a caller-supplied flag. Store a reviewed authorization from approved, passing registry evidence, bind it to the exact candidate and provenance, and consume it once when creating the holdout record. Refused or mismatched attempts must leave the authorization unused. After consumption, load only the authorized timestamp range; any failure remains recorded and leaves the authorization consumed. Do not return holdout results or write them to an ordinary report. Reading completed holdout metrics is a separate one-time reviewed event.

Walk-forward training must end before its validation window begins, and validation windows must be chronological and non-overlapping. Record each fold, cost assumption, and delayed-fill variant as a separate candidate linked to its parent. Comparison reports retain failures and missing metrics and do not calculate a hidden aggregate score. The ordinary runner and comparison APIs reject holdout experiments.

Multi-symbol portfolio research must make one decision from a complete session and history ending at that session. Treat its nonempty target set as one atomic full-universe decision: each session symbol must appear once, each weight must be long-only, and total target weight must not exceed one. Execute reductions before buys at the next eligible open. Do not use symbol processing order to obtain same-session information or allow part of an invalid allocation to trade.

CLI runs use only immutable cataloged datasets and read only the declared training or validation range. Dataset manifests supply the dataset fingerprint and exact universe provenance; callers cannot override them. The command records that provenance, code commit, strategy parameters, cost version, execution version, split, and reason before reading bars. It rejects parameters the selected strategy would ignore.

Future official training campaigns must use a strict `training-campaign-plan-v1` artifact. The
registry stores its canonical content and fingerprint and atomically preregisters the exact candidate
set before execution. The plan budget equals its candidate count; candidate IDs, code revision,
dataset and universe provenance, strategies, parameters, dates, parents, costs, and fill model cannot
change at run time. V1 is training-only and permits the default conservative cost and next-bar models.
Historical unplanned campaigns remain immutable legacy evidence and are not rewritten into plans.
