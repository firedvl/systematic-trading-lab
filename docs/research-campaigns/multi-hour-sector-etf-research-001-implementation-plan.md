# Multi-Hour Sector ETF Research 001 implementation plan

Status: **PLANNING ONLY**

Program: `multi-hour-sector-etf-research-001`

Planning base: clean synchronized `main` at
`ad43c3098e6714b3dde934b5c993b415895f8a21` on 2026-08-25.

This document authorizes no market-data request, strategy implementation, strategy run,
qualification, controlled read, PAPER action, broker write, live action, or change to
`strategic-allocation-21`.

Machine-readable inputs:

- `config/research/cross-sectional-sector-etf-program-002-plan-proposal-v1.json`
- `config/research/cross-sectional-sector-etf-program-002-data-acquisition-plan-proposal-v1.json`
- `config/research/multi-hour-sector-etfs-v1.json`

## Executive assessment

Program 002 is implementable without changing the repository's protected research or broker
boundaries. Existing catalog, XNYS validation, Parquet, attempt, publication, and source-review
components are reusable. The current engines are not semantically sufficient: the generic
portfolio engine has uniform costs and sequential target sizing, while the calibrated engine is
frozen to SPY/QQQ and binary half weights. A new program-specific replay path is the smaller and
safer change.

The planning audit resolved the material ambiguities in the strategic proposal:

| ID | Planning issue | Resolution |
| --- | --- | --- |
| P002-001 | Universe provenance and missing XLC explanation | Bind `multi-hour-sector-etfs-v1`; use the ten sector members already present in Rapid-004, plus IWM/MDY; SPY is context only. |
| P002-002 | 11:30 decision and fill clocks | Observe `[11:00,11:30)` at 11:30; create the order afterward; delay 1/2/3 fills at 11:35/11:40/11:45. |
| P002-003 | Missing symbols and bars | Fail the dataset or complete run specification; never shrink the rank or rescale survivors. |
| P002-004 | Early closes | Remain flat; retain a complete morning only as later relative-volume context. |
| P002-005 | Atomic position construction | Size every selected symbol from one pre-fill equity snapshot at one-third per slot; fractional Decimal shares; symbol order affects only ledger order. |
| P002-006 | Campaign meaning | Campaign 1 is continuation; Campaign 2 is reversal and runs regardless of Campaign 1 merit. Controlled evaluation is a later phase. |
| P002-007 | Walk-forward chronology | Freeze nine explicit rolling 252/126/126 folds ending at 2026-07-31; fold 9 is the final exposed fold. |
| P002-008 | Gates and formulas | Freeze return linking, edge, friction, concentration, drawdown, trace, capacity, and accounting formulas; undefined metrics fail. |
| P002-009 | Controlled context collision with V3 | Use the first twenty Block A sessions as in-block volume warmup; acquire no V3 dates for Program 002. |
| P002-010 | Broad-universe costs | Reuse the quote method, not the old numeric spreads; recalibrate all thirteen symbols on fixed exposed dates and fill clocks. |
| P002-011 | Full-investment fee deficit | Reserve preliminary buy-side fees and apply one common quantity scale; cash and quantities cannot depend on symbol order. |
| P002-012 | Controlled authority coupling | Split each block into acquisition-only authority, independent dataset review/binding, and a distinct one-use evaluation authority. |
| P002-013 | Discovery/validation reuse | End all base-selection evidence on 2022-01-21; use the later nine disjoint 126-session folds only for validation. |
| P002-014 | Controlled retry after data read | Atomically consume a specification read grant and write a protected-read receipt; any later failure is terminal. |
| P002-015 | Controlled shared-trace ownership | Make the candidate the sole full-universe trace producer; bind the later benchmark to its create-only trace and SPY-only grant. |

No strategy returns or market records were used to resolve these issues.

## Scope and exclusions

In scope:

- exact prospective mechanics for two families and eight configurations;
- exposed and controlled chronology;
- acquisition, quote-calibration, credential, and storage design;
- portfolio, accounting, reporting, attempt, and launch-control design;
- deterministic synthetic fixtures and tests;
- likely implementation pull-request sequence.

Excluded:

- market-data and quote acquisition;
- executable strategy or runner code in this planning change;
- any backtest, return, candidate, or gate evaluation;
- June 2026, Intraday V3, daily 2018-2019, or protected result reads;
- PAPER, broker, live, or `strategic-allocation-21` state;
- changing Program 001 or restarting an old campaign.

## State and authority baseline

Committed terminal evidence says Intraday Autonomous Research 001 is closed at revision 8, has no
active campaign or active lease, has no permitted campaign capacity, and cannot be repaired,
relaunched, or extended. Every strategy, qualification, controlled, holdout, PAPER, broker-write,
and live authority is false. The Program 002 strategic proposal is also non-authorizing.

The review did not open `.trading-lab`, a protected dataset, a return artifact, or broker state.
The no-active-lease finding is therefore based on the immutable final state and closeout review,
not a new query of a runtime SQLite file.

## Exact strategy contracts

Both families use the twelve-symbol ranking universe:

`IWM MDY XLB XLE XLF XLI XLK XLP XLRE XLU XLV XLY`

SPY supplies the market-relative return and participation-matched benchmark. It cannot enter the
candidate rank or candidate portfolio.

### Shared causal feature path

1. Validate every expected XNYS five-minute bar for all thirteen symbols.
2. Label source bars by UTC open. A source bar becomes observable five minutes later.
3. Aggregate six consecutive source bars into half-hour buckets anchored at 09:30 New York.
4. At 11:30, observe the bucket `[11:00,11:30)`, whose last source bar opens at 11:25.
5. For lookback `L`, compute close-to-close return against the bucket ending 30 or 60 minutes
   earlier.
6. Subtract SPY's same-clock, same-lookback return from each traded symbol's return.
7. Divide the symbol's volume over `[09:30,11:30)` by the arithmetic mean of that sum over the
   immediately preceding twenty complete XNYS sessions.
8. Evaluate the family activation rule for all twelve symbols from one immutable snapshot.
9. Rank exact Decimal residual returns. Use symbol ascending for exact ties.

There is no z-score, cross-sectional mean subtraction, winsorization, volatility scaling, feature
addition, or missing-symbol fallback.

### Family 1: continuation

Family ID: `sector-relative-continuation-v1`

Strategy ID: `multi-hour-sector-relative-continuation-v1`

Economic claim: information absorbed by one sector or capitalization sleeve may continue over a
fixed multi-hour horizon when its SPY-relative return is positive and participation is elevated.

Activation: `residual_return > 0` and `same_clock_relative_volume >= 1.2`.

Rank: residual return descending, then symbol ascending.

Campaign: `multi-hour-sector-etf-continuation-exposed-001`.

### Family 2: reversal

Family ID: `sector-relative-reversal-v1`

Strategy ID: `multi-hour-sector-relative-reversal-v1`

Economic claim: a sleeve displaced at least ten basis points below SPY on high participation may
reflect temporary pressure that reverses over a fixed multi-hour horizon.

Activation: `residual_return <= -0.001` and `same_clock_relative_volume >= 1.5`.

Rank: residual return ascending, then symbol ascending.

Campaign: `multi-hour-sector-etf-reversal-exposed-001`.

### Eight configurations

Each family crosses lookback `{1, 2}` half-hour bars with hold `{4, 8}` half-hour bars. Thirty and
sixty minutes are the only signal horizons. Two and four hours are the only holds. Thresholds are
fixed family constants, not hidden axes.

| Configuration | Family | Lookback | Hold | Immediate neighbors |
| --- | --- | ---: | ---: | --- |
| `src-v1-l1-h4` | continuation | 30m | 2h | `src-v1-l1-h8`, `src-v1-l2-h4` |
| `src-v1-l1-h8` | continuation | 30m | 4h | `src-v1-l1-h4`, `src-v1-l2-h8` |
| `src-v1-l2-h4` | continuation | 60m | 2h | `src-v1-l1-h4`, `src-v1-l2-h8` |
| `src-v1-l2-h8` | continuation | 60m | 4h | `src-v1-l1-h8`, `src-v1-l2-h4` |
| `srr-v1-l1-h4` | reversal | 30m | 2h | `srr-v1-l1-h8`, `srr-v1-l2-h4` |
| `srr-v1-l1-h8` | reversal | 30m | 4h | `srr-v1-l1-h4`, `srr-v1-l2-h8` |
| `srr-v1-l2-h4` | reversal | 60m | 2h | `srr-v1-l1-h4`, `srr-v1-l2-h8` |
| `srr-v1-l2-h8` | reversal | 60m | 4h | `srr-v1-l1-h8`, `srr-v1-l2-h4` |

An immediate neighbor differs on exactly one axis. Every base has exactly two. No diagonal or
cross-family configuration is a neighbor.

## Portfolio and execution semantics

Construction is long/flat, not long/short. Long/short would add borrow availability, locate,
dividend liability, short fee, recall, margin, and PAPER feasibility work without a stronger
prospective rationale. Cross-sectional market adjustment occurs in the signal and benchmark rather
than through a short leg.

Select at most three active symbols. Each receives exactly
`0.3333333333333333333333333333` of the common pre-fill equity snapshot as its pre-fee slot budget.
One selection budgets one-third gross/net exposure; two budget two-thirds; three budget one. Empty
slots stay cash. Exact fractional Decimal shares avoid whole-share ordering effects.

Build the full preliminary quantity vector from adverse-spread-adjusted buy prices. Compute its exact
buy-side fees under the frozen account-day fee model. Subtract that reserve from the occupied-slot
budget and apply one common proportional scale to every preliminary quantity. The reviewed fee
model must prove fees cannot rise when all quantities fall. Recomputed final fees can therefore not
exceed the reserve, so cash stays nonnegative even when all three slots are occupied. The ledger
records symbol order, but all quantities, fees, and cash come from the complete vector. No resize,
reentry, second decision, leverage, or overnight exposure exists.

At 11:30, the completed snapshot creates the entry order. The contemporaneous 11:30 bar open is
ineligible. Delay 1/2/3 fills at 11:35/11:40/11:45. On a successful entry, schedule the complete
exit from the actual fill time. Two-hour exits are 13:35/13:40/13:45; four-hour exits are
15:35/15:40/15:45. Every scenario therefore holds exactly two or four hours, and every full-day exit
precedes 16:00.

Replay assumes a complete fill at the source five-minute open plus or minus the calibrated adverse
half-spread. It has no market-impact, queue-position, or partial-fill model. The one-percent dollar-
volume gate is a feasibility screen, not an impact estimate.

An early-close session is flat. A missing fill bar in a scheduled full session is a data failure,
not a later fill. Entry capacity is one percent of the symbol's median five-minute dollar volume
over every bar in the twenty prior complete sessions. A selected entry above that limit fails the
run instead of dropping the symbol. Exits remain mandatory and report their capacity ratio.

### Cost application

The old SPY/QQQ numeric spread model is not portable to twelve traded ETFs. Reuse only its method:
SIP quotes, latest strictly prior state on a one-second grid, five-second staleness limit, crossed
state exclusion, locked state inclusion, nearest-rank p75/p95/p99, and upward 0.01-basis-point
rounding.

The new Normal scenario uses symbol p75 adverse half-spread and one delay bar. Stress A uses p95 and
two delay bars. Stress B uses p99 and three. Normal-delay-2/3 isolate delay at Normal costs. The
zero-cost scenario removes spread and fees but keeps one delay bar; it can diagnose gross signal
only and grants no authority.

Freeze the broker fee floor before any strategy run. Apply that prospective fee floor to all
historical fills. A later controlled block may only increase a component to a higher then-effective
documented broker pass-through rate; it may not use a decrease. A missing or conflicting fee source
blocks the controlled run.

### Participation-matched benchmark

Generate one cost-free candidate trace per session. It records ranks, selected symbols, selected
count, the 11:30 decision, hold length, and configuration, but excludes scenario-specific fills.
Candidate and benchmark consume the same trace. The benchmark buys SPY at candidate gross weight
`selected_count / 3` and uses the same scenario entry and exact hold interval, fee formula, and SPY
spread. This is its pre-fee budget; its separate account applies the same fee-reserve algorithm and
cash proof. It is cash on inactive sessions.

Exposed reports contain candidate and benchmark ledgers in one specification. A controlled block
pre-registers the exact candidate specification and an immutable benchmark template whose only
deferred field is an explicit null selection-trace identity. The authority binds that template and a
canonical trace-only derivation. Before opening controlled bytes, one transaction verifies the
candidate authority binding, consumes its full-universe grant, and creates its receipt. The candidate
then produces the trace exactly once and create-only publishes its content-addressed bytes. After the
trace and a metric-free candidate status/hash attestation verify, one transaction derives the final
benchmark specification by substituting only the trace identity, verifies it against the template,
registers it immutably, consumes its grant, and creates its receipt before opening the exact trace or
SPY bars. It may then open only that trace and SPY bars at bound fill timestamps;
it cannot load traded-symbol bars, recompute ranks, or create or replace a trace. Both metrics remain
hidden until the trace and both canonical reports verify.

## Chronology

Implementation development uses synthetic data only. The historical market chronology begins with
twenty context sessions from 2020-06-26 through 2020-07-24. Base selection then uses only three
discovery blocks:

| Block | Dates | XNYS sessions | Full trade-eligible sessions |
| --- | --- | ---: | ---: |
| 1 | 2020-07-27 through 2021-01-22 | 125 | 123 |
| 2 | 2021-01-25 through 2021-07-23 | 126 | 126 |
| 3 | 2021-07-26 through 2022-01-21 | 126 | 125 |

Base selection freezes after 377 discovery sessions on 2022-01-21. The nine later test windows are
mutually disjoint 126-session periods beginning 2022-01-24. Their reference training windows roll by
126 sessions, but no training P&L, return, benchmark metric, report, or gate is computed or read and
no parameter is refit. Fold 9, 2026-01-30 through 2026-07-31, is the final exposed fold. Its metrics
remain behind a stage barrier until folds 1-8 pass. No validation or final-fold return can select,
replace, or retune the base.

Controlled A remains 2027-04-16 through 2027-10-15. Its first twenty sessions are sealed context,
so Program 002 does not acquire Intraday V3 dates. Controlled B remains 2027-10-18 through
2028-04-14 and may use only a volume projection from the final twenty Block A sessions. No substitute
range is allowed.

The installed calendar ends at 2027-08-25. A future reviewed dependency update must freeze exact
controlled session tables without changing either date range.

## Gates and stage barriers

The machine-readable plan contains every threshold and formula. The stage sequence is:

1. Run all four family configurations over all three discovery blocks under Normal and zero cost.
2. Select one all-discovery-gate base inside the family by the frozen lexicographic order.
3. Run that base and its two neighbors over folds 1-8 under Normal and zero cost.
4. If the base passes, run the same three configurations on final exposed fold 9.
5. If the base and both neighbors pass all nine-fold gates, run only the base across nine folds under
   Stress A, Stress B, Normal-delay-2, and Normal-delay-3.
6. Freeze at most one serious candidate for that family.
7. After both campaigns finish normally, select at most one controlled cohort using the frozen final
   order.

Campaign 2 runs after a normal empty or serious Campaign 1 outcome. It does not run after a control
breach, contamination, or unresolved deterministic failure. Its parameters and gates cannot react
to Campaign 1.

The two campaigns each cap at 114 specifications: 24 discovery, 54 fold/neighbor, and 36
stress/delay. Controlled A/B cap at four total specifications. The program cap is
`114 + 114 + 4 = 232`, with at most three infrastructure attempts each, or 696 attempts. A retry is
allowed only for an expired infrastructure lease with no result or publication intent.

Discovery requires positive Normal and zero-cost aggregate returns, positive SPY excess, two of
three positive blocks and benchmark wins, at least 60 active sessions per block, 300 round trips,
10 percent maximum intraday drawdown, gross edge of at least `max(5 bps, 3 * friction)`, cost ratio
at most 35 percent, symbol concentration at most 35 percent, exposure-bucket concentration at most
40 percent, block concentration at most 60 percent, no capacity breach, exact traces, and exact
accounting.

Folds 1-8 require six positive folds and five benchmark wins. Final fold 9 must independently be
positive, beat SPY, contain at least 15 active sessions and 30 round trips, and pass all edge, cost,
drawdown, concentration, capacity, trace, and accounting gates. This yields at least seven positive
and six benchmark-winning folds across all nine. Both immediate neighbors must have positive
nine-fold Normal return and median profit retention of at least 50 percent.

Every robustness variant must be profitable in at least seven folds. Stress A and Normal-delay-2
retain at least 50 percent of Normal aggregate profit; Stress B and Normal-delay-3 retain at least
25 percent. No aggregate can rescue a failed disqualifying gate.

For every run period, net profit is final flat cash minus initial cash after spreads and fees.
Aggregate net profit is the sum of those dollar profits across the exact disjoint periods in frozen
order; it is not compounded, averaged, annualized, or formed from overlapping windows. A neighbor's
retention is its nine-fold Normal aggregate net profit divided by the positive base candidate's
matching aggregate net profit. With exactly two neighbors, median retention is the arithmetic mean
of their two exact ratios. Stress or delay retention uses the same formula against the matching
Normal candidate and folds. A missing ledger or nonpositive Normal denominator is undefined and
fails.

## Statistical and sample-size limits

The exposed range contains 1,511 XNYS sessions, of which 1,499 are full and trade-eligible. The 377
discovery sessions select a base before the 1,134 validation sessions begin. One configuration has
17,988 symbol-session feature observations and at most 4,497 round trips across the full program.
Across eight configurations there are 11,992 session/configuration opportunities.

Those are workload counts, not independent samples. The upper-bound sampling unit is one session.
Same-session ETFs share market and sector shocks; configurations share features; training windows
overlap; serial dependence lowers effective observations further. The nine non-overlapping test
folds contain 1,134 sessions. The plan claims no formal power and makes no expected-trade estimate
without market evidence. A survivor must meet the fixed activity floors.

Eight configurations are defensible only as a bounded falsification design: two hypotheses, two
axes, mandatory local neighbors, chronological tests, and one final cohort. Expanding the grid would
require a new program.

## Data acquisition design

The separate acquisition proposal freezes:

- SIP `GET /v2/stocks/bars`, all thirteen symbols, `5Min`, `adjustment=all`, `limit=10000`, and
  page-token pagination;
- three exposed physical datasets with 1,526,538 rows and one separate context-only dataset with
  20,280 rows, for 1,546,818 acquisition rows;
- monthly request segments, exact response-page bytes, canonical raw JSONL, normalized Parquet,
  manifests, SHA-256 values, canonical fingerprints, duplicate detection, and correction lineage;
- project ceilings of ten pages per monthly bar segment and one hundred pages per quote window;
  Alpaca's documented limit is 10,000 total records per page, not either project ceiling, and every
  continuation token must drain through null;
- at most 180 requests per minute, fixed retry classes, five page attempts, and no redirects;
- 73 fixed monthly quote sessions, nine fill clocks, sixty one-second samples per clock, and at most
  512,460 grid observations;
- no IEX fallback, no quote signal use, no trimming of eligible quote outliers, and at least 57 of 60
  eligible samples in every symbol/session/clock window;
- an estimated 0.5-1.0 GB for bars, 1-5 GB for raw quote evidence, and a 10 GB working reservation;
- current estimated provider charge of $0 with an unauthorized $99 one-month contingency, both to
  be rechecked before any request or spend.

The acquisition journal proves the explicit `feed=sip` request, credential/subscription context,
HTTP result and headers, retrieval time, and response hashes. Alpaca documents no response field
that attests the feed, so the validator must not require or infer one. A rejected entitlement stops;
there is no default-feed or IEX fallback.

No precise acquisition duration is supportable without a response-size probe. Fixed throttle alone
is minutes; quote pagination, transfer, validation, retry, and durable publication can extend work
to hours.

Controlled datasets are not part of the next exposed acquisition. After a block ends, its own
acquisition-only authority may publish data but cannot register specifications or inspect returns.
An independent reviewer must bind the exact dataset bytes. Only then may a distinct one-use
evaluation authority bind those dataset IDs. Block B cannot reach even acquisition until Block A
passes and its protected read is logged.

## Credential boundary

Alpaca does not document a data-only key scope that proves separation from trading authority. Use a
dedicated acquisition account/key with no funded live account and no reuse by PAPER or live
processes. Inject secrets from an OS keychain or secret manager into a dedicated OS user or
container. Do not store them in `.env`, source, fixtures, commands, logs, artifacts, manifests, or
prompts.

The acquisition process has one fixed HTTPS origin and GET-only endpoints. It writes only to its
staging/storage root and imports no paper, order, mutation, risk-authorization, or execution module.
After publication, terminate it and run later research workers with the credential variables
removed. If that boundary cannot be established, acquisition stays blocked.

## Existing components to reuse

| Component | Reuse | Evidence |
| --- | --- | --- |
| `domain.py` | `OHLCVBar`, `Symbol`, `Timeframe`, `TimestampRange`, Decimal validation | Existing typed data boundary |
| `calendar.py` | Expected XNYS sessions and 5m bar opens, including early closes | Current fixture proves 78/42 bar grids |
| `universe.py` | Full-range point-in-time membership and fingerprint | Rejects missing or unsupported members |
| `datasets.py`, `storage.py`, `catalog.py`, `parquet.py` | Validation, immutable publish, normalized Parquet, catalog, bounded reads | Existing M1 path |
| `fingerprints.py` | Canonical JSON and SHA-256 identity | Existing artifact identity |
| `strategies.py` | `TargetPosition` value type | Strategy-to-portfolio boundary |
| `research_attempts.py`, `research_executor.py` | Claims, leases, retries, create-only reports, four workers | Existing restart-safe path |
| `intraday_cost_calibration.py` | Quote sampling and eligibility algorithm | Reuse method, not symbols/dates/spreads |
| `intraday_execution_cost_model.py` | Symbol cost scenario and fee concepts | Generalize symbol set; do not edit frozen model |
| `intraday_reporting.py` | Equity, fill, round-trip, fee, concentration concepts | Extend with paired benchmark and exposure bucket |
| `intraday_exposed_003_equivalence.py` | Sequential/parallel exact-byte comparison pattern | Existing process equivalence proof |

Do not modify frozen Program 001, Exposed 002/005, event, V2, V3, qualification, paper, broker, or
execution artifacts to make Program 002 fit.

## New components required

Names below are proposed boundaries. A later implementation may combine two adjacent files when the
result stays clear and tests remain focused.

| File/module | Purpose | Research semantics | Tests |
| --- | --- | --- | --- |
| `src/systematic_trading_lab/multi_hour_sector_etf_plan.py` | Strictly load the reviewed plan, universe, grids, folds, gates, and false authority | Yes; exact identities and stage graph | Identity, duplicate keys, authorities, grid, neighbors, folds, budget |
| `src/systematic_trading_lab/multi_hour_sector_etf_features.py` | Pure 5m-to-30m aggregation, prior-volume snapshot, residual return, rank, and targets | Yes | Aggregation, cutoff, relative return/volume, ties, invalid input, early close |
| `src/systematic_trading_lab/multi_hour_sector_etf_engine.py` | Atomic multi-symbol fills, slot sizing, timed exits, symbol costs, fee allocation, capacity, benchmark, equity | Yes | Cash/order independence, holds/delays, costs, exits, drawdown, benchmark, accounting |
| `src/systematic_trading_lab/multi_hour_sector_etf_runner.py` | Range binding, report schema, gates, campaigns, attempts, stage barriers, freezes, parallel execution | Yes | Run derivation, screening, budget, retries, deterministic reports, restart/publication |
| `src/systematic_trading_lab/program_002_acquisition.py` | Fixed SIP segmentation, retry journal, page-byte retention, quote windows, context projections | Bars/quotes only; no return semantics | Mock transport, pages, retries, hashes, duplicate/correction, credential scrubbing |
| `src/systematic_trading_lab/multi_hour_sector_etf_launch_control.py` | Later exact merged-main/data/cost/source/authority binding | Control only | Reject every missing/mismatched/false prerequisite; synthetic launch equivalence |

Shared changes should stay small:

- `providers.py`: permit an explicit reviewed `sip` feed and `limit=10000` while preserving the IEX
  default for existing callers; expose exact response bytes to the acquisition journal without
  changing normalized records.
- `datasets.py` and `storage.py`: accept optional provider page artifacts and manifest evidence in
  the same atomic create-only publication. Existing providers continue with no extra artifacts.
- `cli.py`: only after acquisition authority design is approved, add a Program 002 acquisition
  command that requires an exact authority artifact and dedicated credential environment. Do not
  add a strategy-run command until a later execution authorization.

No database migration should touch existing campaign tables. Use a disjoint Program 002 namespace
inside the research-attempt database or a separate Program 002 SQLite file.

## Synthetic validation contract

Build one deterministic generator with 22 XNYS sessions, all thirteen symbols, exact five-minute
grids, Decimal prices, and integer volumes. Twenty sessions establish prior volume. One normal
session carries known continuation, reversal, and exact-tie cases. One early-close session proves
flat behavior and context eligibility. Mutations create one missing bar, one missing symbol, one
duplicate, and one invalid denominator.

The smallest required checks are:

1. Six source bars aggregate to exact open, high, low, close, and volume.
2. The 11:30 decision can see the 11:25 source close but cannot see the 11:30 open or any later bar.
3. SPY-relative returns and twenty-session same-clock volume match hand-computed Decimals.
4. Equal residual returns rank by symbol; relative volume does not break a tie.
5. A missing symbol/bar, duplicate, invalid price, or zero denominator fails the full input.
6. One/two/three selected symbols receive one/two/three pre-fee slots, then one common fee-reserve
   scale keeps cash nonnegative without changing their relative weights.
7. Reversing input symbol order leaves fee reserve, scale, quantities, cash, fills, metrics, and
   report bytes unchanged.
8. The 11:30 bar open is never eligible; delay 1/2/3 produces entry clocks 11:35/11:40/11:45 and
   exits exactly two/four hours after each actual entry.
9. An early close remains flat but may enter a later prior-volume denominator.
10. Higher spread, fee, or delay never improves fixed-trace net P&L through accounting error.
11. The controlled candidate receipt precedes the sole full-universe trace read and exactly one
    create-only trace publication. The benchmark binds that hash, opens the trace only after its own
    receipt, reads SPY fill bars only, and cannot recompute or replace the trace.
12. Turnover, gross edge, friction, drawdown, symbol/bucket/block concentration, and capacity match
    hand calculations.
13. A repeat produces the same semantic trace, report fingerprint, and canonical bytes.
14. One-worker and four-worker runs produce identical specification sets and report bytes.
15. Exposed expired no-result work retries at most twice. Controlled crash tests cover before the
    candidate receipt, after its read, after trace intent, after trace publication, before the
    benchmark receipt, and after its SPY read. Only pre-receipt failures retry; every post-receipt
    failure is terminal without a second read.
16. Restart reconciles retained trace/report publication intents only from durable exact bytes;
    create-only conflict blocks completion; exactly one trace and one canonical report per
    specification exist.
17. Block A's first twenty sessions cannot produce a target or P&L; neither block's acquisition
    authority can start evaluation; Block B cannot open without a passing Block A authority chain.
18. No strategy or acquisition path imports broker mutation code or receives broker credentials.

Run only these synthetic and mock-transport checks before any data or strategy authority. They
produce no market-return evidence.

## Implementation phases and likely PR sequence

### PR 1: planning artifacts

This change. Freeze mechanics, acquisition plan, implementation plan, structural tests, state
update, and independent planning review. It stays non-executable.

Completion: all JSON parses with no duplicate keys; cross-artifact identities, false authorities,
configuration graph, chronology, and budgets agree; independent review has no finding.

### PR 2: mock-only data boundary

Requires future implementation authority, not acquisition authority.

Add explicit SIP configuration, monthly segmentation, raw page evidence, manifest extension,
context projections, fixed project page ceilings, credential scrubbing, and mock-only tests. Do not
use credentials or the network.

Completion: mocked pagination/retry/validation/publication tests pass; request evidence binds SIP
without inventing a response feed field; existing providers and data tests are unchanged; no
acquisition command can run without a later authority artifact.

### PR 3: synthetic strategy and replay

Requires future implementation authority.

Add strict plan loading, aggregation/features, ranking/targets, atomic replay, cost/fee/capacity,
benchmark, metrics, and the 22-session fixture. Do not load real market data.

Completion: every synthetic mechanic above passes; normal and adverse input order yield identical
bytes; no broker or protected module import exists.

### PR 4: runner, reports, and launch controls

Requires future implementation authority.

Add immutable specifications, stage coordinator, gates, campaign succession, four-worker execution,
restart recovery, source review, and a launch control that remains false without exact later
authority and data/cost bindings.

Completion: sequential/parallel/restart/exactly-once tests pass; the 232/696 ceilings cannot be
exceeded; no market run can start.

### PR 5: exposed acquisition and cost freeze

Requires a separate user authorization for exposed acquisition only after PRs 2-4 pass independent
review. Acquire three exposed bar datasets, one separate context-only dataset, and the fixed quote
windows. Validate, publish, bind, and freeze a new thirteen-symbol cost model. Do not run a strategy.

Completion: exact expected row counts, raw/page hashes, Parquet fingerprints, quote coverage, fee
sources, and independent data review pass. Any failure stops before a strategy reservation.

### PR 6: exposed strategy launch binding

Requires a later user strategy-execution authorization. Bind exact merged main, plan, source,
datasets, cost model, registry, reports, budget, and worker equivalence. A finding-free launch review
must pass before reserving Campaign 1.

Completion: one exact authority can reserve only the two frozen exposed campaigns. It cannot open
controlled data, qualify, promote, or execute PAPER.

Controlled A and B use separate future PRs and authorities after their dates. PAPER remains a still
later program.

## Launch-control procedure

A future exposed launch must fail closed unless all of these match exact reviewed bytes:

1. clean synchronized `main` and a GitHub-attested source commit;
2. Program 002 plan, universe, implementation, and independent reviews;
3. three exposed dataset manifests plus the context-only manifest, raw/page hashes, normalized
   fingerprints, and context projection;
4. new quote-calibration analysis and thirteen-symbol cost model;
5. strict report schema, gate implementation, campaign graph, 232-spec budget, and attempt policy;
6. one-worker/four-worker synthetic equivalence and restart/publication checks;
7. a one-use user authority that grants exposed strategy execution only;
8. false controlled, protected, PAPER, broker-write, and live authority;
9. a worker environment with no Alpaca or broker credentials;
10. no active old campaign, no Program 001 repair/relaunch path, and no protected-range binding.

Reservation consumes the launch authority atomically. Campaign 2 succession is fixed. Any source,
plan, data, cost, report, registry, or authority mismatch stops before a data read or claim.

## Runtime and resource estimate

The program has fewer maximum specifications than Intraday Exposed 005 (232 versus 272) but about
6.5 times as many symbols per timestamp. It makes one decision per session, so feature and target
logic are simpler than frequent five-minute families. These effects point in opposite directions;
prior campaign timings cannot support a precise estimate.

Use four workers only after a synthetic benchmark. Range-load each fold or block from Parquet rather
than reading all six years per worker. Set an initial verification target below 1 GB resident memory
per worker and below 4 GB for the four-worker pool; measure before launch and lower worker count if
the target fails. This is an operational target, not a claim about the final implementation.

Long runs must remain resumable through SQLite claims, heartbeats, attempt journals, and canonical
publication. Do not hold a model turn or terminal session open as the only record of progress.

## Controlled evaluation procedure

At most one frozen candidate reaches controlled evaluation. After 2027-10-15, Block A first needs
an acquisition-only authority that binds the exact request and grants no strategy or result-read
power. Acquisition publishes immutable data. An independent reviewer then validates and binds every
raw page, manifest, normalized artifact, session table, row count, fingerprint, and isolation
control. A separate one-use evaluation authority must name those reviewed dataset IDs, the frozen
candidate specification, an immutable benchmark template and canonical derivation rule, plan and
source hashes, cost model, gates, and report schema. The template binds every benchmark field except
an explicit null selection-trace identity; the authority binds its exact SHA-256 and fingerprint.
The authority contains a candidate full-universe grant and a template-bound benchmark SPY-only
grant. The candidate runs first and is the sole trace producer. In one transaction before
opening controlled bytes, it consumes its grant and writes a receipt that binds the attempt,
specification, symbols, dataset, range, source, plan, cost model, and report schema. It then reads the
full universe, produces the scenario-independent selection trace once, commits a publication intent,
and create-only publishes canonical content-addressed trace bytes. The benchmark cannot start until
that trace and a separate candidate terminal-status/report-hash attestation verify without exposing
metric bytes. The final benchmark specification is the canonical template with only its null trace
identity replaced by the trace path, SHA-256, and fingerprint. Any other byte difference is terminal.
One transaction re-derives and verifies that final specification, registers it immutably, consumes
its grant, and creates its receipt before opening the trace bytes. The benchmark then opens only the
exact trace and the SPY fill bars named by it. It cannot enumerate other symbols, compute features or
ranks, or create or replace a trace.

An expired lease may retry only before its receipt. A timeout, lease loss, process loss, trace/report
loss, or publication loss after it is terminal and cannot reread the block. Deterministic
reconciliation may finish an already committed trace or report publication intent only from durable
exact bytes without reopening data. Metrics stay hidden until both reports verify. A separate logged
read applies the frozen gates.

Any Block A failure stops. A pass grants no Block B authority. Block B remains unacquired until
after 2028-04-14, Block A passes every gate, and its protected read is logged. Block B then repeats
the acquisition-only authority, independent dataset review/binding, and separate evaluation
authority sequence. Both blocks must pass independently. No reselection, retuning, substitute
range, rerun, gate change, aggregate rescue, or controlled-result feature addition is allowed.

## Researcher-degrees-of-freedom audit

The plan fixes universe, roles, two families, thresholds, features, decision, delays, holds, weights,
neighbors, folds, final exposed period, costs, gates, campaign succession, final selection, controlled
ranges, retries, and stop rules. A later material change requires a new program ID and new authority.

The remaining choices are implementation details that cannot alter semantics: private function
names, test helper layout, log formatting, and whether adjacent program-specific modules are combined.

## Verification plan

For each implementation PR, run the smallest affected synthetic/mock tests first, then:

```console
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
uv run python scripts/check_secrets.py
bash -n scripts/*.sh
uv build --wheel
```

No command in this planning phase may invoke acquisition, a strategy runner, a backtest, a protected
loader, PAPER, or a broker.

## Coverage ledger

| Area | Status | Evidence or limit |
| --- | --- | --- |
| Git and Program 001 state | Inspected | Clean base and immutable revision 8/closeout records |
| Strategic review and proposal | Inspected | Full human and machine-readable artifacts |
| Research/data/architecture/threat policies | Inspected | Repository policy files |
| Universe provenance | Inspected | Rapid-004 final universe and new proposed universe |
| Five-minute data/calendar/storage | Inspected | Provider, dataset, validation, Parquet, calendar code and tests |
| Cross-sectional portfolio support | Inspected | Generic portfolio and calibrated SPY/QQQ engines |
| Relative-volume precedent | Inspected | Closed Relative Volume strategy and tests |
| Costs and quote calibration | Inspected | Calibration v2, cost model, official current sources |
| Attempts, concurrency, restart, publication | Inspected | Attempt store, executor, equivalence, tests |
| Reporting and concentration | Inspected | Backtest and intraday reporting code |
| Qualification, holdout, PAPER, broker | Sampled for boundaries only | No state, credentials, data, or result access |
| Protected market data and returns | Excluded | Prohibited by planning authorization |
| Live provider behavior | Excluded | No credentials or market-data request authorized |
| Controlled future calendar counts | Blocked | Installed calendar ends before both blocks complete; dates remain frozen |

## Exact next decisions

After this planning change is merged, none is automatic:

- **A. Exposed historical acquisition only:** authorize the three exposed bar datasets, separate
  context-only dataset, and fixed quote windows after mock-only acquisition code and review; no
  strategy implementation or run.
- **B. Implementation only:** authorize PRs 2-4 with synthetic/mock data only; no network request or
  market run.
- **C. Acquisition plus implementation:** authorize A and B together, while strategy execution,
  controlled evaluation, qualification, PAPER, broker writes, and live remain false.
- **D. Reject or revise Program 002:** acquire nothing and implement nothing.

Strategy execution requires a later fifth choice after data, costs, source, launch control, and an
independent review exist. Controlled A, Controlled B, and PAPER each require still later choices.
