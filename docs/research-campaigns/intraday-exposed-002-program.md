# Intraday Exposed 002

Status: plan v1 and its independent review merged. The exact May GET exposed a pre-result raw
transport boundary mismatch. That attempt is closed. Amendment v2 and its independent review are
frozen before data binding or strategy results and await merge.

Starting main: `71aa4da11875cffbff77693be83d116d11a5cb73`

Plan: `config/research/intraday-exposed-002-plan-v1.json`

Plan SHA-256: `8acb778eec43dd53b56c65712b5a076bdc6126de3504d68114aa714e2474b17f`

Plan fingerprint: `a255949e41c9776e82a04782c6183f5af1476a1dc97c36be4910e4d59424fb98`

Independent review SHA-256: `7a87b647aaf420a8613b793f26bc948c5572e6d66907f9aa9c330e9c543fafb0`

Independent review fingerprint: `2ecd5227c3ddc51de9725484de21c994a930dc6f83b7c866d886b68185efdcc4`

May acquisition disposition SHA-256:
`eca321176b609e5b2e9069b7364a1d61979998899b8ef6c4dc4c75d457816707`

May acquisition disposition fingerprint:
`3715a0f424e7450976b1d17f0118906ab9c862e601fcb2c226d98916465df7b3`

Plan amendment v2 SHA-256: `d6409531b31d25c4f3bcd79a55b2bf22b359ca71e4a0fada346ba06dbf0bc14b`

Plan amendment v2 fingerprint:
`e02a23d078f5b4d7216f7b1ede6dab0c2b85859e8e56c4781da5fa32a6429e00`

Plan amendment v2 review SHA-256:
`a739b1e5bb82d0c03640e5d9fd13a4d1edc3b77c1865ed7a065520f9d3c11aa3`

Plan amendment v2 review fingerprint:
`38a359ce9eb04243ba4092e7eb70c7239a46ac738de3ccbd09b6ddde31325976`

This campaign tests new sparse SPY/QQQ five-minute strategies under the frozen calibrated execution
model. It does not replay an Intraday Exposed 001 candidate. It does not read or modify protected
results, V3 data, June data, PAPER or broker state, or `strategic-allocation-21`.

## June disposition

The first metadata-only audit considered the active registry and Exposed 001. It concluded that
June could be reserved once, subject to a later conflict check. A second metadata-only review found
that the committed exposure inventory already classifies Intraday V2 real-market results through
June 30, 2026. No V2 result or market-data artifact was opened to make this finding.

The v1 reservation remains historical evidence. The corrective
`intraday-exposed-002-june-disposition-v2` artifact supersedes its clean-range conclusion while
preserving its conservative no-read rule. Its SHA-256 is
`a3b623a6ab070a8f33cc5d032bf4ab944e9e2d971405c95f4b220e758c5250f0`; its fingerprint is
`7c8a2ea44a3f6679d5cc7ca72b0aee509073272723755c8fea99b09b85de477d`.

June is ineligible for controlled evaluation. The program will not read it or choose a substitute.
An empty final cohort closes as failed exposed evidence. A nonempty exposed-serious cohort freezes
with blocker evidence and stops before controlled evaluation. Neither path grants controlled
qualification.

## Data and chronology

The plan binds three existing IEX five-minute dataset identities through April 30, 2026. It does
not bind the existing May–June artifact. That Parquet file was written without row-group statistics,
so applying a May predicate can scan June rows before filtering them.

After plan v1 merged at `1aedc2d4056c955a8fdd835a1795277979c94be4`, the program made its exact
GET-only Alpaca historical request for QQQ and SPY from `2026-05-01T13:30:00Z` through
`2026-05-29T19:55:00Z`. It published new dataset
`4afa60f29ea266ec8b60be9d9600132f8cff4207e846443c65afd3bb5c497a19`; it did not derive from or
filter the May–June artifact.

The normalized Parquet is valid and has the exact 20-session, 3,120-bar XNYS grid through `19:55`.
The manifest requested and actual ranges match it. The immutable raw evidence retained 3,503 mapped
transport records, including 383 outside that grid, and ends at `20:00` on May 29. No raw,
normalized, or manifest market-data timestamp reaches June.

The five-minute raw overrun violated plan v1's stricter publication rule. The acquisition
disposition therefore forbids binding under v1, raw deletion or filtering, and strategy execution.
Amendment v2 preserves every strategy and control while replacing only that boundary: raw transport
records must remain complete and strictly pre-June; normalized Parquet and manifest ranges must end
exactly at `19:55`. It binds the exact dataset fingerprints, byte hashes, counts, and bounds.

Amendment v2 still grants no binding authority. Its independent final-byte review passed with no
findings. The amendment and review must merge first. The exact binding must then be frozen in
`config/research/intraday-exposed-002-data-binding-v1.json`, independently reviewed, and merged
before strategy execution. One-minute acquisition remains excluded.

| Stage | Evaluation range | Sessions |
| --- | --- | ---: |
| Discovery | July–October 2025 | 87 |
| Walk-forward 1 | November–December 2025 | 41 |
| Walk-forward 2 | January–February 2026 | 39 |
| Walk-forward 3 | March–April 2026 | 43 |
| Final exposed fold | May 2026 | 20 |

Each walk-forward range receives ten prior XNYS sessions for causal warmup. Strategies abstain when
history is insufficient. They decide only from completed bars and known prior sessions.

## Search

The exact search contains 60 parent configurations: ten families with two small axes and six points
each. Every family has two free parameters, below the four-parameter preference and 800-parent
ceiling.

| Family | Required direction |
| --- | --- |
| Gap-down failed-continuation fade | Gap fade after confirmation |
| Gap-up confirmed continuation | Gap continuation |
| Opening-range breakout | 10-, 15-, and 30-minute ranges |
| Volatility-compression breakout | Quiet range followed by expansion |
| Trend-pullback recovery | Established trend, pullback, recovery event |
| Prior-session level event | Prior-high breakout and prior-low rejection with prior-range filter |
| Morning-afternoon continuation | Morning cutoff and one afternoon entry |
| Cross-asset confirmed breakout | SPY/QQQ agreement as a filter |
| Volatility-filtered breakout | Prior-session expected move relative to cost |
| Minimum-edge hysteresis one-trade | Signal-to-cost threshold and hysteresis |

Every structure is long-only, uses a fixed half-weight per active symbol, does not resize, permits at
most one entry per symbol per session, and is flat at the XNYS close. This caps the design at two
completed round trips per session across SPY and QQQ.

## Costs and accounting

Discovery and walk-forward run paired Normal and exact zero-cost diagnostics. Normal uses each
symbol's p75 adverse half-spread, one delay bar, and daily SEC, TAF, and CAT charges. Stress A and B
use p95/p99 spreads with two and three delay bars. Isolated Normal delay-2 and delay-3 variants keep
the Normal monetary model.

The new engine must derive New York account days from aware fill timestamps, group TAF partial
fills by trade, deduct daily regulatory charges before the next session, and record:

```text
gross profit/loss - execution friction = net profit/loss
```

Gross profit/loss uses the Normal path's quantities at unadjusted eligible prices. Execution
friction is adverse fill-price slippage plus regulatory fees. The zero-cost replay remains a
diagnostic and cannot pass a gate on its own.

## Prospective screens

All 60 parents finish discovery before uniform screening. Discovery requires positive Normal and
zero-cost returns, at least eight round trips, no more than two round trips per session, drawdown no
greater than 5%, cost no greater than 35% of gross profitable-trade profit, at least 3 bps average
gross edge, at least three bars average holding time, positive-profit symbol concentration no
greater than 85%, and exact accounting. At most 30 points and four per family enter walk-forward.

Walk-forward applies the same cost-efficiency and accounting gates across four folds. It also
requires at least three positive Normal folds, positive aggregate and May returns, and no fold below
-1%. At most 15 points and two per family become serious.

Every serious point runs Stress A, Stress B, isolated delay-2, and isolated delay-3 on every fold.
Each variant must stay positive in aggregate and on at least three folds. Profit retention floors are
50% for Stress A and delay-2 and 25% for Stress B and delay-3. Every immediate one-axis parameter
neighbor runs paired Normal/zero across all folds; at least 67% must remain positive and median
Normal profit retention must reach 50%.

The final cohort contains zero to five candidates and at most one per family. Selection uses visible
stress, return, cost, and candidate-ID ordering; there is no composite score or post-result
substitution. One create-only final-freeze artifact must include the full screened ledger, cohort,
source identities, and June blocker.

## Required review and implementation gates

The plan-v1 independent prospective review passed with no findings after a final-byte recheck. The
later transport mismatch did not change any price, strategy, cost, chronology, gate, stress,
neighbor, cohort, June, or terminal rule.

Amendment v2's independent final-byte review passed all six controls with no findings. Repository
gates, PR review, CI, and merge remain. The exact May data binding and its separate review must merge
next. A later isolated runner must then pass focused tests, full repository gates, PR review, CI,
and merge. The runtime must start from that exact merged implementation main. No strategy run is
allowed sooner.

The plan grants no research qualification, controlled evaluation, protected holdout, paper,
broker-write, or live authority.
