# Program 003 low-cost successor plan

Program 003, `multi-hour-sector-etf-research-002`, is a proposed successor to terminal Program 002. It preserves the untested economic hypothesis and replaces only the data, corporate-action, missingness, and transaction-cost architecture. This plan grants no data-request, acquisition, strategy, controlled, PAPER, broker-write, or live authority.

## Lineage

Program 002 did not fail a strategy test. It stopped before strategy execution because its frozen Alpaca evidence could not reconstruct nine missing MDY bars and its conditional Massive replacement failed the adjustment, aggregate-eligibility, and licensing gates before transport. No Program 002 strategy return was generated or observed. Its controls and failed source lineage stay immutable.

Program 003 therefore keeps the same return-blind hypothesis:

- Tradeable universe: IWM, MDY, XLB, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, and XLY.
- Context and benchmark only: SPY.
- Families: `multi-hour-sector-relative-continuation-v1` and `multi-hour-sector-relative-reversal-v1`.
- Decision: 11:30 America/New_York.
- Lookbacks: 30 and 60 minutes.
- Holds: 120 and 240 minutes from actual entry.
- Portfolio: long/flat, at most three positions, no leverage, shorting, resizing, or reentry.
- Search: the same eight family/lookback/hold configurations, at most 232 run specifications and 696 infrastructure attempts.

No symbol, family, indicator, lookback, hold, or decision time is added.

Program 003 binds the exact predecessor plan at SHA-256 `2872d4d3301df0a85e1a5a2eba6e3ee533ee5573971121e99840041e7c8d2173` and fingerprint `701dc67ea2da1e45d235f4247724b2bc8eb62853561c2400c17a668342c6b81e`. A future validator must load and verify that artifact before implementation or data access. Its economic, feature, configuration, portfolio, benchmark, metric, gate, budget, controlled-evaluation, statistical, and researcher-discretion controls remain in force except for the plan's explicit data, adjustment, missingness, and transaction-cost replacements.

## Canonical source design

The sole candidate is Tiingo's Beta consolidated historical intraday endpoint:

```text
GET https://api.tiingo.com/tiingo/equity/intraday/<ticker>/prices
```

The required effective request is bounded by start and end date, resampled to five minutes, limited to regular sessions, excludes after-hours bars, sets force fill to false, and requests open, high, low, close, and volume. Current public documentation confirms `startDate`, `endDate`, `resampleFreq`, and `columns`, but does not publish the exact after-hours or force-fill parameter names. It also leaves bar labels, timezone, regular-session boundaries, bucket alignment, partial buckets, pagination limits, corrections, and revisions unresolved. No implementation or transport may infer those semantics.

Raw unadjusted Tiingo five-minute OHLCV and exact response bytes would be canonical source evidence. A deterministic repository-owned layer would create split-normalized analytical price and volume, then aggregate complete five-minute bars into thirty-minute features. Raw contemporaneous five-minute opens would remain the execution prices. Alpaca evidence may serve only as an existing read-only structural comparison; it can never fill a Tiingo gap or create a blended price.

There is no fallback. A failed Tiingo qualification stops Program 003 and requires a new user decision.

## Current license blocker

Tiingo advertises Starter at $0 with 50 requests per hour, 1,000 per day, 1 GB per month, and 500 unique symbols per month. Its current Terms of Use prohibit Starter and trial users from persisting Tiingo data in files, databases, logs, queues, archives, or backups. That conflicts with this repository's immutable raw-evidence requirement.

Power is advertised at $30 per month with 10,000 requests per hour, 100,000 per day, and 40 GB per month. The terms permit persistence only while an eligible paid plan remains active and require deletion after cancellation or downgrade unless separate written terms apply. No purchase is authorized.

The preferred `$0` design is therefore not scientifically usable under current public terms. The projected recurring cost for a reproducible Tiingo design is $30 while data is retained. Program 003 stays blocked before source-qualification authority unless the user accepts that obligation or Tiingo grants separate durable-retention terms, and provider-authored material resolves the remaining semantics and endpoint entitlements.

## Force fill and missingness

Force fill must be explicitly false. Forward fill, backward fill, interpolation, synthetic OHLC, previous-close substitution, symbol dropping, and date replacement are prohibited. A missing interval remains absent.

Admission uses the complete cross-section as its minimum unit. If any expected regular-session five-minute bar is absent for any of the twelve ranked ETFs or SPY, the whole session is excluded from every configuration, benchmark, and later context use. An early close never trades and may be context only when all thirteen symbols contain all 42 scheduled bars.

The return-blind ceilings are:

- At most seven of 1,499 full exposed sessions and at most 0.5% overall.
- At most one excluded session and 1% in any fixed discovery or test block.
- At most one excluded session in any rolling 63 expected sessions.
- At most one consecutive excluded session.
- At most one session with the same missing symbol in any rolling 252 expected sessions.
- Zero loss in the fixed twenty-session required context.

Any failed ceiling stops dataset admission and the program. A fixed block has about 125-126 full sessions: one loss is about 0.8%, while two are at least 1.59%, so one percent permits one isolated defect but not two in the same six-month block. The global rate is half that ceiling to prevent sparse block losses from accumulating; `floor(1499 * 0.005) = 7`. Sixty-three sessions define a trading-quarter concentration horizon, and 252 define a trading-year same-symbol recurrence horizon. Two adjacent excluded sessions indicate a continuing mechanism. Required context allows no loss because a missing member changes every affected fixed relative-volume denominator. These return-blind rules do not admit the known clustered MDY gaps, which fail the fixed-block, rolling-quarter, and same-symbol controls.

## Corporate actions

Tiingo's split and distribution endpoints are also Beta or early release and their entitlement is unclear. Qualification must resolve that access before transport.

For each active split, the analytical layer uses the exact rational ratio `splitTo / splitFrom`. For a source session before an ex-date and an exposed-range anchor of July 31, 2026, historical OHLC is divided by the cumulative ratio and volume is multiplied by it. The implementation must use standard-library `Fraction` values without float rounding. Raw OHLCV and raw fill prices remain unchanged.

Cash distributions are retained as audit records but are not applied to price or portfolio cash. Every planned position opens after the ex-date session begins and closes in that same session, so it never owns an overnight distribution entitlement. Any overnight hold, cross-session price return, or total-return benchmark needs a new prospective plan.

Frozen ticker strings and issuer identities are sufficient for the current range. A ticker change fails qualification unless an issuer-backed mapping was reviewed before results; Tiingo permaticker access is not assumed.

## Static transaction costs

Program 003 does not require historical NBBO. It uses one universal conservative envelope for the twelve liquid tradeable ETFs; SPY remains non-tradeable.

| Scenario | Adverse spread/slippage | All-in reserve | Total per side | Delay | Entry |
| --- | ---: | ---: | ---: | ---: | ---: |
| Normal | 5 bps | 1 bp | 6 bps | 5 minutes | 11:35 |
| Stress A | 10 bps | 2 bps | 12 bps | 10 minutes | 11:40 |
| Stress B | 20 bps | 5 bps | 25 bps | 15 minutes | 11:45 |

The reserve covers possible commission, regulatory pass-through, rounding, and other small-order friction without asserting a broker-specific fee schedule. Current issuer-published 30-day median full spreads are 0-2 bps across the thirteen symbols. They are only a lower-bound sanity check, not historical spread evidence. Normal's five-basis-point adverse allowance per side is at least five times the largest current median half-spread before the separate reserve.

Normal also matches the repository's existing return-blind `conservative-bps-v1` baseline of five adverse basis points plus a one-basis-point reserve. Prior SPY/QQQ SIP calibration found p99 half-spreads no greater than 0.36 bps, but that evidence does not cover this universe or prove future fills. Six basis points is not an empirical historical upper bound and may miss episodic adverse selection, bar-open uncertainty, latency, impact, queue position, partial fills, or broker-specific costs. It remains only the frozen Normal assumption. The inherited robustness gates also require Stress A, Stress B, Normal at a ten-minute delay, and Normal at a fifteen-minute delay to pass. Normal alone can never qualify a candidate, and later evidence may raise a stop but cannot lower costs after results.

A zero-cost replay may later diagnose whether gross edge exists, but it can never qualify a candidate.

## One-use structural qualification

Qualification is designed but blocked before authority. It contains no strategy return and fixes thirteen symbols across fifteen sessions:

- The five sessions containing the nine exposed MDY coordinates.
- Three ordinary controls.
- The November 25, 2022 early close.
- December 4, 5, and 8, 2025 around the five Select Sector SPDR 2-for-1 splits.
- June 10, 11, and 12, 2024 around a fixed IWM distribution control.

The sample contains 14 full sessions, one early close, and exactly 14,742 expected bars. It permits at most 195 single-session bar chains, 13 split chains, 13 distribution chains, 221 HTTP responses, 16 MiB, and one credential load. Every response must reparse and rederive to identical evidence; correction behavior must match the pre-transport contract. Qualification must find all expected coordinates, no duplicates or foreign bars, all nine real MDY bars, exact regular-session counts, no force-filled row, and the fixed corporate-action controls.

A pass publishes only a structural receipt. Full acquisition still needs separate user authorization. A failure consumes the one-use authority, records only evidence allowed by the license, and stops without another provider.

## Acquisition projection

The exposed range would use 74 monthly chunks for each of 13 symbols, plus 26 corporate-action requests: 988 requests total and about 1,546,818 bar rows. At a planning envelope of 200-400 raw JSON bytes per row, raw responses would use about 295-590 MiB; reserve 2 GiB working storage.

At a conservative 40 requests per hour, acquisition spans about 24.7 hours and two calendar days. One create-only receipt per symbol-month or action chain, an atomic response hash, and deterministic pending/completed state make it resumable from the first absent receipt. The free limits are numerically sufficient, but Starter's persistence ban makes them unusable for this design.

## Chronology and next authority

The exposed chronology remains unchanged through July 31, 2026. Controlled A, April 16 through October 15, 2027, and Controlled B, October 18, 2027 through April 14, 2028, remain unacquired and unopened. Controlled A's first twenty complete sessions are context only; evaluation starts on session 21. Controlled B may use only the final twenty complete Controlled A sessions as volume context and cannot be acquired until Controlled A passes every gate and a separate protected-result read is logged.

Each controlled block retains the predecessor's sequence: a block-specific acquisition-only authority after the block ends, independent exact-byte dataset review and binding, then a distinct one-use evaluation authority. Candidate and benchmark grants are consumed atomically and create protected-read receipts before bounded reads. No replacement grant, retry, or reread exists after a receipt. Completed metrics remain hidden until a separate logged reviewer-and-reason event. `exchange-calendars` 4.13.2 ends before Controlled A ends, so a reviewed update must freeze exact session tables without moving block dates before any controlled acquisition.

After the licensing, semantic, entitlement, implementation, synthetic-test, and independent-review preconditions pass, the next possible authorization is exactly one low-cost Tiingo structural qualification: at most 221 GET chains and responses, 16 MiB, one credential load, the fixed sample and corporate-action ranges, and no full acquisition, strategy execution, return observation, controlled access, PAPER, broker write, or live action.

## Sources

- [Tiingo consolidated intraday documentation](https://www.tiingo.com/documentation/equity-realtime-stock-data)
- [Tiingo pricing](https://www.tiingo.com/pricing)
- [Tiingo Terms of Use](https://api.tiingo.com/tos/)
- [Tiingo split documentation](https://www.tiingo.com/documentation/corporate-actions/splits)
- [Tiingo distribution documentation](https://www.tiingo.com/documentation/corporate-actions/dividends)
- [State Street five-ETF split notice](https://investors.statestreet.com/investor-news-events/press-releases/news-details/2025/State-Street-Investment-Management-Announces-Share-Splits-for-Five-Select-Sector-SPDR-ETFs/default.aspx)
- [SEC Section 31 fee information](https://www.sec.gov/rules-regulations/fee-rate-advisories/section-31-transaction-fees-basic-information-firms)
- [FINRA fee adjustment schedule](https://www.finra.org/rules-guidance/rule-filings/sr-finra-2024-019/fee-adjustment-schedule)
