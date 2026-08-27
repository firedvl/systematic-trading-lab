# Program 004 MarketParquet successor plan

Program 004, `multi-hour-sector-etf-research-003`, is a prospective successor to Program 003. It
changes only the data and provenance architecture. It grants no purchase, subscription, credential,
download, qualification, dataset, strategy, controlled, PAPER, broker-write, or live authority.

## Lineage and preserved hypothesis

Program 002 remains terminal. Program 003 did not fail a strategy test: it generated and exposed zero
strategy returns, and its Tiingo source qualification never ran. Program 003 became unattractive
because Tiingo's public terms tie persisted data to an eligible continuing paid plan and require
deletion after cancellation or downgrade unless separate terms apply.

Program 004 binds the exact Program 003 plan at SHA-256
`4b1fd55774f89caf853c27cfc521c94ad1b18435a22ee07c2333ca229e9e2c91` and fingerprint
`f5b184ff3e1604a151a82214d1cf91fbdffa6fc4fddf7d7ce0506a2e99427a42`. It also binds the
finding-free review at SHA-256 `7f7aa36f382ce93b0d3046023e02782626be354a2c44f4c95d1f0fe64284556d`
and fingerprint `55ea3dcb3fc122034b59909bd8431886aa61fac5e8c83ea2a53eb9fdbd060bdb`.

The inherited hypothesis stays fixed:

- Tradeable: IWM, MDY, XLB, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, and XLY.
- Context and benchmark only: SPY.
- Families: cross-sectional continuation and cross-sectional reversal.
- Lookbacks: 30 and 60 minutes.
- Holds: 2 and 4 hours from actual entry.
- Decision: 11:30 America/New_York.
- Portfolio: long/flat, at most three equal-dollar fractional-share slots, no leverage, shorting,
  resizing, or reentry.
- Search: exactly eight family/lookback/hold configurations.

The full exposed chronology, 232-specification ceiling, missing-data rules, 6/12/25-basis-point cost
envelope, delayed-fill checks, controlled blocks, one-use protected reads, and every PAPER, broker,
and live control also remain unchanged.

## Public license verdict

The standard MarketParquet license passes for this constrained use. As retrieved on August 27, 2026,
it expressly permits personal research and trading; commercial or noncommercial backtesting,
modeling, and analysis for the account owner or its single organization; copies on owned machines,
servers, and private cloud storage; non-reconstructable derived results; and AI/ML models and coding
agents operated by the licensee. It calls the license perpetual for downloaded files, including after
Keep Current cancellation or account closure.

Private encrypted backups and hash-frozen snapshots are stored copies within that scope. Raw files,
trivially transformed datasets, public hosting, third-party APIs, and credentials shared outside the
organization are prohibited. Program 004 also prohibits sending raw bars to an external AI or coding
agent not operated by the licensee. That out-of-scope use needs written confirmation.

The Complete Archive was advertised at `$79` once. Keep Current was optional at `$15/month` and is
not needed or authorized. A later authority may permit a manual purchase only when the archive line
item is at most `$89` before tax and the total charge is at most `$100`. Before payment, it must capture
the exact license, terms, price, methodology, and documentation bytes. Any material loss of perpetual
retention, private-copy, research, backtest, or local-agent rights stops purchase.

No recurring cost is required for files already delivered. This is a plan interpretation of the
published contract, not legal advice.

## Source and file contract

MarketParquet says it licenses bars from an unnamed institutional market-data vendor that builds them
from exchange trade feeds. It says it does not scrape prices or synthesize bars, and that the vendor
delivers each timeframe natively. This supports a conditional source verdict for conservative
multi-hour ETF OHLCV. It does not prove official SIP, CTA/UTP equivalence, NBBO, TAQ, or a named
exchange or vendor. Program 004 makes none of those claims and does not need historical NBBO.

The archive advertises US ETF history from January 2000 to the present in native one-minute,
five-minute, thirty-minute, one-hour, and daily files. Each Parquet file contains all ETFs for one
trading date. Intraday rows contain a timezone-naive US/Eastern bar-open timestamp, symbol, asset
type, OHLC, and volume. The files include extended-hours rows where trades exist. They do not insert
synthetic or forward-filled bars.

Program 004 selects native `etf_5min` files. The strategy already consumes five-minute bars, the
provider advertises native bars, and the full five-minute archive is 6.8 GB versus 15.4 GB for
one-minute data. Rebuilding five-minute bars from one-minute files would add storage and a new bucket
contract without improving the strategy definition.

The private raw evidence is each exact whole-date file. A later isolated adapter must:

1. Attach `America/New_York` to the naive source timestamp, then convert it to UTC.
2. Filter the thirteen symbols and the exact XNYS regular-session five-minute bar-open grid.
3. Sort by timestamp and symbol and preserve provider numeric values without rounding volume to an
   integer.
4. Label the projection `provider-split-adjusted-no-dividends-v1`.
5. Aggregate six complete five-minute bars into each inherited thirty-minute feature bucket.

The generic importer cannot be reused: it would treat a naive timestamp as UTC, has no split-only
adjustment label, requires integer volume, and does not own Program 003's bounded whole-session
missingness disposition. The predecessor replay also rejects some 6 bps fractional-Decimal paths at
its exact-accounting assertion because of finite-precision rounding. A future Program 004 replay must
pass exact 6/12/25 bps synthetic accounting before any strategy authority; this plan does not repair
or run that engine.

## Split-adjusted equivalence

Let `s > 0` be the split scale for one symbol and session. MarketParquet's documented representation
is:

```text
adjusted price:       p' = p / s
adjusted volume:      v' = v * s
adjusted share units: q' = q * s
```

For every same-session price return:

```text
p_exit' / p_entry' - 1
= (p_exit / s) / (p_entry / s) - 1
= p_exit / p_entry - 1
```

The scale cancels independently for each ETF and SPY. The 30-minute return, 60-minute return,
SPY-relative residual, continuation/reversal order, activity threshold, ticker tie-break, and top-three
selection are unchanged.

Equal-dollar replay is also invariant:

```text
q' * p' = (q * s) * (p / s) = q * p

q' * (p_exit' - p_entry')
= (q * s) * ((p_exit / s) - (p_entry / s))
= q * (p_exit - p_entry)
```

Notional, weights, unused cash, market P&L, bps-on-notional costs, every marked equity value,
percentage return, and percentage drawdown remain identical. `p' * v' = p * v`, so prior median
dollar volume and capacity ratios also remain identical. The common fee-reserve scale is unchanged
because Program 003 froze an all-in bps reserve.

Integer-share rounding and per-share fees are not invariant because adjusted share units change.
Program 003 already excluded both: it uses fractional Decimal units and no separate per-share fee
formula. Program 004 binds that rule and does not reuse the optional predecessor regulatory-fee path.

The proof establishes representation compatibility under consistent scaling. It does not reconstruct
unavailable contemporaneous raw prints or remove provider FLOAT64 rounding. Inconsistent price and
volume scaling, dividend-smoothed prices, or a factor that changes inside a session fails the plan.

## Relative volume, dividends, and split sessions

Relative volume is current 09:30-11:30 volume divided by the mean for the same interval over the
twenty prior complete sessions.

- Away from a split, one common scale multiplies numerator and denominator and cancels.
- Immediately before a split, the current and lookback observations share the archive scale and it
  cancels.
- Immediately after a split, pre-split volume is converted to post-split-equivalent share units. The
  ratio then matches the counterfactual expressed in one common unit. Comparing unadjusted pre-split
  and post-split share counts would mix units.
- Once the lookback clears the split, all observations already use the new unit.

MarketParquet says dividends are not embedded in prices. Program 004 applies no dividend adjustment
and no cash credit. Every return feature starts after the session open, every position opens and closes
the same day, and prior context uses volume and dollar-volume capacity rather than an overnight price
return. An ex-dividend session therefore follows the normal full-session rule. Overnight positions,
cross-session price returns, or a total-return benchmark require a new plan.

A split-effective session is not excluded just because a split occurred. It is admitted only when the
complete cross-section and reciprocal price/volume basis pass. A partial or pre-applied rebase fails
qualification or admission.

## Corrections and immutable evidence

MarketParquet documents nightly re-pulls, trailing-window corrections, explicit older overwrites, and
full-history split rebasing. Its remote archive is mutable.

Program 004 freezes exact delivered bytes. Each file gets a SHA-256 hash, acquisition timestamp,
trading date, byte count, non-secret request identity, product identity, license snapshot hashes,
canonical projection hash, and normalization version. The ordered source and projection manifests
form one immutable dataset ID. Research never points at a moving URL.

A later correction becomes a new dataset version. It cannot replace old bytes or rerun an exposed
campaign after strategy evidence without a new reviewed disposition and user authority.

All raw data stays under `.trading-lab/program-004-marketparquet`, which Git ignores. A committed
report may contain only aggregates that cannot reconstruct the bars.

## One-use structural qualification

The first possible data phase is a manual Complete Archive purchase plus fifteen exact `etf_5min`
date files. It is designed but not authorized. It contains no strategy calculation.

The fixed dates are:

- Five sessions containing the nine exposed MDY gaps: December 4, 2020; February 3, 5, 10, and 22,
  2021.
- Three normal controls: July 27, 2020; July 17, 2023; July 15, 2026.
- One early close: November 25, 2022.
- Three sessions around the five Select Sector SPDR 2-for-1 splits: December 4, 5, and 8, 2025.
- Three sessions around the fixed IWM distribution control: June 10, 11, and 12, 2024.

The sample has fourteen full sessions, one early close, and exactly 14,742 required regular-session
rows. A later authority is capped at fifteen authenticated URL responses, fifteen presigned file
responses, 128 MiB, and one credential load. A transport failure stops without retry.

A pass requires:

- Exact raw hashes and deterministic reparsing/projection hashes.
- The documented schema and Eastern bar-open timestamp conversion.
- Exactly 78 rows per symbol on each full session and 42 on the early close.
- Every required coordinate exactly once, including all nine MDY coordinates.
- Finite positive OHLC, valid ranges, and finite strictly positive volume without integer coercion.
- For each of XLB, XLE, XLK, XLU, and XLY, both the December 5 open divided by the
  December 4 close and the December 8 open divided by the December 5 close must be from `0.75` through
  `1.333333333333333333333333333`. This rejects an unapplied or double-applied factor-of-two price
  discontinuity. The captured methodology binds reciprocal volume adjustment; adjusted-only files
  cannot reconstruct raw share volume or independently audit upstream rounding.
- Split-only, non-total-return treatment around the IWM distribution control.
- No extended-hours row in the canonical projection.

MarketParquet does not have to match Alpaca. A failure stops Program 004 without a patch, blended
source, replacement date, or provider search. A pass publishes only a structural receipt. It does not
authorize the remaining exposed range, dataset admission, strategy implementation, or strategy
execution.

## Later full acquisition

After a qualification pass, independent exact-byte review, and separate user authority, a later phase
may acquire only the 1,511 expected `etf_5min` date files from June 26, 2020 through July 31, 2026. It
would reuse the exact fifteen qualified files and download at most 1,496 more. Source bytes are capped
at 8 GiB with 16 GiB working storage.

Full admission keeps Program 003's missing-data policy unchanged: an incomplete required bar excludes
the whole thirteen-symbol session; no symbol is dropped and no bar, provider, or date is substituted.
At most seven full sessions and 0.5% overall may be lost, with one per fixed block, one per rolling 63
sessions, one consecutive session, one same-symbol failure per rolling 252 sessions, and zero required
context loss. A duplicate, invalid OHLC value, non-finite volume, or zero-volume required row counts as
a missing required bar under those same ceilings. Any failed ceiling stops before strategy execution.

## Costs, chronology, and protected state

Historical NBBO remains unnecessary. Program 004 keeps the same static scenarios:

| Scenario | Cost per side | Delay | Entry |
| --- | ---: | ---: | ---: |
| Normal | 6 bps | 5 minutes | 11:35 |
| Stress A | 12 bps | 10 minutes | 11:40 |
| Stress B | 25 bps | 15 minutes | 11:45 |

Normal also runs at 10- and 15-minute delays and cannot qualify alone.

Controlled A remains April 16 through October 15, 2027, with twenty context sessions before
evaluation. Controlled B remains October 18, 2027 through April 14, 2028 and still depends on a full
Controlled A pass and logged protected-result read. Neither block may be acquired or inspected. V3,
June, daily 2018-2019, PAPER, broker, live, and `strategic-allocation-21` state remain unchanged.

## HF Data Library

HF Data Library is audit-only. Its documentation says pre-March-2022 data is PiTrading consolidated
CTA/UTP-derived data, while post-March-2022 data is IEX-only and about 2-3% of consolidated volume.
That source break affects volume and potentially OHLC; its post-2022 path also does not consume trade
break messages.

HF may later check pre-March-2022 MDY gap presence, split sanity, or timestamp structure. It can never
be canonical, fill a MarketParquet gap, or create a blended dataset.

## Exact next authorization

After finding-free review, green CI, merge, and clean synchronized main, the next possible user grant
is exactly:

> ONE-TIME MARKETPARQUET COMPLETE ARCHIVE MANUAL PURCHASE PLUS FIFTEEN-FILE ETF_5MIN STRUCTURAL
> QUALIFICATION ONLY: at most $89 pre-tax and $100 total, no Keep Current, one credential load,
> fifteen authenticated download-URL responses, fifteen presigned file responses, 128 MiB, the exact
> fifteen dates and thirteen symbols, private immutable evidence, and no remaining exposed-range
> acquisition, dataset admission, strategy implementation or execution, return observation,
> controlled access, PAPER, broker write, or live action.

This plan does not grant that authority.

## Sources retrieved August 27, 2026

- [MarketParquet ETF archive](https://marketparquet.com/data/etfs)
- [MarketParquet pricing](https://marketparquet.com/pricing)
- [MarketParquet data license](https://marketparquet.com/license)
- [MarketParquet terms](https://marketparquet.com/terms)
- [MarketParquet documentation](https://marketparquet.com/documentation)
- [MarketParquet data quality and methodology](https://marketparquet.com/data-quality)
- [MarketParquet FAQ](https://marketparquet.com/faq)
- [MarketParquet ETF five-minute browser](https://marketparquet.com/browse/etf_5min)
- [MarketParquet ETF one-minute browser](https://marketparquet.com/browse/etf_1min)
- [HF Data Library methodology](https://hfdatalibrary.com/pages/docs)
- [HF Data Library known issues](https://hfdatalibrary.com/pages/issues)
- [HF Data Library data overview](https://hfdatalibrary.com/pages/data)
- [State Street split notice](https://investors.statestreet.com/investor-news-events/press-releases/news-details/2025/State-Street-Investment-Management-Announces-Share-Splits-for-Five-Select-Sector-SPDR-ETFs/default.aspx)
