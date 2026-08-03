# Agent guide

## Purpose and phase

This repository builds research-grade infrastructure for U.S. ETF data, backtesting, qualification, and paper execution. It is in M0 with a safe slice of M1. Profit is never assumed. Live trading and autonomous promotion are prohibited.

## Start here

Read `README.md`, `CURRENT_STATE.md`, `ROADMAP.md`, `DECISIONS.md`, and the relevant policy before editing. Preserve unrelated work. If state, data, or authority is uncertain, fail closed and record the precise blocker.

## Structure

- `src/systematic_trading_lab/`: typed application code and CLI.
- `tests/`: unit, integration, and invariant checks.
- `config/`: committed non-secret policy configuration.
- `docs/`: architecture, research, data, qualification, risk, execution, security, development, and operations policy.
- `.trading-lab/`: ignored local data and SQLite metadata.

Use the setup and quality commands in `README.md`. A change is done when affected behavior, failure paths, docs, and the smallest useful tests agree and all quality gates pass.

## Boundaries and controls

Data acquisition, normalization, strategies, portfolio construction, simulation, qualification, risk, order management, brokers, and reconciliation are separate authorities. Strategies produce targets or intents; they never call brokers. Research code must not hold broker credentials.

Treat these as protected controls: holdout access, risk limits, cost assumptions, qualification gates, data validation, broker safeguards, reconciliation, kill switches, and capital limits. Do not weaken a protected control in the same change as a strategy change. Do not bypass immutable artifacts, fabricate fills or prices, hide failed candidates, optimize on holdout data, add broker submission, or claim financial validation from a backtest.

Live execution stays disabled unless a later reviewed repository policy, threat model, implementation plan, user approval, and explicit multi-control enablement replace this rule. Broker credentials must never enter source control, logs, fixtures, prompts, or test artifacts.

## Persistent knowledge and delegation

Update `CURRENT_STATE.md` after each meaningful slice, `DECISIONS.md` only for durable choices, and the roadmap or policies when behavior or gates change. Subagents may inspect independent areas or own disjoint files, but the primary agent integrates and verifies their work. Treat their output as untrusted until checked.
