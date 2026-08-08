# Intraday backtesting foundation

Intraday replay reuses `BacktestEngine` with an explicit `1m` or `5m` timeframe. This is offline bar replay, not a market-microstructure simulator and not paper execution.

## Point-in-time sequence

For each symbol and bar:

1. A pending order may fill at the current bar open if that open is not earlier than its eligible fill time.
2. The current bar completes and becomes observable at `bar_open + timeframe_duration`.
3. The strategy receives the completed bar and history through that bar.
4. The decision and order creation timestamps equal the observability timestamp.
5. With one-bar delay, the earliest fill is the next same-symbol bar open. Contiguous bars can therefore have equal decision and fill timestamps, but the fill never precedes bar completion or order creation.

A signal from the `10:00–10:05` bar cannot use its `10:00` open or any earlier price. Its earliest eligible fill is the `10:05` open. Additional delay is an integer number of same-symbol bars. The final signal is rejected when no eligible future bar exists.

Portfolio strategies receive one complete multi-symbol timestamp slice and immutable history through that completed slice. Invalid target sets fail atomically. Position reductions execute before buys. Long-only weights remain between zero and one, total target weight cannot exceed one, leverage and shorting remain unsupported.

## Day-trading session policy

`XNYS-regular-session-flat-v1` is the explicit flat-at-close replay policy. It treats the last validated bar open in each `America/New_York` session as the final eligible fill. An order cannot cross into the next session.

The engine creates a mandatory zero-weight target early enough for the configured whole-bar delay to fill at that final bar open. This intent uses only bars completed by its decision time. It cancels a pending order and rejects a new positive target when either could leave exposure after the final fill. The engine then fails if any symbol, complete portfolio slice, or pending order remains exposed after the session. The same rule derives normal and early closes from the validated dataset.

The default replay remains a generic diagnostic that may carry positions. A strategy classified as day trading must use `XNYS-regular-session-flat-v1`. The M5B controlled runner enforces that policy for its fixed baselines.

## Costs and metrics

The existing versioned basis-point slippage and commission model applies at the eligible bar open. Higher fixed costs cannot improve the same trade sequence. Bar-open fills do not model queue position, spread paths inside a bar, partial fills, market impact, halts, or quote latency.

Intraday equity evidence retains every completed bar. Summary return, drawdown, volatility, Sharpe ratio, exposure, and profit concentration use the last equity point in each `America/New_York` trading date, preserving the existing 252-session annualization convention. These reports are research diagnostics only.

## M5B research boundary

M5B adds `intraday-experiment-v1`, `intraday-backtest-report-v1`, fixed cash, previous-bar momentum, and moving-average trend baselines, plus research-only `intraday-qualification-policy-v1`. See [intraday-research.md](intraday-research.md) for provenance, metrics, benchmark, robustness, and CLI details.

Daily campaign plans, daily report v2 qualification, protected holdout authorization, paper intents, risk admission, and broker adapters remain unchanged and daily-only. No intraday replay or research-gate result promotes a strategy or grants holdout, paper, broker-write, or live authority.
