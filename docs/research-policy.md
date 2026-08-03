# Research policy

Official research records every candidate, parameter set, failure, code revision, dataset fingerprint, universe ID and fingerprint, cost and execution model, random seed, data split, and artifact hash. Compare results with cash, SPY, relevant buy-and-hold instruments, a fixed-weight ETF portfolio, and approved baselines after costs and risk.

Create the experiment record before execution, claim it before work begins, heartbeat long runs, and complete or fail it explicitly. Campaign budgets count every created candidate. Recovery marks stale runs failed instead of guessing whether they completed.

Training and validation may guide development. Holdout evaluation is an explicit logged qualification event; once viewed for a decision, that holdout is retired or reclassified. Do not promote from one attractive backtest, hide search volume, optimize foundation baselines, promise profit, or combine a strategy change with weaker qualification controls.

Walk-forward training must end before its validation window begins, and validation windows must be chronological and non-overlapping. Record each fold, cost assumption, and delayed-fill variant as a separate candidate linked to its parent. Comparison reports retain failures and missing metrics and do not calculate a hidden aggregate score. The ordinary runner and comparison APIs reject holdout experiments.

CLI runs use only immutable cataloged datasets that pass integrity validation. Dataset manifests supply the dataset fingerprint and exact universe provenance; callers cannot override them. The command records that provenance, code commit, strategy parameters, cost version, execution version, split, and reason before simulation. It rejects parameters the selected strategy would ignore.
