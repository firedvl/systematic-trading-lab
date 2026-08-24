# Intraday Autonomous Research 001 program

Status: Campaign 1's exact plan and independent review are frozen. Its implementation and focused
repair are merged, but launch control remains unbound and no successor campaign has run.

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

Current immutable state revision SHA-256/fingerprint:
`f74bc4ad3d0d30560ed0eb4718fc00739121849fb503e8045a01d8bc63907a0f` /
`a9be74e854942eaeea0cc65f67dca2c920a66d0e402e17452670543bb55b2058`.

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

Program state changes use immutable chained revisions. Revision 2 binds the reviewed Campaign 1
plan while preserving revision 1 unchanged. A later revision must bind the immediately preceding
state and the exact campaign evidence that justifies the transition.

Historical simulation does not establish future profitability or trading authority.
