# Rapid-004 expanded-universe final report

## Outcome

**AUTONOMOUS RAPID-004 COMPLETE — EXPANDED UNIVERSE EXHAUSTED WITH NO
CONTROLLED-QUALIFIED CANDIDATE**

The frozen exposed campaign completed 629 parent records with zero failures. It tested every
required A–U family. Thirty-five identities completed all three fixed blocks, but none passed every
visible-base gate. Every selected identity failed the frozen sleeve-concentration limit. The serious
set, uniform-screen set, and simultaneously frozen final cohort are therefore empty. The campaign
created no controlled plan and inspected no controlled result.

This is historical simulated evidence, not a claim of future profitability.

## Identity and Git delivery

- Program: `rapid-004-expanded-universe`.
- Starting main: `a8312b641d0dcfec4933c735b593b346c27eb564`.
- Exposed research source main: `ff0e80d1a090b7bf0159349753ab5704a73ca39c`.
- Predeclaration SHA-256:
  `28f97126d49a9f0f092f2c8159d5b7c48a14a4e5b7ba850c2e58dfd9b6c64996`.
- Final closeout main: attested after merge by annotated tag `rapid-004-closeout-v1`.

| PR | Merge commit | Purpose |
| --- | --- | --- |
| #133 | `712d6aba333c9d26b6c564a611e29bb59cbab400` | Predeclare the 40-ETF candidate universe |
| #134 | `a9a001d7fa064f2fd208853b0eafa46c43f93a25` | Add the read-only Yahoo acquisition fallback |
| #135 | `56e6225f8b4cf6a18e90a03cf33bb82e353551b5` | Preserve canonical Yahoo raw evidence |
| #136 | `5f8696126665b1fb841da5a7abb6ba963d82480a` | Preserve adjusted OHLC relationships under rounding |
| #137 | `8fb8f60121f4e602c9a02a67e65d21f69f8ad106` | Freeze the 37-ETF final universe and dataset |
| #138 | `450a7d789398b89b41fa00633ab245173cab6133` | Freeze benchmarks, A–U grids, chronology, gates, and budget |
| #139 | `ff0e80d1a090b7bf0159349753ab5704a73ca39c` | Add the dedicated frozen-plan campaign runner |

The closeout PR and merge SHA are recorded by `rapid-004-closeout-v1`. The tag also records final
open-PR and branch counts, evidence hashes, and protected-state confirmations without creating a
recursive requirement for this committed report to contain its own merge SHA.

## Universe selection and data

The 40-symbol seed pool was:

`SPY QQQ IWM DIA MDY IWD IWF IVE IVW MTUM QUAL USMV VLUE XLK XLF XLE XLV XLI XLP XLY XLU XLB XLRE EFA EEM VWO VGK EWJ TLT IEF SHY TIP LQD HYG AGG EMB GLD SLV DBC VNQ`

All 40 symbols had 614 complete XNYS sessions and passed the inclusive $10 million median daily
dollar-volume screen from 2020-07-27 through 2022-12-30. Three duplicate representatives were
excluded using the predeclared first tie-breaker, exact median dollar volume:

- IVE: IWD won the large-value pair,
  `352163890.08026121515 > 96822387.248229976975`.
- IVW: IWF won the large-growth pair,
  `401941165.0344848514648 > 136298953.24249267578125`.
- VWO: EEM won the emerging-markets pair,
  `1665961756.5429688455365 > 461495005.2288055499437`.

The frozen final universe was:

`SPY QQQ IWM DIA MDY IWD IWF MTUM QUAL USMV VLUE XLK XLF XLE XLV XLI XLP XLY XLU XLB XLRE EFA EEM VGK EWJ TLT IEF SHY TIP LQD HYG AGG EMB GLD SLV DBC VNQ`

Its category, sleeve, economic-exposure, inception, and disposition records are in
`config/research/rapid-004-final-universe-v1.json`.

- Final universe ID: `rapid-004-expanded-final-universe-v1`.
- Universe fingerprint:
  `d57039d3a172337c78ad8206644feeb72d76d124ce33a4e5cbe4733dbb2e94e3`.
- Provider: `yahoo-chart-v8`; feed: none.
- Adjustment policy: `yahoo-adjusted-ohlc-v1`.
- Exposed range: 2020-07-27 through 2026-07-31, inclusive.
- Dataset ID: `450e329a8f11f1bd19dcc37ac417b2c59a262e875723eb668332beb22c48d3ff`.
- Dataset fingerprint:
  `ac506268e019a03f7e9e202858171141c3f2d63fc88e03649a1dda091ac47304`.
- Coverage: 37 symbols, 1,511 sessions, 55,907 adjusted daily bars.
- Validation: full immutable catalog, normalized Parquet, raw JSONL, identity, symbol, range,
  duplicate, ordering, and value checks passed before the first run row.

Universe selection used inception, product structure, data completeness, liquidity, and duplicate
exposure only. The final-universe artifact records `performance_fields_calculated: []` and
`strategy_results_inspected: false`. No return, Sharpe, momentum, drawdown, or strategy result
informed inclusion or exclusion.

## Benchmarks and execution

The benchmark suite was frozen before candidate results:

- cash;
- SPY buy-and-hold;
- QQQ buy-and-hold;
- fixed 40% SPY, 20% EFA, 30% AGG, 10% GLD, rebalanced every 21 sessions;
- unchanged `strategic-allocation-21` historical reference.

Full exposed-range Normal results:

| Benchmark | Return | Sharpe | Max drawdown | Turnover |
| --- | ---: | ---: | ---: | ---: |
| Cash | 0.00% | — | 0.00% | 0.00 |
| SPY buy-and-hold | 151.43% | 0.999 | 24.50% | 1.00 |
| QQQ buy-and-hold | 174.38% | 0.855 | 35.12% | 1.00 |
| Static 40/20/30/10 gate | 79.73% | 0.971 | 20.85% | 2.53 |
| `strategic-allocation-21` reference | 145.23% | 0.971 | 25.69% | 3.05 |

Normal execution used 5 bps slippage, 1 bp commission, and a one-bar delay. Stress A and B remained
frozen at 10/2 bps slippage/commission with two bars and 20/5 bps slippage/commission with three
bars. They were not run because no identity passed the prerequisite visible-base gate.

## Implementations added

The campaign added one local-only portfolio strategy factory with 20 frozen mechanics contracts:

`ranked-equal-v1`, `ranked-inverse-volatility-v1`, `dual-momentum-v1`, `multi-horizon-v1`,
`multi-horizon-inverse-volatility-v1`, `trend-relative-strength-v1`, `independent-trend-v1`,
`independent-trend-inverse-volatility-v1`, `channel-breakout-v1`,
`channel-breakout-inverse-volatility-v1`, `equity-bond-gold-regime-v1`,
`inverse-volatility-allocation-v1`, `hierarchical-sleeve-v1`, `breadth-scale-v1`,
`one-per-sleeve-v1`, `defensive-breadth-v1`, `normalized-mean-reversion-v1`,
`core-satellite-v1`, `signal-consensus-v1`, and `fixed-weight-configured-v1`.

It also added:

- the dedicated `Rapid004CampaignRunner` with fixed `plan`, `status`, and `run` actions;
- full dataset and raw-evidence validation before row creation;
- exact benchmark, global stage, parent-budget, child-link, resume, report, and cohort checks;
- an opt-in FIFO for independent trend and breakout state changes so 1/2/3-bar fills retain their
  original signal timestamp while ordinary portfolio backtests keep pending-order rejection;
- training-state replay for breakout walk-forward starts;
- a full-universe fixed-weight benchmark and a zero-expanding adapter around the unchanged
  `StrategicAllocationPortfolioStrategy`.

No ordinary strategy-registry entry, controlled bridge, broker path, or new dependency was added.

## Campaign ledger

- Benchmarks: 20 parents, five benchmarks over the full range and three fixed blocks.
- Discovery: 356 parents; every frozen discovery configuration completed.
- Conditional confirmation: 148 parents. B, I, P, and S did not activate confirmation; the other
  17 families completed their whole frozen confirmation grids.
- Fixed blocks: 35 selected identities × three blocks = 105 parents.
- Total parent configurations: 629 of the predeclared 2,452 maximum and 3,000 hard ceiling.
- Walk-forward folds: 0.
- Parameter-neighbor runs: 0.
- Isolated sensitivity runs: 0.
- Combined stress runs: 0.
- Total Rapid rows: 629 completed, zero failed, zero pending; all rows are parents.

Early rejection explains the zero later-stage counts. The frozen plan requires an identity to pass
every visible-base gate across all three fixed blocks before it becomes serious. None did, so later
execution would have violated stage prerequisites rather than added useful evidence.

## Family results

`D/C` is discovery/activated-confirmation count. `Blocks` counts identities, each with three block
parents. The reported strongest point is the machine report's full-range representative; returns,
drawdowns, and gate excess are percentages. These are exploratory results, not controlled evidence.

| Family | D/C | Blocks | Strongest full-range configuration | Run | Return / Sharpe / DD / gate excess |
| --- | ---: | ---: | --- | --- | ---: |
| A cross-sectional relative strength | 30/24 | 1 | `relative-strength {lookback=126, selection_count=1, rebalance_every=5}` | `rr-b13ac64854f97397e946` | 268.26 / 0.841 / 42.45 / 188.53 |
| B dual momentum | 24/0 | 1 | `dual-momentum-treasury-gold {short_lookback=20, long_lookback=63, selection_count=2, rebalance_every=21}` | `rr-0200782891e177cde9b7` | 76.84 / 0.614 / 34.32 / -2.89 |
| C tactical multi-asset allocation | 24/12 | 5 | `tactical-multi-horizon-momentum {short_lookback=40, long_lookback=126, selection_count=2, rebalance_every=10}` | `rr-c2e909fdb6b19f6de7c6` | 124.03 / 1.092 / 10.56 / 44.30 |
| D sector rotation | 18/8 | 1 | `sector-trend-relative-strength {lookback=252, selection_count=1, rebalance_every=5}` | `rr-edfc4071ee307a5602b7` | 273.95 / 1.079 / 26.04 / 194.21 |
| E style/factor rotation | 18/8 | 5 | `style-relative-strength {lookback=63, selection_count=1, rebalance_every=21}` | `rr-424108487a0a5e9d11cf` | 155.91 / 1.037 / 30.79 / 76.18 |
| F international rotation | 12/8 | 1 | `international-relative-strength {lookback=126, selection_count=2, rebalance_every=21}` | `rr-fbfc4d2bd268a8d6eda6` | 73.52 / 0.758 / 13.74 / -6.22 |
| G bond-duration rotation | 18/8 | 1 | `bond-relative-strength {lookback=189, selection_count=2, rebalance_every=21}` | `rr-3cb0a249377c46cd9053` | 17.45 / 0.548 / 10.11 / -62.29 |
| H equity/bond/gold regime | 18/8 | 1 | `equity-bond-gold-regime {trend_window=84, volatility_window=84, volatility_limit_percent=25, rebalance_every=5}` | `rr-f4fb3e8e3cc066dfdec5` | 71.35 / 0.912 / 11.46 / -8.39 |
| I multi-asset trend | 12/0 | 1 | `multi-asset-trend {window=189}` | `rr-35af888eef9c738dc7a3` | 27.94 / 0.631 / 10.86 / -51.80 |
| J multi-asset breakout | 12/6 | 1 | `tactical-inverse-volatility-breakout {entry_window=126, exit_window=63, volatility_window=63}` | `rr-7d821d438d650afdd582` | 43.89 / 0.748 / 11.40 / -35.84 |
| K volatility-weighted momentum | 18/8 | 3 | `ranked-inverse-volatility-momentum-cap50 {lookback=252, selection_count=3, volatility_window=84, rebalance_every=21}` | `rr-9690cde20b473eda150e` | 149.69 / 0.956 / 19.07 / 69.96 |
| L risk parity/inverse volatility | 12/6 | 1 | `volatility-balanced {volatility_window=63, rebalance_every=21}` | `rr-ceba109cb20238c4796e` | 45.06 / 0.825 / 17.27 / -34.67 |
| M hierarchical/sleeve allocation | 12/8 | 1 | `hierarchical-sleeve-allocation {lookback=126, rebalance_every=5}` | `rr-c1b8bdd10fcf4d5deeaf` | 93.88 / 0.906 / 14.30 / 14.15 |
| N breadth regime | 18/8 | 1 | `breadth-regime {trend_window=189, breadth_threshold_percent=40, rebalance_every=21}` | `rr-37f22472f2b0f387a57b` | 39.45 / 0.873 / 8.43 / -40.28 |
| O diversification-constrained rotation | 18/8 | 1 | `diversified-rotation {lookback=84, selection_count=2, rebalance_every=21}` | `rr-b715471da4a22ee41f3c` | 190.85 / 0.930 / 30.89 / 111.11 |
| P multi-horizon momentum | 20/0 | 1 | `multi-horizon-momentum {short_lookback=20, long_lookback=63, selection_count=1, rebalance_every=5}` | `rr-79a04c6aabd668a73a7c` | 196.99 / 0.772 / 36.85 / 117.25 |
| Q trend + relative strength | 18/8 | 1 | `trend-relative-strength {rank_lookback=126, trend_window=126, selection_count=1, rebalance_every=5}` | `rr-7da7e3a57263f13d27ef` | 205.08 / 0.746 / 44.44 / 125.35 |
| R defensive breadth/crisis | 18/8 | 1 | `defensive-breadth-ranked {trend_window=84, breadth_threshold_percent=40, rebalance_every=5}` | `rr-832e2005f87b85ab068f` | 53.75 / 0.885 / 16.95 / -25.98 |
| S cross-sectional mean reversion | 12/0 | 1 | `cross-sectional-mean-reversion {reversal_lookback=10, trend_window=63, selection_count=1, rebalance_every=5, volatility_window=20}` | `rr-c2d48dd010ca39b3551e` | 28.02 / 0.327 / 38.49 / -51.71 |
| T static core + tactical satellite | 12/6 | 1 | `static-core-tactical-satellite {core_weight_percent=90, tactical_lookback=63, selection_count=1, rebalance_every=21}` | `rr-8c53443b5444ac16f497` | 74.74 / 0.959 / 19.63 / -5.00 |
| U ensemble/consensus | 12/6 | 5 | `signal-consensus {momentum_lookback=126, breadth_threshold_percent=80, selection_count=1, trend_window=126, rebalance_every=21}` | `rr-d9292bbc05fde71c0860` | 101.17 / 0.704 / 26.40 / 21.43 |

No additional family was added. All A–U ledger statuses are `TESTED`; zero-confirmation families
completed discovery and were explicitly stopped by the predeclared activation rule.

## Gate, benchmark, cost, and concentration findings

Ten family full-range maxima beat the static gate benchmark. That result did not persist as a
complete fixed-block gate pass. Non-exclusive visible-base failures across the 35 selected
identities were:

| Failed metric | Identities |
| --- | ---: |
| Maximum sleeve profit share | 35/35 |
| Maximum top-instrument profit share | 29/35 |
| Worst validation Sharpe | 28/35 |
| Gate-benchmark win rate | 19/35 |
| Positive-fold rate | 12/35 |
| Worst validation return | 12/35 |
| Maximum validation drawdown | 11/35 |
| Total validation trade count | 4/35 |
| Maximum turnover | 1/35 |

No identity failed block count, gross exposure, top-five session concentration, or regime-session
coverage. Sleeve concentration was decisive. Even the hierarchical and diversification-constrained
families could not hold every fixed block below the unchanged 50% sleeve-profit limit.

Turnover and cost were secondary but material for some full-range maxima:

- S mean reversion: turnover 501.69; cost paid $30,101.34.
- P multi-horizon momentum: turnover 424.35; cost paid $25,461.00.
- A relative strength: turnover 222.22; cost paid $13,333.19.
- Q trend-relative strength: turnover 221.22; cost paid $13,273.22.

Instrument concentration failed 29 of 35 selected identities; sleeve concentration failed all 35.
No candidate earned neighbor, walk-forward, sensitivity, or stress execution. The campaign therefore
makes no parameter-plateau or stress-retention claim and did not spend compute polishing known
fixed-block failures.

## Final screen, cohort, and controlled qualification

- Serious identities: zero.
- Complete uniform-screen candidates: zero.
- Uniform-screen passes: zero.
- Final frozen cohort: empty.
- Frozen candidate parameters: none.
- Controlled plans: none; empty controlled-plan-list fingerprint
  `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.
- Controlled qualification attempts: zero.
- Controlled PASS/FAIL results: none.
- Controlled failed gates: not applicable; no controlled run was authorized.
- Successful qualification fingerprints: none.
- Best controlled-qualified candidate: none.
- Runner-up: none.
- Recommended candidate for the independent range: none.

The cohort freeze was written once before any controlled result and contains an empty cohort and
empty controlled-plan list. The predeclared rule requires the program to stop here.

## Evidence

- Exact exposed report:
  `.trading-lab/rapid-004/rapid-004-exposed-report-v1.json`.
  SHA-256 `dde2323b9e46f954b16619522547c0360073b1515012a19745ba0385a38852be`;
  report fingerprint `4d2f2be597785baf86765431edcf9c68b565d8e23bfb4fa38b17a3442b46e6ad`.
- Exact cohort freeze:
  `.trading-lab/rapid-004/rapid-004-cohort-freeze-v1.json` and committed byte-for-byte mirror
  `config/research/rapid-004-cohort-freeze-v1.json`.
  SHA-256 `c42f0de99fa04f6d90a77d73821b5db0aea6b91b0ceae195bcc80dbf3110b346`;
  cohort fingerprint `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.
- Rapid database: `.trading-lab/rapid-004/rapid-research.sqlite3`.
  SHA-256 `60d52e067a098450a137936fa050b6f1d4cdc74175896ff41eb402dad9d93c28`.
- Per-run reports: `.trading-lab/rapid-004/rapid-research/reports/`, 629 canonical JSON files.
- Machine strategy ledger: `config/research/rapid-004-strategy-ledger-v1.json`.

Strict status validation re-read all stored specifications and canonical report bytes after the run.
Database counts, source commit, campaign hashes, dataset identity, report counts, and artifact hashes
reconciled.

## Protected-state audit and stop condition

All 629 rows use the one frozen dataset, fingerprint, predeclaration, campaign, and clean source
commit. Their minimum start is 2020-07-27 and maximum end is 2026-07-31. Metadata overlap queries
returned zero rows for 2018-01-02 through 2019-12-31 and zero for the V3 range. There were no child,
walk-forward, sensitivity, stress, controlled, holdout, paper, broker, live, or promotion rows.

The tracked diff since starting main contains no V3, PAPER, broker, order, risk, execution,
reconciliation, or controlled-qualification mutation. `src/systematic_trading_lab/strategies.py` is
unchanged, so `strategic-allocation-21` is unchanged; the benchmark adapter only called the existing
implementation. No independent-range or V3 market data or result was loaded. No PAPER, broker, or
live state was read or mutated.

Rapid-004 is closed. Do not reinterpret its empty cohort, run pointless controlled plans, access the
2018–2019 independent range, or start Rapid-005 automatically.
