# Intraday SPY-QQQ Lead-Lag 001 program

Status: terminal empty cohort after independent read-only reassessment of a post-observation
screening defect. Do not rerun, rewrite, retune, or reinterpret this campaign.

Program ID: `intraday-spy-qqq-lead-lag-001`.

Plan SHA-256: `1a02410da60f9dc90e2408e46e4dad88fe9ab9ec248ad8cb035f26734dc78b92`.
Plan fingerprint: `177fad36b3911b89a4938cdfe130a6eda81d22bd1d19e448ab7d11b46326a51a`.

Independent-review SHA-256:
`71b60c8d4b900bb4ad1cb8c737fe26927b0365c7314aff5d64c688ffea6b6a07`.
Review fingerprint: `b0f14d7fe31f509300b1f5bedce4dcf6b94edba476efc8ed0b9f9fea351fe5d6`.

Launch-control SHA-256:
`26d1ef10abb3b2ef063dec1bc5931b0c667c2698bc983c7c9e3a3e58ca01e863`.
Launch-control fingerprint:
`b69466bfe3ed67d8e539a6e772341f2fbb7a7bddcdefa4bcee04e336c73c446e`.

Runtime database SHA-256:
`fca67d95832a6fad87f29ef68ce56238a0f9d8d2e02e8d331aece63e4e9e8908`.

Final-report SHA-256/fingerprint:
`d44f9390db7f8882f7375afbfd40607ce51d89d6a7537431e01c9cfd9b6b6608` /
`0c05593ab04da12774c066b361c2f44de4db0a103d4c3f78bb3edd0763e82dc0`.

Final-freeze SHA-256/fingerprint:
`62c2301cde8e72d80f39159b3d38da156e92801afdd70e554356b806cac37d2c` /
`d958ff60712fc60acb04942327fd3930331aa0ce482119a726d19a44cdcf98cf`.

Post-campaign reassessment SHA-256/fingerprint:
`597d7229e1a4a9616fbe418c12b6ad8053cd2ca0f3bae538184ec428b8a50cad` /
`a06e1c83980f6968dba678fb4a0b71b25f73f542e58d01c09ee5144e89b60e6f`.

Independent reassessment review SHA-256/fingerprint:
`8e45148b7711c667dcc1f4190d2820e28632e0f6c0435d36af86b1f43cf83a0e` /
`ddaf06bfb1121dd194d99d20d8c29a48787f320dfebeb33d5fe8b0f67cade7a9`.

Starting main: `4bb7615bcb508db114d11904d07dc202fe135e99`.

## Frozen hypothesis and strategy

Campaign 1 tests fixed-leader cross-asset information transmission on ordinary XNYS sessions. SPY
is always signal-only; QQQ is the only traded symbol. After `6`, `12`, or `18` aligned completed
five-minute bars, SPY must have returned at least `10`, `20`, or `40` basis points from the session
open. QQQ must be nonnegative and no more than half the SPY return. The nine axis combinations form
twelve symmetric undirected immediate-neighbor edges.

A qualifying decision targets QQQ at `0.5` and SPY at zero. The scenario delay fills QQQ at the
next, second-next, or third-next eligible open. The exit decision stays fixed and produces exactly
24 five-minute holding intervals under every delay. Each active session has one QQQ round trip,
zero SPY fills, no resize, and no reentry. A session that cannot complete the delay-3 exit remains
flat and is recorded as hold-capacity-ineligible; the hold never shortens.

This is not an event filter, leader ranking, paired laggard control, joint breakout confirmation,
opening-range rule, relative-strength rotation, or inversion of a predecessor result.

## Data, chronology, and execution

The campaign owns five ordinary-session periods: 87 discovery sessions followed by folds of 41,
39, 43, and 20 sessions. It binds the four exact read-only SPY/QQQ IEX five-minute datasets through
`2026-05-29T19:55:00Z`, the calibrated cost model, completed-bar decisions, next-open delay
semantics, and flat-at-close safeguards. No acquisition is allowed.

Normal and zero-cost reports must have equal cost-independent signal traces. Stress A, Stress B,
delay-2, and delay-3 must preserve the same trace. Every evaluated ordinary session remains in a
ledger with one disposition, causal features or a reason code, fills, fees, friction, round trips,
and reconciled P&L. Under-response ratio and bucket are null when the positive SPY floor does not
pass or hold capacity is unavailable.

Symbol concentration is structurally inapplicable because QQQ is the only traded symbol. Frozen
session, period, and causal under-response-bucket concentration gates replace it; undefined required
metrics fail.

## Screens and budget

| Stage | Maximum specifications |
| --- | ---: |
| Discovery: 9 candidates × Normal/zero-cost | 18 |
| Walk-forward: cap 3 × 4 folds × Normal/zero-cost | 24 |
| Stress/delay: cap 1 × 4 folds × 4 scenarios | 16 |
| Up to 4 immediate neighbors × 4 folds × Normal/zero-cost | 32 |
| Total | 90 |

Run identity is exactly candidate, period, and scenario. Neighbor screening reuses identical
completed rows; unused budget stays unused. The three-attempt infrastructure ceiling permits at
most 270 append-only attempts and only an expired no-result lease can retry.

Discovery, walk-forward, stress, delay, and every applicable neighbor must pass the exact frozen
activity, return, gross-edge, cost, drawdown, concentration, accounting, and trace gates. One
all-gate survivor freezes and stops the autonomous program while waiting for future untouched data.
An empty cohort closes and advances only to predeclared Campaign 2 without adapting its plan.

## Terminal result and reassessment

The exact four-worker launch from source main `a8093f24fba142c2817311bbd3c30656b981b15c`
completed all 18 discovery specifications once. It had zero failure, retry, pending row, running
row, active lease, or later-stage run.

The historical screen omitted canonical decimal strings after report reload, so eight decimal-based
gates appeared as `observed: null` in the frozen ledger. The historical artifacts remain byte-valid
and immutable; they are semantically incomplete for screening. The isolated assessor verified all
18 report bytes and fingerprints, restored the 11 frozen discovery gates, derived activity from
each 87-session ledger, and changed no runtime evidence.

Corrected Normal active-session counts are `3, 1, 0, 0, 0, 0, 2, 1, 0`. Every parent fails the
minimum of 12 active sessions and the matching round-trip gate. The corrected cohort is empty, so
no walk-forward, stress, delay, or neighbor work was warranted. Independent review reproduced the
assessment and found no issue.

## State and implementation boundary

Immutable state revision 3 binds revision 2, the exact historical runtime evidence, reassessment,
independent review, and 18 consumed specifications at SHA-256/fingerprint
`7d35eeaf7f079033d1ce2f396088754ce5de22f829c88e3a884757672feef6a2` /
`7f35e0876c2398589b37b7a34d924e3a7a2d588f86f16102c5f2f4080b20d81e`. Future transitions must
publish a new chained revision; earlier state files cannot be mutated.

The separate strategy, runner, CLI, launch control, and focused tests implement the frozen
contract. Exact-main launch review found that Normal/zero-cost pairs lacked the frozen
decision-trace equality check. Repair main `fa0f19db989c8e9d1e15c3c5a2b3f1bf1ac6dd87` makes a
mismatch terminal and adds a regression test. After durable wording was synchronized, exact main
`c987371b6a1b632b8fa7930ff2ac11192e4b5000` passed the seven repository gates and four-fixture
synthetic one-worker/four-worker equivalence. A fresh independent review found no issue. The launch
artifact bound that evidence before the first reservation or result.

June, Intraday V3, daily 2018–2019, protected results, PAPER or broker state,
`strategic-allocation-21`, and live data remain prohibited. Every authority field is false.
Historical simulation cannot establish future profitability or trading authority.
