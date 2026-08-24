# Intraday SPY-QQQ Lead-Lag 001 program

Status: exact-main launch review found one implementation mismatch; the focused repair awaits merge
and fresh review. Launch control remains unbound. No reservation, market-data read, runtime
directory, or result exists.

Program ID: `intraday-spy-qqq-lead-lag-001`.

Plan SHA-256: `1a02410da60f9dc90e2408e46e4dad88fe9ab9ec248ad8cb035f26734dc78b92`.
Plan fingerprint: `177fad36b3911b89a4938cdfe130a6eda81d22bd1d19e448ab7d11b46326a51a`.

Independent-review SHA-256:
`71b60c8d4b900bb4ad1cb8c737fe26927b0365c7314aff5d64c688ffea6b6a07`.
Review fingerprint: `b0f14d7fe31f509300b1f5bedce4dcf6b94edba476efc8ed0b9f9fea351fe5d6`.

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
An empty cohort closes and advances only to already frozen Campaign 2 without adapting its plan.

## State and implementation boundary

Immutable state revision 2 binds the exact program, Campaign 1 plan, and review at SHA-256
`f74bc4ad3d0d30560ed0eb4718fc00739121849fb503e8045a01d8bc63907a0f`. Future transitions must
publish a new chained revision; the original state file cannot be mutated.

The separate strategy, runner, CLI, launch-control stub, and focused tests implement the frozen
contract. Exact-main launch review found that Normal/zero-cost pairs lacked the frozen
decision-trace equality check. The focused repair makes a mismatch terminal and adds a regression
test. Full repository gates, a repair merge, synthetic one-worker/four-worker equivalence, exact
merged-main launch control, and finding-free fresh launch review remain required before the first
reservation or result.

June, Intraday V3, daily 2018–2019, protected results, PAPER or broker state,
`strategic-allocation-21`, and live data remain prohibited. Every authority field is false.
Historical simulation cannot establish future profitability or trading authority.
