# Program 005 free Alpaca SIP successor plan

Program 005, `multi-hour-sector-etf-research-004`, is a prospective successor to Program 004. It
preserves the untested economic hypothesis and replaces only the prospective data, provenance,
missingness, adjustment, retention, credential, and acquisition contract. This plan grants no
provider contact, credential, request, acquisition, strategy, controlled, PAPER, broker-write, or
live authority. Program 004's paid MarketParquet path is abandoned before purchase.

## Lineage and actual state

Program 002 stopped before strategy execution because its frozen Alpaca contract could not supply
nine required MDY five-minute coordinates and its later source paths failed before strategy work.
Program 003 remained a Tiingo plan. Program 004 remained a MarketParquet plan. Programs 003 and 004
generated and exposed zero strategy returns, Program 004 never bought MarketParquet, and neither
program ran source qualification. The provider changes were not candidate rescue and no return
informed them.

Repository reconstruction started from clean synchronized `main` at
`afe1cfd4ebb71d1cb1eafb3a6a25d05350b45e76`. No Program 002-005 acquisition or research process is
active. One unrelated `intraday-exposed-003` row remains stale: its last heartbeat was August 22,
2026, and recorded PID 20769 is absent. Program 005 records that exception but does not clear another
campaign's runtime state.

The exact Program 004 plan and finding-free review remain immutable and are bound by hash. Program
005 inherits their economic, chronology, search-budget, cost, and protected-control contracts. It
does not reopen Programs 002-004.

## Preserved hypothesis

The twelve ranking and trading ETFs remain IWM, MDY, XLB, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV,
and XLY. SPY remains context and benchmark only. The two families remain sector-relative
continuation and reversal. Their Cartesian product with 30- and 60-minute lookbacks and 2- and
4-hour holds remains exactly eight configurations.

The decision stays at 11:30 New York. The portfolio stays long/flat with at most three equal
fee-safe fractional slots, no leverage, no shorting, no resizing, and no reentry. Entries remain
11:35, 11:40, and 11:45. Two-hour exits remain 13:35, 13:40, and 13:45; four-hour exits remain 15:35,
15:40, and 15:45. The hold begins at the actual entry. A complete early-close session may supply
09:30-11:30 context but cannot be traded because it lacks the exact four-hour exits.

The exposed context remains June 26 through July 24, 2020. Discovery starts July 27, 2020, and the
exposed range ends July 31, 2026. The three discovery blocks, nine folds, training-window P&L ban,
232-specification ceiling, and stopping rules remain unchanged. Controlled A remains April 16
through October 15, 2027. Controlled B remains October 18, 2027 through April 14, 2028. No controlled
or protected range may be acquired or inspected.

## Verified free historical SIP contract

Official Alpaca pages retrieved August 27, 2026 state that Trading API Basic is free, covers U.S.
stocks and ETFs back to 2016, and permits 200 historical API calls per minute. The latest fifteen
minutes are restricted, but the FAQ says a historical request whose explicit `end` is at least
fifteen minutes old may query SIP without Algo Trader Plus.

The selected endpoint is:

```text
GET https://data.alpaca.markets/v2/stocks/bars
feed=sip
timeframe=5Min
sort=asc
limit=10000
asof=2026-07-31
```

Alpaca documents `start` and `end` as inclusive. `limit` applies to all returned points, not each
symbol. A caller must pass each `next_page_token` back as `page_token` until it becomes null. The
reference lists `raw`, `split`, `dividend`, `spin-off`, `all`, and comma-separated combinations.
Every parameter is explicit; no provider default is part of the contract. A committed evidence manifest maps
each claim to a retrieved representation, section, SHA-256, and byte count without copying third-party source
bodies into the repository. The free entitlement and limits must be rechecked before each future authority.
Any paid-plan requirement stops Program 005.

The repository's generic Alpaca adapter cannot be reused unchanged. It defaults to IEX and
`adjustment=all`, and it extends `end` under an obsolete exclusive-end assumption. A future Program
005 adapter needs a separate reviewed authority and mock suite.

## Retention gate

The free transport contract passes. The retention contract does not yet pass.

Alpaca says the Historical API may support charting, backtesting, and trading strategies. Its current
customer agreement also incorporates Nasdaq and NYSE market-data agreements where applicable and
says a customer may not reproduce, distribute, sell, or commercially exploit market data in any
manner without Alpaca's written consent. Both incorporated agreements were accessible during the final
review: they permit personal use and restrict furnishing data to others, but neither expressly grants private
immutable raw-response copies, backups, or retained derived research artifacts.

Program 005 therefore remains contract-gated. Applicable terms or written Alpaca confirmation must
permit noncommercial personal research, private immutable raw pages, private backups, canonical
derived artifacts, and audit reproduction without a recurring paid plan. This plan does not authorize
provider contact.

A hash-only re-fetch design is not an acceptable fallback. Hashes could detect a later correction but
could not reproduce the bytes used by a frozen campaign. Program 005 will not trade exact
reproducibility for a formal zero-storage design.

## Canonical and analytical views

Each authorized chain would be requested twice under one predeclared paired contract:

- `adjustment=raw` is canonical immutable provider evidence and supplies raw contemporaneous fills,
  marks, and P&L inputs.
- `adjustment=split,spin-off` is the frozen analytical OHLCV view for same-session returns, prior
  twenty-session relative volume, and prior median dollar-volume capacity.

The two chains differ only in `adjustment`. A missing bar cannot trigger alternate parameters,
another timeframe, one-minute reconstruction, or a provider switch.

Split-normalized volume puts both sides of a split in one share unit. Analytical price and volume must
scale reciprocally and use one constant factor within each symbol-session. Same-session returns are
unchanged by a constant factor. Fractional equal-dollar sizing and bps-on-notional costs use raw fill
prices, so analytical scaling cannot change target notional, cost, or raw P&L.

Cash dividends are not requested as an adjustment and create no cash credit. Every price feature
starts after the open and every position closes in the same session, so the strategy never owns an
overnight distribution entitlement. A complete ordinary ex-dividend session remains eligible.

The paired analytical view handles documented spin-off price factors. Before dataset freeze, an
issuer- or exchange-backed action ledger must explain every split or spin-off factor change. An
ambiguous effective date, factor, action identity, or factor that changes within a session excludes
the affected session and counts against the loss ceiling. An unresolved ledger fails admission.
Later provider corrections create a new dataset version and cannot overwrite frozen pages.

## Missing-session disposition

Every included session requires the complete 13-symbol regular-session grid needed for the causal
lookback, decision, execution delay, hold, exit, and prior twenty complete-session context. One
missing bar excludes the whole session from every configuration, benchmark, and later context use.
The program never drops one symbol, reranks, fills, interpolates, reconstructs, blends, or replaces a
date.

The five sessions already known to contain nine missing MDY coordinates are a fixed quarantine:

- December 4, 2020
- February 3, 5, 10, and 22, 2021

They stay excluded even if a later response contains every bar. This makes later provider corrections
irrelevant to campaign membership. It also avoids pretending the exposed defect is a random sample
from future provider behavior.

The numeric ceiling is derived separately and before comparing known gaps. Each predeclared discovery
or test block has 125-126 full sessions. One loss is at most 0.8% of a block; two are at least 1.5873%.
The fixed 1% block ceiling therefore separates one isolated loss from two losses without using a return
or a known gap. Apply the same 1% source-loss ceiling to all 1,499 full trade-eligible sessions with a
two-sided 95% exact Clopper-Pearson upper bound. At `p=0.01`, the binomial CDF is
`0.017691212591` for seven losses, below the `0.025` upper-tail alpha, and `0.036959445291` for
eight, above it. Seven is the largest permitted count: exactly `7 / 1499`, about 0.46698%, leaving
at least 1,492 sessions. The prompt's suggested 0.5% is not an input. Only afterward does the fixed
quarantine consume five slots and leave at most two unexpected exclusions.

Unexpected exclusions must be isolated: at most one per calendar year, at most one per fixed discovery or
test block, at most one
per rolling 63 expected sessions, none consecutive or adjacent to another exclusion, and at most one
with the same missing symbol per rolling 252 sessions. No unexpected exclusion may join a block or
rolling-quarter window containing the fixed quarantine, and no new MDY exclusion may join its
rolling-year window. The initial twenty context sessions allow zero loss.

Before admission, a structural report must list exclusions and coordinates by symbol, month, year,
and five-minute time; fixed-block, rolling, contiguous, and same-symbol counts; and all context
completeness. It also ranks every full trade-eligible session by three return-blind SPY 09:30-11:30
metrics: absolute morning return, morning high-low range, and morning volume. Each deterministic
quartile sorts by metric and then date. The tests use the high-return, high-range, and low-volume tails
with Bonferroni alpha `0.05 / 3`. Admission fails at four tail members among five exclusions, five
among six, or five among seven; their exact binomial tail probabilities are `0.015625`,
`0.004638671875`, and `0.01287841796875`. A missing required SPY bar makes the diagnostic
unavailable and fails admission. No reviewer may override or reinterpret the result, and no threshold
may be relaxed after acquisition.

The already-exposed nine gaps may remain absent during source qualification. No other missing
coordinate is allowed on those fixed sessions. Their absence is handled by unconditional whole-date
exclusion, not by tuning a tolerance to nine bars.

## Static costs and historical NBBO

Historical NBBO remains unnecessary. The cost model is unchanged:

| Scenario | Cost per side | Delay | Entry | Two-hour exit | Four-hour exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Normal | 6 bps | 5 minutes | 11:35 | 13:35 | 15:35 |
| Stress A | 12 bps | 10 minutes | 11:40 | 13:40 | 15:40 |
| Stress B | 25 bps | 15 minutes | 11:45 | 13:45 | 15:45 |

Normal also runs at 10- and 15-minute delays and cannot qualify alone. Zero cost is diagnostic only.
Hash-bound issuer pages for all twelve traded ETFs, retrieved August 27, 2026, report 30-day median
full spreads from 0 to 2 bps as of August 26. The plan records each URL, retrieval timestamp, byte
count, SHA-256 value, reported date, and spread, plus a mutable-source warning. Normal's five-basis-point
adverse component is at least five times the largest current median half-spread, before a separate
one-basis-point reserve. This is a conservative planning assumption, not a historical upper bound. It
does not observe episodic adverse selection, latency, impact, queue position, partial fills, or
broker-specific costs. Evidence that the envelope is too low stops the program; later evidence cannot
lower it.

## One-use structural qualification

The qualification is designed but contract-gated and unauthorized. It contains no strategy
calculation. It uses all thirteen symbols, both adjustment views, 120 requests per minute, one
credential load, and twenty-two exact sessions:

- The five fixed MDY quarantine sessions.
- Normal controls on July 27, 2020; July 17, 2023; and July 15, 2026.
- The November 25, 2022 early close.
- June 10-12, 2024 around the fixed IWM distribution control.
- Ten sessions from December 1-12, 2025 around the five issuer-known 2-for-1 sector ETF splits.

The sample has twenty-one full sessions, one early close, 21,840 expected rows per adjustment view,
and 43,680 paired rows before the permitted known gaps. Twelve samples use one-session chains. The
December block contains 10,140 rows per view, so `limit=10000` must exercise real token pagination.
The cap is twenty-six logical chains, sixty HTTP responses, 64 MiB, and one credential load. A
transport failure has no retry under the one-use authority.

A pass requires exact inclusive boundaries, token exhaustion, unique coordinates, valid finite
OHLCV, matching paired coordinate sets, reproducible parse and hash results, constant action factors,
reciprocal split volume, action-ledger reconciliation, and no unexpected missing bar. The nine known
MDY coordinates may exist or remain absent. The five dates stay quarantined in either case.

A pass publishes only a structural receipt. A failure publishes a terminal structural receipt and
stops without alternate parameters or another provider.

## Later full acquisition

Full acquisition remains separate and unauthorized. The range contains 1,531 XNYS sessions: 1,519
full sessions and twelve early closes. One adjustment view contains 1,546,818 expected rows; the pair
contains 3,093,636.

The simple restart boundary is one XNYS session per adjustment view. Reuse the twenty-two qualified
sessions and request at most 3,018 additional chains for the remaining 1,509 sessions. With one page
per chain, 120 requests per minute takes about 25.15 transport minutes plus checkpoints and network
overhead. Each chain is capped at four pages, for a worst-case 12,072 additional responses and about
100.6 transport minutes before backoff. Paired JSON pages are estimated at 0.4-0.8 GiB; the source cap
is 4 GiB and working reservation is 8 GiB.

Each response page is create-only, fsynced, hashed, and bound to its incoming and outgoing token
before an atomic checkpoint advances. Restart verifies every completed page and resumes only the
recorded token. A chain identity cannot publish twice.

Raw and analytical pages, request identities, page tokens, response hashes, retrieval times, actual
bounds, symbol set, source commit, action ledger, missingness report, and canonical dataset hashes
stay under the ignored `.trading-lab/program-005-free-alpaca` root if and only if the retention gate
passes. A correction creates a new version; research never points at a moving provider result.

## Credential boundary

A dedicated unused brokerage account is not required. A smaller fetch process supplies the control:
it loads the key and secret once after exact authority, permits only `GET` to
`https://data.alpaca.markets/v2/stocks/bars`, rejects redirects and every trading origin or path, and
never passes credentials to dataset admission or research workers. Credentials never enter source,
logs, hashes, prompts, fixtures, manifests, or exceptions.

## Admission order and stop conditions

The only valid future order is source qualification, separately authorized full acquisition,
structural missingness report, corporate-action validation, immutable dataset freeze, independent
dataset admission review, exact source/data/cost binding, and separate strategy-execution authority.
No return may exist before dataset admission.

Program 005 stops if free historical SIP changes, a paid plan becomes necessary, retention stays
incompatible, any missingness or concentration ceiling fails, corporate actions remain ambiguous,
pagination or integrity differs, or source behavior changes materially. It does not choose another
provider automatically.

## Exact next authorization

The committed tests construct both full frozen request variants, reject defaults and end extension, and
execute mock-only pagination, completeness, concentration, objective SPY bias, adjustment, credential,
origin, and authority controls. They add no network-capable adapter. The next data authority is not yet
eligible because the retention gate is unresolved. After that gate, a reviewed adapter, green CI, and a
separate user grant, the exact scope may be:

> ONE-USE FREE ALPACA BASIC HISTORICAL SIP STRUCTURAL SOURCE QUALIFICATION ONLY: zero provider
> subscription cost; GET-only data.alpaca.markets/v2/stocks/bars; feed=sip; timeframe=5Min; paired
> adjustment=raw and adjustment=split,spin-off requests; asof=2026-07-31; the exact twenty-two
> sessions and thirteen symbols; at most twenty-six logical chains, sixty HTTP responses, 64 MiB,
> 120 requests/minute, and one credential load; private immutable evidence only under resolved
> retention rights; no remaining chronology acquisition, dataset admission, strategy implementation
> or execution, return observation, controlled or protected access, PAPER action, broker write, or
> live action.

This plan does not grant that authority.

## Sources retrieved August 27, 2026

The auditable claim map is
`config/research/program-005-alpaca-public-contract-evidence-v1.json`.

- [Alpaca Market Data API plans](https://docs.alpaca.markets/us/docs/about-market-data-api)
- [Alpaca Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)
- [Alpaca historical stock bars reference](https://docs.alpaca.markets/us/reference/stockbars)
- [Alpaca Historical API overview](https://docs.alpaca.markets/us/v1.4.2/docs/historical-api)
- [Alpaca customer agreement](https://files.alpaca.markets/disclosures/library/AcctAppMarginAndCustAgmt.pdf)
- [Alpaca disclosures and incorporated agreements](https://alpaca.markets/disclosures)
- [Nasdaq OMX Global Subscriber Agreement](https://files.alpaca.markets/disclosures/library/NASDAQ+OMX+Global+Subscriber+Agreement.pdf)
- [NYSE Market Data Display Services Agreement](https://files.alpaca.markets/disclosures/library/NYSE+Market+Data+Display+Services+Agreement.pdf)
- [iShares IWM issuer page](https://www.ishares.com/us/products/239710/ishares-russell-2000-etf)
- [State Street ETF pages](https://www.ssga.com/us/en/intermediary/etfs)
- [State Street sector ETF split notice](https://investors.statestreet.com/investor-news-events/press-releases/news-details/2025/State-Street-Investment-Management-Announces-Share-Splits-for-Five-Select-Sector-SPDR-ETFs/default.aspx)
