# Intraday Autonomous Research 001 program

Status: Campaign 1 is terminal with an independently reassessed empty cohort. Campaign 2's
prospective plan is pending.

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

Campaign 1 launch-control SHA-256/fingerprint:
`26d1ef10abb3b2ef063dec1bc5931b0c667c2698bc983c7c9e3a3e58ca01e863` /
`b69466bfe3ed67d8e539a6e772341f2fbb7a7bddcdefa4bcee04e336c73c446e`.

Current immutable state revision SHA-256/fingerprint:
`7d35eeaf7f079033d1ce2f396088754ce5de22f829c88e3a884757672feef6a2` /
`7f35e0876c2398589b37b7a34d924e3a7a2d588f86f16102c5f2f4080b20d81e`.

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

Program state changes use immutable chained revisions. Revision 3 binds revision 2, Campaign 1's
exact runtime database, final report, final freeze, reassessment, independent review, and 18
consumed specifications. Campaign 2 must freeze and pass independent review without adapting from
Campaign 1. A later revision must bind the immediately preceding state and the exact evidence that
justifies the transition.

Historical simulation does not establish future profitability or trading authority.
