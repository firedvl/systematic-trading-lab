# Intraday Relative-Volume Drift 001 program

Status: prospective plan and implementation reviewed before strategy execution or results. Exact-main
launch control remains pending. No market data or strategy result has been read under this campaign.

Program ID: `intraday-relative-volume-drift-001`.

Plan SHA-256: `bc3731b5976fbf7ddb39d275a373ddec7a0678daefbbd1e745a0b0504833b518`.
Plan fingerprint: `699a41c4cf6dd38826361b9b7ad35cfb2869a5e59e73f0983bf27fbf9a63e111`.

Independent-review SHA-256:
`c934369f1cdebeb99613a0ea0e5396c30ff5771c7ee2d92b380d4ca92b5a5611`.
Review fingerprint: `0fb04bfd40cd028355dd8bf4594093cb5bb0707945eeebf867cccab51d994946`.

Source state revision 3 SHA-256/fingerprint:
`7d35eeaf7f079033d1ce2f396088754ce5de22f829c88e3a884757672feef6a2` /
`7f35e0876c2398589b37b7a34d924e3a7a2d588f86f16102c5f2f4080b20d81e`.

Reviewed state revision 4 SHA-256/fingerprint:
`6aa4f195b408e037dd11333f79d9f1b829ea01c12ac233b5b781866eb9ff1551` /
`69d8e113bea81e9bde27b34c3cf7909eea2cafed743a7238823e5a627ae3ff0b`.

Starting main: `6fedd1acfce45758c75d93b6425873c74b4be5cb`.

## Frozen hypothesis and strategy

Campaign 2 tests whether broad positive early price action with unusual joint participation continues
over a fixed multi-hour hold on ordinary XNYS sessions. After `8`, `16`, or `24` aligned completed
five-minute bars, both SPY and QQQ must have returned at least `15` basis points from the session
open. Each symbol's cumulative volume must also be at least `1.2`, `1.5`, or `2` times its causal
same-clock baseline. The nine axis combinations form twelve symmetric undirected neighbor edges.

For each symbol and horizon, the baseline is the exact median of the same cumulative prefix from the
ten most recent strictly prior complete sessions. The even-count median averages the fifth and sixth
sorted integer sums. The baseline must be positive. A zero current cumulative volume is valid but
produces relative volume zero. The current session, later current-session bars, and future sessions
never enter the estimator.

An active decision targets SPY and QQQ at `0.5` each. Scenario delay fills both symbols together at
the next, second-next, or third-next eligible open. The exit decision remains fixed and produces
exactly 24 five-minute holding intervals under every delay. Each active session has two entries, two
exits, two completed round trips, no resize, and no reentry.

This is not an opening-range breakout, VWAP rule, current-versus-recent-bar volume filter, pullback,
event strategy, relative rank, or reuse of the prior volume-filtered breakout parameters. Campaign 1
results did not select or alter its axes, fixed terms, gates, or budget.

## Chronology and session eligibility

The campaign owns five periods: 87 discovery sessions followed by folds of 41, 39, 43, and 20
sessions. Discovery begins without earlier permitted data, so its first ten complete sessions are
lookback-ineligible and remain flat while seeding later baselines. Each later fold has exactly ten
context-only prior sessions. Context sessions never enter P&L, fees, benchmarks, activity, or gates.

Maximum-delay hold capacity is checked before the signal and applied to every scenario. A candidate
with horizon `h` requires bar index `h+26`. Horizon 8 can trade on normal and early-close sessions;
horizons 16 and 24 remain flat on early closes. The hold never shortens. This rule keeps signal
traces identical across Normal, zero-cost, stress, and delay scenarios.

The plan binds the four existing read-only SPY/QQQ IEX five-minute datasets through
`2026-05-29T19:55:00Z`, the calibrated cost model, completed-bar decisions, next-open fills, and
flat-at-close safeguards. No acquisition is allowed.

## Reporting, screens, and budget

Every evaluated session records one of five ordered dispositions: lookback-ineligible,
hold-capacity-ineligible, inactive-joint-return, inactive-joint-relative-volume, or active. Reports
retain both symbol returns, both cumulative-volume baselines and ratios, predicate results,
participation strength and bucket, synchronized decisions and fills, fees, friction, and reconciled
P&L. Inactive and ineligible sessions have no orders, fills, fees, friction, or P&L.

Canonical reports store Decimal metrics as strings. The runner must strictly decode only JSON
integers, semantically valid nulls, and canonical finite Decimal strings before every discovery,
walk-forward, stress, neighbor, and ranking operation. Floats, booleans, whitespace, exponent forms,
noncanonical strings, missing keys, and silent omissions fail. Terminal validation must recompute all
reached-stage gates and verify report, screening-ledger, and cohort identity before interpretation.

| Stage | Maximum specifications |
| --- | ---: |
| Discovery: 9 candidates × Normal/zero-cost | 18 |
| Walk-forward: cap 3 × 4 folds × Normal/zero-cost | 24 |
| Stress/delay: cap 1 × 4 folds × 4 scenarios | 16 |
| Up to 4 immediate neighbors × 4 folds × Normal/zero-cost | 32 |
| Total | 90 |

Run identity is exactly candidate, period, and scenario. Neighbor screening reuses identical
completed rows. Campaign 1's unused 72 specifications cannot transfer. Three infrastructure
attempts permit at most 270 append-only attempts; only an expired no-result lease can retry.

Discovery, walk-forward, stress, delay, and every applicable neighbor must pass the exact frozen
activity, return, gross-edge, cost, drawdown, concentration, accounting, and trace gates. One
all-gate survivor freezes and stops the autonomous program while waiting for future untouched data.
An empty cohort closes and advances only to predeclared Campaign 3 without adaptation.

## Review and implementation boundary

Independent review revalidated the exact plan bytes and fingerprint, all program, state, dependency,
and exposed-evidence bindings, prior-only estimator, early-close and delay semantics, graph, gates,
budget, canonical numeric decoding, terminal validation, protected boundaries, and false authorities.
It found no issue.

Immutable state revision 4 binds revision 3, this exact plan, and its review while preserving
Campaign 1 terminal evidence and accounting. The strict loader verifies all four artifacts, every
dependency and exposed-evidence hash, campaign mechanics, candidate graph, chronology, budget, and
state chain without reading market data.

The separate implementation branch adds the strategy, runner, report, CLI, launch-disabled binding,
and focused tests. The runner enforces causal ten-session same-clock baselines, exact two-symbol
entry and exit timing, strict canonical numeric reloads, stage ceilings, complete accounting, and
independent terminal-screen recomputation. Synthetic one-worker/four-worker reports are byte-equal.
Independent implementation review found and then verified the fix for noncanonical Decimal strings;
its final review has no findings.

Exact merged main must next pass all repository gates and fresh synthetic equivalence before a
separate finding-free launch-control review binds it. Until that later artifact and binding merge,
construction fails before runtime creation, reservation, market-data read, or result.

June, Intraday V3, daily 2018–2019, protected results, PAPER or broker state,
`strategic-allocation-21`, credentials, and live data remain prohibited. Every authority field is
false. Historical simulation cannot establish future profitability or trading authority.
