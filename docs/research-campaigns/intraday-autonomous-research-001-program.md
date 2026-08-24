# Intraday Autonomous Research 001 program

Status: Campaigns 1 and 2 are terminal with independently reviewed empty cohorts. Immutable state
revision 5 permits prospective planning for Campaign 3, the program's final campaign. Campaign 4
remains prohibited.

Program ID: `intraday-autonomous-research-001`.

Plan: `config/research/intraday-autonomous-research-001-program-v1.json`.

Plan fingerprint: `734282e42b991889aa2dbce220b46807debe0114309e93cf4ca8d89bf0d0c14f`.

Independent review: `config/research/intraday-autonomous-research-001-program-independent-review-v1.json`.

Review fingerprint: `50424b9e5c07a95351af93e560859293768e34959d01f816f0f63042302497c0`.

Starting main: `8db080d51971d360c3d3a979664c23cdc144abfa`.

Campaign 1 plan SHA-256/fingerprint:
`1a02410da60f9dc90e2408e46e4dad88fe9ab9ec248ad8cb035f26734dc78b92` /
`177fad36b3911b89a4938cdfe130a6eda81d22bd1d19e448ab7d11b46326a51a`.

Campaign 1 review SHA-256/fingerprint:
`71b60c8d4b900bb4ad1cb8c737fe26927b0365c7314aff5d64c688ffea6b6a07` /
`b0f14d7fe31f509300b1f5bedce4dcf6b94edba476efc8ed0b9f9fea351fe5d6`.

Campaign 2 plan SHA-256/fingerprint:
`bc3731b5976fbf7ddb39d275a373ddec7a0678daefbbd1e745a0b0504833b518` /
`699a41c4cf6dd38826361b9b7ad35cfb2869a5e59e73f0983bf27fbf9a63e111`.

Campaign 2 review SHA-256/fingerprint:
`c934369f1cdebeb99613a0ea0e5396c30ff5771c7ee2d92b380d4ca92b5a5611` /
`0fb04bfd40cd028355dd8bf4594093cb5bb0707945eeebf867cccab51d994946`.

Campaign 1 launch-control SHA-256/fingerprint:
`26d1ef10abb3b2ef063dec1bc5931b0c667c2698bc983c7c9e3a3e58ca01e863` /
`b69466bfe3ed67d8e539a6e772341f2fbb7a7bddcdefa4bcee04e336c73c446e`.

Campaign 2 reviewed implementation main:
`b9efc2c7a4a022177d72935821c3cb0e7b46c598`.

Campaign 2 launch-control SHA-256/fingerprint:
`51159d51aff6b11b9fee9c5c5bacfa3ac3ceaa93c17259b493aeb794d0b5e655` /
`3b6c46f924ab94557f5235bf26650c1b8bf6f836b0f55bb590e63c1bba86717f`.

Current immutable state revision SHA-256/fingerprint:
`cd68f08b0b95839d41672a5df024e8867759911830f28d0a3d255c61c2643883` /
`c6eaa1acc6af58af2d0f4a937c89ad95690ee8743ec998526b5f16ebdf7ea9af`.

## Campaign 1 disposition

The four-worker Campaign 1 launch from source main
`a8093f24fba142c2817311bbd3c30656b981b15c` completed all 18 discovery specifications once. It
had no failure, retry, pending row, running row, active lease, or later-stage run.

Post-campaign audit found a screening defect: canonical JSON stored `Decimal` metrics as strings,
but the historical discovery screen kept only `Decimal`, integer, or null values. The runtime
database, final report, and final freeze remain unchanged. Their SHA-256 values are
`fca67d95832a6fad87f29ef68ce56238a0f9d8d2e02e8d331aece63e4e9e8908`,
`d44f9390db7f8882f7375afbfd40607ce51d89d6a7537431e01c9cfd9b6b6608`, and
`62c2301cde8e72d80f39159b3d38da156e92801afdd70e554356b806cac37d2c`.

The isolated read-only reassessment has SHA-256/fingerprint
`597d7229e1a4a9616fbe418c12b6ad8053cd2ca0f3bae538184ec428b8a50cad` /
`a06e1c83980f6968dba678fb4a0b71b25f73f542e58d01c09ee5144e89b60e6f`. Its independent review
has SHA-256/fingerprint `8e45148b7711c667dcc1f4190d2820e28632e0f6c0435d36af86b1f43cf83a0e` /
`ddaf06bfb1121dd194d99d20d8c29a48787f320dfebeb33d5fe8b0f67cade7a9` and no findings.
Corrected Normal active-session counts are `3, 1, 0, 0, 0, 0, 2, 1, 0`; every parent fails the
frozen minimum of 12 and the paired round-trip gate. The empty cohort and zero later-stage
disposition therefore remain valid.

Campaign 1 consumed 18 specifications. The program has 252 units of numerical headroom, but only
the 180 specifications reserved for Campaigns 2 and 3 remain usable. Campaign 1's unused 72 cannot
transfer.

## Campaign 2 disposition

Campaign 2 fixes `8/16/24` completed-bar horizons, joint relative-volume floors `1.2/1.5/2`, a
15-basis-point return floor for both symbols, and the exact median of the same cumulative-volume
prefix from ten strictly prior complete sessions. An active session targets SPY and QQQ at `0.5`
each for one fixed 24-bar hold with no resize or reentry.

Maximum-delay hold capacity is applied before the signal in every scenario. Horizon 8 can trade on
early closes; horizons 16 and 24 remain flat. Reports must strictly decode canonical Decimal strings
before all screens and must recompute reached-stage gates and cohort identity at terminal validation.
The campaign remains capped at 90 specifications and 270 attempts.

Independent review revalidated the exact bytes, causal estimator, chronology, graph, gates, budget,
state and dependency bindings, non-adaptation rule, protected boundaries, and false authorities. It
found no issue. State revision 4 binds revision 3, the plan, and its review while preserving Campaign
1 terminal evidence.

Implementation main contains the campaign-owned strategy, runner, reports, CLI, binding, and focused
tests. It uses the existing engine, attempt store, executor, cost model, and frozen data plumbing
unchanged. It strictly validates canonical Decimal strings at every screen, enforces the
`18/24/16/32` stage ceilings, and rebuilds every reached gate and the final cohort from canonical
reports. Independent implementation and exact-main launch reviews closed with no findings.

The exact four-worker launch from source main `551c891585c176016e9f98a20586957d1bfdca61`
completed all 18 discovery specifications on attempt 1, with zero failure, retry, pending row,
running row, active lease, or later-stage run. Four parents had positive Normal and zero-cost
returns, but every parent failed the frozen 12-session, 24-round-trip, and participation-bucket
concentration gates. The strongest row returned `0.878023%` under Normal costs with `15.106` gross
basis points per trade, but it activated six sessions and concentrated all positive profit in one
participation bucket. The cohort froze empty.

Runtime database, final-report, and final-freeze SHA-256 values are
`8d9fb50dd25f022ed69580bdc90201c47e05e7bf730d84900de04030217a200a`,
`7c271ace238d0871a0654edc790ff301ce9600e64b2765baaea4dc2ac4be0ade`, and
`fda9aa99ff0b456419c5d90205dc890bc612ee43974aac24a33eedf67d8f7f30`.
Postmortem SHA-256/fingerprint is
`e1bb5f7dc8a3353219c3a9a0c93dec62938c314b1281a4eca34e37ad7b13c638` /
`5738b8bc93fb9fa24e086651bf673ed35b83232450e1e171795723b29cd65d56`.
Independent review SHA-256/fingerprint is
`21e83c4c180e160ad7760bde12089b6a167c01154b2ad890e824a22eb7ea4fc9` /
`6b2b632e298a1faaa86b01667d97bd7124b2c1b6f9dc0f2239232272a33c61b0` and has no findings.
Campaign 2 consumed 18 specifications. Its unused 72 cannot transfer.

## Purpose and bound

The program permits three successor campaigns in one fixed order and no fourth campaign. Each may
reserve at most 90 immutable run specifications; the global maximum is 270. Infrastructure recovery
may use at most three append-only attempts for the same immutable run, but retries do not add search
specifications.

The order is:

1. `intraday-spy-qqq-lead-lag-001`: fixed early-session SPY price discovery followed by a possible
   QQQ catch-up.
2. `intraday-relative-volume-drift-001`: joint positive early price action with unusual same-clock
   cumulative volume relative to prior complete sessions.
3. `intraday-fed-policy-absorption-001`: late-session continuation after an official 14:00 New York
   Federal Reserve policy statement or meeting-minutes publication.

These mechanisms do not reopen the closed high-turnover, breakout, pullback, gap, relative-rank, or
BLS-event candidates. Campaign 2 cannot use an opening-range or VWAP rule. Campaign 3 cannot inspect
release contents or decision values.

## Shared evidence and controls

All price and volume work uses the four exact read-only SPY/QQQ five-minute datasets already bound
through May 29, 2026. June, Intraday V3, daily 2018–2019, protected results, PAPER or broker state,
`strategic-allocation-21`, and live data remain prohibited. Campaign 3 may add only hashed official
Federal Reserve date-and-time metadata frozen before any strategy reservation.

Each campaign must separately freeze and pass independent review of its exact causal contract,
nine-parent maximum grid, symmetric neighbors, chronology, costs, gates, 90-spec budget, cohort
rule, false authorities, and protected boundaries before implementation. Runs use completed bars,
state changes only, one entry per symbol per session, no leverage, flat-at-close execution, the
frozen calibrated cost model, `research-attempts-v1`, and four spawned workers by default.

## Transition and stop rules

An empty terminal campaign advances to the next predeclared mechanism only after terminal validation
and independent audit. Its results cannot change the next campaign. A nonempty all-gate exposed
cohort freezes simultaneously and stops the program while waiting for future untouched data. A
post-observation semantic defect, protected-boundary issue, or authority escalation stops the
program for review.

If all three campaigns close empty, the program is exhausted. The closeout must synthesize common
gate failures and decide whether the SPY/QQQ five-minute domain is exhausted. It cannot invent
Campaign 4.

Program state changes use immutable chained revisions. Revision 5 binds revision 4, Campaign 2's
exact runtime database, final report, final freeze, postmortem, independent review, and 18 newly
consumed specifications. Across Campaigns 1 and 2, 36 specifications are consumed. Only the 90
specifications reserved for Campaign 3 remain usable. Campaign 3 must bind revision 5 and pass its
own prospective plan review before implementation, reservation, market-data read, or result.

Historical simulation does not establish future profitability or trading authority.
