# Qualification policy

Qualification is a set of visible gates, not a single score. It will cover out-of-sample and walk-forward stability, periods and instruments, drawdown, turnover, exposure, trade count, parameter and cost sensitivity, delayed execution, missing data, regimes, profit concentration, benchmarks, and search volume.

Thresholds remain unapproved until a reviewed milestone sets them. The gate evaluator marks any report containing an unapproved threshold as `unapproved`, never qualified. Missing or invalid metrics fail their gates, and disqualifying failures reject the experiment. Failed experiments cannot qualify. Holdout metrics remain hidden until a completed holdout receives an explicit logged qualification event. A change that lowers a gate requires its own review and evidence.

Financial thresholds are explicitly deferred in this milestone. No threshold is approved by the catalog-backed campaign runner.

Cost and delayed-fill sensitivity results remain separate candidates and cannot alter qualification thresholds. Candidate comparisons show each metric, failure, and missing result directly; they do not rank candidates with a composite score.

Report schema v2 calculates qualification metrics from the last equity point in each completed session; the detailed per-symbol ledger remains unchanged. Annualized volatility and the Sharpe ratio use 252 sessions and a zero reference rate. Gross exposure is long market value divided by equity. Period concentration is the share of all positive session profit supplied by the five largest positive sessions. Instrument concentration is the largest positive instrument profit divided by total positive instrument profit after fills and commissions. SPY close-to-close returns classify up and down sessions; strategy returns are compounded separately within each class.

Parameter-neighborhood runs are separate validation candidates linked to the base candidate. They consume campaign budget and may reveal fragility, but they cannot select a new parameter from validation results. Missing regime classes or undefined risk and concentration values fail any gate that requires them.
