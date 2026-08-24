# Intraday Relative-Volume Drift 001 program

Status: terminal exposed research. The exact four-worker launch from source main
`551c891585c176016e9f98a20586957d1bfdca61` completed once and froze an empty cohort. Independent
terminal and exact-postmortem review found no issue. Do not rerun, retune, rescue, or reinterpret
this campaign.

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

Reviewed implementation main: `b9efc2c7a4a022177d72935821c3cb0e7b46c598`.

Launch-control SHA-256/fingerprint:
`51159d51aff6b11b9fee9c5c5bacfa3ac3ceaa93c17259b493aeb794d0b5e655` /
`3b6c46f924ab94557f5235bf26650c1b8bf6f836b0f55bb590e63c1bba86717f`.

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

Implementation main adds the strategy, runner, report, CLI, launch-disabled binding, and focused
tests. The runner enforces causal ten-session same-clock baselines, exact two-symbol
entry and exit timing, strict canonical numeric reloads, stage ceilings, complete accounting, and
independent terminal-screen recomputation. Synthetic one-worker/four-worker reports are byte-equal.
Independent implementation review found and then verified the fix for noncanonical Decimal strings;
its final review has no findings.

Implementation main passed all seven repository gates, including 1,039 tests with four skips. Fresh
synthetic equivalence produced byte-identical canonical reports for four fixtures: one worker took
`13.477235` seconds and four workers took `4.147198` seconds, a `3.249721` speedup. Independent
launch review found no issue and accessed no protected input. Its exact artifact binds the source,
reviewed inputs, implementation hashes, gates, equivalence evidence, reviewer, scope, and false
authorities.

The launch-control artifact, binding constants, regression test, and durable state merged before
the exact four-worker launch. Clean synchronized main accepted the full binding before runtime
creation, reservation, market-data read, or result.

## Terminal result and postmortem

All 18 discovery specifications completed on attempt 1. No run failed, retried, remained pending,
or retained an active lease. The campaign had 217 heartbeat events. Walk-forward, stress, delay,
and neighbor stages did not open because none of the nine parents passed discovery.

Runtime database SHA-256:
`8d9fb50dd25f022ed69580bdc90201c47e05e7bf730d84900de04030217a200a`.

Final-report SHA-256/fingerprint:
`7c271ace238d0871a0654edc790ff301ce9600e64b2765baaea4dc2ac4be0ade` /
`87d94ce8ce0bc30782e5a4ea3c07375c45cf61baab1d07049860fbabbb283f34`.

Final-freeze SHA-256/fingerprint:
`fda9aa99ff0b456419c5d90205dc890bc612ee43974aac24a33eedf67d8f7f30` /
`3374f9206bf446bb321e1baa0117c867fc325d6e0fa8c992158ca545af57ba1b`.

The 1.2-floor candidates at horizons 8, 16, and 24 produced positive Normal returns. The strongest
row, `irvd001-a02-b01`, returned `0.878023%`, averaged `15.106` gross basis points per trade, and
had a `2.299%` cost-to-gross-profit ratio. It still activated only six sessions, completed 12 round
trips, and concentrated all positive profit in one participation bucket. Every parent failed the
minimum 12 active sessions, 24 round trips, and participation-bucket concentration gates. Friction
reduced positive returns but did not cause the common rejection. Later-stage stability, delay,
stress, neighbor, and regime evidence does not exist and must not be inferred.

Postmortem SHA-256/fingerprint:
`e1bb5f7dc8a3353219c3a9a0c93dec62938c314b1281a4eca34e37ad7b13c638` /
`5738b8bc93fb9fa24e086651bf673ed35b83232450e1e171795723b29cd65d56`.

Independent postmortem-review SHA-256/fingerprint:
`21e83c4c180e160ad7760bde12089b6a167c01154b2ad890e824a22eb7ea4fc9` /
`6b2b632e298a1faaa86b01667d97bd7124b2c1b6f9dc0f2239232272a33c61b0`.

Immutable state revision 5 binds revision 4 and every terminal artifact at SHA-256/fingerprint
`cd68f08b0b95839d41672a5df024e8867759911830f28d0a3d255c61c2643883` /
`c6eaa1acc6af58af2d0f4a937c89ad95690ee8743ec998526b5f16ebdf7ea9af`. Campaign 2 consumed 18
specifications. Campaign 3 is the only remaining campaign and must freeze independently before any
reservation or strategy result. Campaign 4 remains prohibited.

June, Intraday V3, daily 2018–2019, protected results, PAPER or broker state,
`strategic-allocation-21`, credentials, and live data remain prohibited. Every authority field is
false. Historical simulation cannot establish future profitability or trading authority.
