# Intraday Exposed 002

Status: plan v1 and its independent review merged. The exact May GET exposed a pre-result raw
transport boundary mismatch. That attempt is closed. Amendment v2 and its review merged. The exact
May data binding and its independent review merged in PR #151. The isolated runner and exact
pre-result mechanics merged in PR #152. Its first invocation stopped during catalog lookup before
runtime state, bar loading, or a strategy result. Runner v2's exact split-catalog dispatch now awaits
independent review, CI, and merge before the first strategy result.

Starting main: `71aa4da11875cffbff77693be83d116d11a5cb73`

Runner starting main: `8df22d0eb87f54c8fb19cb5713908f0dc93dc9d8`

Runner implementation main: `794045775d323f1ba2481b44a454be4386bc7edd`

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

Data binding SHA-256: `3d6a5dde3b05369ceeb1e3be5b1f47e73a541c74eed184e1850945ee56890769`

Data binding fingerprint: `b6849987e7673c4073272ec891e7f7118b91eba6926aa4c16f262162f529ea9d`

Data binding review SHA-256:
`16e1ae6bc4f718f5086eec15dfcdab61fa1a2ca57ce85dab73de8fbb045e3701`

Data binding review fingerprint:
`bae2ed10678d5a18c916773b1dcfe0b11d3b26f1f7ec2d2ec9e88dd88965d444`

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

Amendment v2 and its no-finding review merged in PR #150 at
`01430416953559e0168a2192afb3f859440bc7a4`. The exact binding then passed full local validation and
an independent final-byte review. PR #151 merged the binding and review at
`8df22d0eb87f54c8fb19cb5713908f0dc93dc9d8`. They still grant no strategy-execution authority.
One-minute acquisition remains excluded.

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

## Frozen family mechanics

Bar counts mean completed bars. Fields named `bar_index` are zero-based. Every threshold comparison
uses unrounded `Decimal` arithmetic.

1. Gap-down failed-continuation fade compares the session open with the prior session close. After
   3 or 6 completed bars, it enters when a 20, 40, or 60 bps down gap has retraced at least half of
   the open-to-prior-close distance. It exits at bar index 66.
2. Gap-up confirmed continuation requires the matching up gap. After 3 or 6 completed bars, it
   enters when the current close exceeds every earlier current-session high by 5 bps. It exits at
   bar index 66.
3. Opening-range breakout uses the first 2, 3, or 6 bars. A later close must exceed the range high
   by the greater of 5 or 10 bps and four times the symbol's Normal round-trip cost estimate. It
   exits on a close at or below the opening-range low.
4. Volatility-compression breakout measures the immediately preceding 6, 12, or 18 bars as
   `(maximum high / minimum low - 1) * 10,000`. The range must be at most 15 or 30 bps, and the
   current close must exceed its high by 5 bps. It exits on a close at or below the lower low of the
   bar before entry and the entry bar.
5. Trend-pullback recovery examines the preceding 6, 12, or 18 bars. It measures the trend from
   the first close to the first maximum high, requires a 20 or 40 bps rise, then requires a later
   low in that window to retrace at least one third of that rise. The current close must recover to
   more than 5 bps above the prior bar's high. It uses the same previous/entry-bar exit floor as the
   compression family.
6. Prior-session level event waits for 2 completed bars and requires the prior session's
   `(high / low - 1) * 10,000` range to reach 30, 60, or 90 bps. The breakout branch closes more
   than 5 bps above the prior high. The rejection branch first trades more than 5 bps below the
   prior low, then closes back above that low. It uses the same previous/entry-bar exit floor.
7. Morning-afternoon continuation freezes the morning return from the session open through the
   close of bar index 24, 30, or 36. It requires 20 or 40 bps, waits until at least bar index 48,
   and enters when the current close exceeds every high from the cutoff through the prior bar. It
   exits on a close below the frozen cutoff close.
8. Cross-asset confirmed breakout uses each symbol's first 6 bars. For each of the latest 1, 2, or
   3 completed confirmation bars, both SPY and QQQ must close 5 or 10 bps above their own range
   high. Agreement activates both symbols. Each exits on a close at or below its own range low.
9. Volatility-filtered breakout averages each symbol's complete prior-session range over 3, 5, or
   10 sessions. The average must reach four or eight times that symbol's Normal round-trip cost
   estimate. After the first 6 bars, a close more than 5 bps above the range high enters. A close at
   or below the range low exits.
10. Minimum-edge hysteresis uses the first 6 bars. Both symbols' current close-to-range-high edges
    must each reach their own Normal round-trip cost estimate times 4, 8, or 12. Each entered symbol
    exits when its close falls below its entry close by its own cost estimate times 1 or 2.

The cost-aware filters estimate one `$50,000` Normal round trip. For symbol slippage `s`, the
synthetic buy and sell prices are `close * (1 + s / 10,000)` and
`close * (1 - s / 10,000)`. Quantity is `$50,000 / buy price`. The estimate is
`2 * s + exact synthetic SEC/TAF/CAT fees / $50,000 * 10,000`. This applies the frozen symbol
spread and regulatory rules without reading a strategy result.

## Frozen replay mechanics

A completed bar at index `i` creates its decision at that bar's close. A changed desired state queues
for the open of the scenario's `N`th later bar. Existing queued work remains FIFO and is never
superseded. At cutoff index `session_bar_count - N - 1`, new changes are rejected. Existing queued
entries and exits that remain eligible before the final bar keep their original fill. The controller
projects each symbol's queued final state and, if invested, appends a zero-weight transition at the
final regular-session bar open. No position or transition may cross the session boundary.

An entry buys `min(0.5 * current equity / adverse fill price, cash / adverse fill price)` fractional
shares. It never resizes. An exit sells the full held quantity. Buys pay the symbol's adverse spread
above the eligible open; sells receive it below the eligible open. Daily SEC, TAF, and CAT totals are
deducted after the final flatten and before the next session. Fees are attributed to symbols in
proportion to their fill-price notionals for reporting only.

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

## Frozen metric formulas

Each fold starts with an independent `$100,000` account. Metrics use only its evaluation sessions;
warmup sessions stay flat.

- Gross profit/loss is the sum of `quantity * (exit eligible open - entry eligible open)` over
  completed round trips on the Normal path.
- Adverse slippage is the sum of `absolute(fill price - eligible open) * absolute(quantity)`.
  Execution friction is adverse slippage plus exact daily regulatory fees. Net profit/loss is final
  session-end equity minus `$100,000`.
- Accounting identity error is
  `absolute(gross profit/loss - execution friction - net profit/loss)`, quantized to `1e-12`.
- Total return is net profit/loss divided by `$100,000`. Maximum drawdown uses fold session-end
  equity. Turnover is total eligible-open fill notional divided by `$100,000`.
- Cost to gross profit divides all execution friction by the sum of positive gross round-trip
  profits. It is undefined when no round trip has positive gross profit.
- Gross trade edge is the unweighted per-round-trip mean of
  `gross profit / (quantity * entry eligible open) * 10,000`. Holding bars are elapsed entry-to-exit
  five-minute intervals.
- Symbol net profit is symbol gross profit less symbol slippage and attributed fees. Positive-profit
  symbol concentration is the largest positive symbol net profit divided by the sum of positive
  symbol net profits. It is undefined when neither symbol is positive.
- Multi-fold aggregates sum independently funded fold returns, dollar profit, friction, trade-edge
  sums, holding-bar sums, trades, and sessions. They take the worst fold drawdown, recompute weighted
  averages from totals, and recompute concentration after summing each symbol's net profit.
- Stress retention is aggregate scenario net profit divided by aggregate Normal net profit. A
  neighbor is positive only when its aggregate Normal net profit is positive. Neighbor retention is
  the median immediate-neighbor Normal net profit divided by the base candidate's aggregate Normal
  net profit. Paired zero-cost neighbor reports remain diagnostic and do not satisfy either gate.

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

Amendment v2, its review, the exact May binding, and its review passed repository gates, PR review,
CI, and merge. The isolated runner's independent read-only review found no remaining P0, P1, or P2
issue after focused mechanics corrections, and PR #152 merged it. Its first CLI invocation then
found that the runner used the main catalog for all four datasets even though the three frozen
pre-May datasets remain in the isolated `intraday-exposed` catalog. Lookup failed before full
validation, bar loading, runtime-directory creation, a database or run row, or a strategy result.

Runner v2 dispatches the three exact pre-May dataset IDs only to that isolated catalog and the exact
May ID only to the main catalog. It does not scan, relocate, rebuild, or fall back between roots.
Every existing identity, byte, full-validation, range, and June gate remains unchanged. Independent
review, full repository gates, PR review, CI, and merge remain required. Runtime must start from the
new exact merged implementation main. No strategy result is allowed sooner.

The plan grants no research qualification, controlled evaluation, protected holdout, paper,
broker-write, or live authority.
