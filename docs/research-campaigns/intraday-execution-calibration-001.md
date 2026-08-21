# Intraday Execution Calibration 001

Status: v1 closed before dataset publication; v2 acquisition and analysis complete; prospective model frozen before strategy research.

Active plan: `config/research/intraday-execution-calibration-001-plan-v2.json`

V2 plan SHA-256: `67dc2a2155a91f5ab26395a4c3f34457ebcb6e1813f95f7e02c642129c9db546`

V2 plan fingerprint: `c0c4971336569eb05935e2b0b92ffbc3aea50ae39686c7192afbd2cbe99fca4b`

Cost-model ID: `intraday-execution-cost-model-001-v1`

Cost-model SHA-256: `a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af`

Cost-model fingerprint: `94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4`

Independent-review ID: `intraday-execution-cost-model-001-independent-review-v1`

Independent-review SHA-256: `fb197856b9229349e5de4bca742f328a8f1e5e53f9558dfd7324744e91a795aa`

Independent-review fingerprint: `8ade5190bb64330af037f88bf0911ed3cdb04578ca7a6d6e27a5fa6d651349b2`

V1 starting main: `1186e9356de742ed94d030f272ba5522553be78a`

V2 starting main: `355e0ae3b8d1697553f3cfc8b3f230b2019b72dd`

This program calibrates a prospective small-order SPY/QQQ execution-cost model. It does not read
strategy results. It grants no holdout, paper, broker-write, or live authority.

## June audit

The audit used repository files and SQLite metadata only. It did not open a June bar, quote, or
strategy-result artifact.

- The active controlled registry contains no experiment whose declared range overlaps June 2026.
- It contains no unconsumed holdout-run authorization.
- The exposed catalog contains metadata for the existing May-June five-minute bar dataset. The audit
  did not open its Parquet or raw records.
- The local Exposed 001 runtime database is absent.
- `CURRENT_STATE.md` records zero Exposed 001 June strategy runs, no controlled plan, and no
  controlled result.
- The old frozen plan named June, but the name alone created no global reservation or access
  authority under `docs/research-policy.md`.

`config/research/intraday-exposed-002-june-reservation-v1.json` recorded that first conclusion and
forbade early access. A later metadata-only review found the conflict its failure rule anticipated:
the committed exposure inventory classifies Intraday V2 results through June 30, 2026. The v2 June
disposition preserves the old artifact but supersedes its clean-range conclusion. Exposed 002 will
not read June, perform a controlled evaluation there, or choose another range.

## V1 acquisition failure

The first frozen SIP probe returned 112,133 QQQ quote updates for the 2025-07-03 opening window.
Three unique updates were crossed by $0.01. All three carried condition `R`, occurred away from an
exact one-second grid timestamp, and were followed by an uncrossed update within 0.454 milliseconds.
V1 required every raw update to have `ask >= bid`, so validation stopped before dataset publication,
feed selection, analysis, or strategy access. It did not fall back to IEX.

The ignored raw quarantine evidence has SHA-256
`c099643476b3f26f9342697c842245644ba6a81ad95275b3465a5fa592705f82`. The committed sanitized
failure record is `config/research/intraday-execution-calibration-001-plan-v1-failure-v1.json`,
SHA-256 `2bab01f3cc5b4e5809e80d4ce2ab11e32038d23ba129d754ca1a46419a129ef0`, fingerprint
`4d048b3775e971617fd1448e48d6f9cf7957a909fb06ef0161f63fbc96b7b0f7`. V1 plan and quarantine
bytes remain unchanged.

Official UTP and CTA specifications permit crossed national BBO states. Condition `R` marks a
regular BBO-eligible quote; it does not make crossing impossible. V2 therefore treats crossing as a
market state that is ineligible for a simple nonnegative spread observation, not as malformed raw
data.

## Exposed 001 cost audit

Exposed 001 used `CostModel` through `IntradayExposedStateTransitionEngine`. A changed desired state
filled at the eligible bar open through the shared `BacktestEngine._execute` path.

Let `P` be the eligible bar-open price and `q` the absolute fill quantity.

| Item | Exact treatment |
| --- | --- |
| Buy slippage | Fill price `P * (1 + 5 / 10000)` |
| Sell slippage | Fill price `P * (1 - 5 / 10000)` |
| Commission | `abs(q * fill_price) * 1 / 10000` on every buy and sell fill |
| Delay | One whole five-minute bar. This changes the eligible market price; it is not a numeric fee. |
| Sizing | Decimal fractional shares. Entry quantity uses the slipped buy price. Whole-share rounding is absent. |
| Scaling | Slippage and commission scale linearly with fill quantity and notional. There is no ticket minimum or daily fee rounding. |
| Regulatory fees | Absent. SEC, TAF, and CAT charges are not represented. |

At an unchanged reference price, a complete buy/sell round trip pays 10 bps of reference notional in
slippage and 2 bps in commission. The exact modeled loss is `0.0012 * q * P`, or 12 bps of one-way
reference notional. Relative to buy cash outlay, it is about 11.9928 bps.

This model treats buys and sells symmetrically for the 1 bp commission. Slippage is adverse by side.
It does not model spread, quote state, queue position, partial fills, latency inside a bar, market
impact, or regulatory charges.

## Current Alpaca equity fee facts

Retrieved from official Alpaca sources on 2026-08-20 UTC.

| Charge | Current published treatment |
| --- | --- |
| Brokerage commission | Alpaca says it generally charges no trade commission. Its schedule lists 0%-3% per transaction because an authorized business partner or Alpaca Elite Smart Router arrangement can impose a commission. |
| SEC transaction fee | Sells only: `$0.0000206 * trade value`. |
| FINRA Trading Activity Fee | Sells only: `$0.000195 * shares`, capped at `$9.79` per trade. |
| FINRA CAT fee | Buys and sells: `$0.000003 * executed equivalent share` for NMS equities. |
| Rounding | Exact executed quantity includes fractional shares. Each fee type is aggregated daily per account, then rounded up to the nearest cent. |

The calibration assumes a direct Alpaca Securities retail account without a partner commission or
Elite Smart Router fee. PAPER and broker state were not accessed to infer account structure. A later
paper plan must verify that assumption from the account's applicable fee schedule; a mismatch
invalidates this model rather than changing it after research.

Spread is a market price difference, not a broker fee. Slippage is realized execution relative to a
reference quote. Market impact is the order's effect on prices. Alpaca's paper system says orders are
matched against NBBO but does not model market impact, latency slippage, queue position, price
improvement, or regulatory fees. A Paper Only account is entitled to IEX market data. SIP is still
preferred for this calibration because it represents all U.S. exchanges; if the account returns HTTP
403 for SIP, the frozen method uses IEX and labels it as venue-only evidence.

## Frozen quote method

The plan selects no date from volatility or strategy performance.

- Range: exposed sessions from July 2025 through May 2026. June and all V3 periods are excluded.
- Sessions: the first XNYS session on or after the 15th of each month, plus every early close in the
  range. This produces 14 sessions, including 2025-07-03, 2025-11-28, and 2025-12-24.
- Windows: ten minutes after the earliest possible five-minute fill, morning, session midpoint,
  afternoon on normal sessions, and the final ten minutes. This produces 67 windows.
- Sampling: one grid point per second. Each point inspects the latest unique raw quote strictly
  before that second and no more than five seconds old, then applies spread eligibility without
  backfill.
- Weighting: time-weighted grid observations, not quote-message counts.
- Raw validity: ordered timestamps, exact symbol and feed, nonnegative prices and integer sizes, one
  or two condition codes, and explicit duplicate and same-timestamp counts.
- Grid eligibility: inspect the latest unique raw quote strictly before each grid point; never
  backfill an older quote. Exclude and count stale, one-sided, zero-size, or crossed latest states.
  Locked states remain eligible with zero spread. Require at least 99% eligible-grid coverage in
  every symbol-window.
- Statistics: spread dollars, spread bps, half-spread bps, median, p75, p90, p95, and p99 for each
  symbol, each time window, symbol-window pairs, and the combined sample. Nearest-rank percentiles
  avoid interpolation choices.

The v2 runner uses the separate runtime identity `intraday-execution-calibration-001-v2` and
publishes 134 content-addressed symbol-window datasets. Each retains canonical raw quotes, causal
one-second observations, validation counts, source feed, retrieval time, and SHA-256 values. V2
cannot reuse the v1 quarantine or feed state. Before parsing the first nonempty SIP page, the runner
writes a create-only marker. If feed selection has not completed, that marker makes every later
attempt SIP-only; IEX fallback remains possible only when no SIP quote has ever returned in v2.

```console
uv run python -m systematic_trading_lab.intraday_cost_calibration \
  inspect-plan --data-home .trading-lab
```

After exporting the externally stored Alpaca research credentials:

```console
uv run python -m systematic_trading_lab.intraday_cost_calibration \
  acquire --data-home .trading-lab
```

```console
uv run python -m systematic_trading_lab.intraday_cost_calibration \
  analyze --data-home .trading-lab
```

## V2 result and frozen model

V2 acquired all 134 frozen symbol-windows from SIP. It did not use IEX and wrote no quarantine
artifact. The raw and observation evidence remains ignored local state under the v2 runtime root.
The dataset-ID fingerprint is
`6ea873f76a26ed38a5522d7a16d6773b7755d2511a3ad6a2681ce6d5fb2aa762`.

Analysis fingerprint `5302ae235f4fba10c516fc6a110b0717ba81879a5944e25548fd0ee95e30d07d`
and SHA-256 `0555a247138450ffc0e76b5b273d94e1a5c8c6a09634d5f063da57eda8df12be`
bind 80,399 eligible one-second observations. The quote-dataset fingerprint is
`3c5d4f853b281c635df1f6575fa98db11acd12d640798e043650c603e5a80036`.
Minimum symbol-window coverage was `0.9983333333333333333333333333`. One grid point was excluded
because its latest causal state was crossed; 3,858 crossed raw updates remained in evidence.

The model uses adverse half-spread by symbol and rounds the selected rate upward to 0.01 basis
point:

| Scenario | SPY per fill | QQQ per fill | Delay | Monetary fees |
| --- | ---: | ---: | ---: | --- |
| Normal | 0.09 bps (p75) | 0.17 bps (p75) | 1 five-minute bar | SEC, TAF, CAT; zero assumed direct-retail commission |
| Stress A | 0.16 bps (p95) | 0.25 bps (p95) | 2 five-minute bars | Same fee schedule |
| Stress B | 0.22 bps (p99) | 0.36 bps (p99) | 3 five-minute bars | Same fee schedule |
| Zero-cost diagnostic | 0 | 0 | 1 five-minute bar | None; no promotion authority |

The delay changes the eligible market price and is not a fee. Isolated Normal-cost delay-2 and
delay-3 variants separate timing sensitivity from cost sensitivity. Regulatory fees derive the New
York account day from each aware execution timestamp and require a trade identity. TAF aggregates
partial fills by trade before its per-trade cap; each fee type then rounds upward once per account
day. The model does not
claim to measure depth, queue position, partial fills, price improvement, order latency, or market
impact. An applicable partner or Alpaca Elite commission invalidates it.

`config/research/intraday-execution-cost-model-001-v1.json` binds the plan, analysis, dataset
fingerprints, formulas, source documents, assumptions, scenarios, and false authority fields. The
typed loader rechecks the exact model bytes and can reverify the ignored analysis before research.

The independent review passed after the fee boundary was changed to group TAF partial fills by
trade and derive New York account days from aware execution timestamps. Its seven answers were:

| Control question | Answer |
| --- | --- |
| Candidate returns excluded? | Yes |
| June excluded? | Yes |
| V3 excluded? | Yes |
| Spreads measured causally? | Yes |
| Broker fees represented correctly? | Yes |
| Normal defensible rather than optimistic? | Yes |
| Stress A/B materially stricter than Normal? | Yes |

The fingerprinted review artifact records each basis, the resolved findings, verification, scope
limit, and false authority fields. It binds the exact model SHA-256 and fingerprint above.

## Official source identity

| Source | Document identity | SHA-256 |
| --- | --- | --- |
| <https://docs.alpaca.markets/us/docs/regulatory-fees.md> | Updated 2025-10-03; retrieved 2026-08-20T21:27:06Z | `ee2d303dd467b1de58bea957fcfb0f6799e7f807c5260414308b38ef59f656be` |
| <https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf> | Revised 2026-07-20; retrieved 2026-08-20T21:27:11Z | `cfed684b2554e856022bc80c4883260ea1414c4ba79fc65304f7fc08cc780a7e` |
| <https://docs.alpaca.markets/us/docs/paper-trading.md> | Updated 2026-07-07; retrieved 2026-08-20T21:27:06Z | `8a8bfb57946d8ab1fb80ac8bdb65f6f43d904e955a676d6a5f9f76b6a145a846` |
| <https://docs.alpaca.markets/us/reference/stockquotes-1.md> | Updated 2026-05-27; retrieved 2026-08-20T21:27:06Z | `5be32c1fa69c8d5e68fb3946d3e8e05da48ddd7e2afb3f0c7f375b33d0a7028c` |
| <https://utpplan.com/DOC/UtpBinaryOutputSpec.pdf> | July 2026; retrieved 2026-08-20T22:03:00Z | `e031d0fb283a97558ca0ae7007e92343c696371d44cd4596189737cbb715c1e3` |
| <https://www.ctaplan.com/publicdocs/ctaplan/CQS_Pillar_Output_Specification.pdf> | PDF created 2026-03-06; retrieved 2026-08-20T22:03:00Z | `57a88227590f136ecc64a1488aa611f88295ab1fe7b569bc59bd656abbb30dc6` |
