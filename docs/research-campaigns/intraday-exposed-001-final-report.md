# Intraday Exposed 001 final report

## Outcome

AUTONOMOUS INTRADAY RESEARCH COMPLETE — BOUNDED INTRADAY UNIVERSE EXHAUSTED WITH NO CONTROLLED-QUALIFIED CANDIDATE

The frozen exposed-data campaign completed all discovery and selected walk-forward work with zero
runtime failures. Eleven gap-fade configurations passed discovery. The frozen cap sent the top five
through all four walk-forward folds, where every one failed the same net-return, fold-consistency,
worst-fold, cost, and concentration requirements. No configuration became serious. The final cohort
therefore froze empty, and the runner stopped without loading or replaying the June 2026 evaluation
range.

This is historical simulated evidence, not a claim of future profitability.

## Identity and Git delivery

- Program: `intraday-exposed-001`.
- Starting main: `13039947fa7761c77a6b02c224c5cf16d55a34a8`.
- Exposed research source main: `0c3126c0c1e3244d313afa6dd94b70e988173b94`.
- Frozen plan SHA-256:
  `75e33950647b83d3213fb635153961b36b80d8dbbbfe9e9220350910c09ecfc9`.
- Frozen plan fingerprint:
  `2487030ec3f3fe2b212834790e44d113f72beeee5642408cd516a0589183a0ce`.
- Reviewed policy fingerprint:
  `42481069d9d0295d40ff1ccc6c956632d852f58522040d01024d7798172fe127`.
- Final closeout main: attested after merge by annotated tag
  `intraday-exposed-001-closeout-v1`.

| PR | Merge commit | Purpose |
| --- | --- | --- |
| #141 | `1300acedb1079371fa26bdf04f6f5dfedb30f1ba` | Freeze the exposed-data design, datasets, chronology, families, gates, and budget |
| #142 | `d007cf1224394558655f4b8b7c38ec421ab58911` | Add the 35 strategy contracts and isolated frozen-plan runner |
| #143 | `0c3126c0c1e3244d313afa6dd94b70e988173b94` | Validate the research-calendar label and manifest bar-grid policy separately |

The machine report records #143 because the completed command used
`--implementation-pr 143`. The source commit contains the first-parent merges for #141, #142, and
#143; the table above preserves the complete program history. The closeout tag records the final
closeout PR and merge SHA without requiring this committed report to contain its own merge SHA.

## Frozen data

The program used only four immutable Alpaca IEX SPY/QQQ five-minute datasets. Post-run validation
rechecked each normalized fingerprint and returned `valid: true`.

| Dataset ID | Range | Bars | Normalized fingerprint | Raw fingerprint |
| --- | --- | ---: | --- | --- |
| `0a307dd767283d8f268c10b372c416abc49ac555cb242bf612f0b485be518363` | 2025-07-01 13:30Z–2025-12-31 20:55Z | 19,752 | `166722d26f52ca344abf38c35e56e9c6496c1fd7444affa5218495091aaee01e` | `249f23deb77c2a4488d7cdde058b538d8431f1dde912a483d80a5d5f73605d3d` |
| `074e66c2260f576d6c1765295db93b5e22fb4753dc8f9912ef6f5be7fa937479` | 2026-01-02 14:30Z–2026-02-27 20:55Z | 6,084 | `d74ba8fefd3ac0f46cb86f155212f5d5eecef286d5d411847c952f6ab60e8437` | `b08465f9fdd726cf0e9669836e510bd181dd0eae3771fa80da63c2c820f104d5` |
| `1b1b5b1179a84522d6827827a6143a547321ef8b49262cdfb4d6a81885f647ed` | 2026-03-02 14:30Z–2026-04-30 19:55Z | 6,708 | `bbff4ec9c8992d088a2a85cf35196d20b0b30328d9d5e287540b8e73e907c470` | `b21dc4074f31b1ba8cbc15f1767f76aa1287b5d128310f20c9b5ea002ea3609a` |
| `9b4ff70403ac81ff7874f37578930df5654adfe321e8586e6f64bc10dd1ced23` | 2026-05-01 13:30Z–2026-06-30 19:55Z | 6,396 | `53c3d52a42a7baf099ff195ed67815a8db682c1c77e31e4869e484d7027c3ecb` | `d44cb2ab7da7eec3a8d717583c59f0af6f230b992a64c276515458fa7b8b6536` |

Together they contain 38,940 bars: 19,470 per symbol across 251 complete XNYS sessions. The
archive has 248 full sessions and three early closes, on 2025-07-03, 2025-11-28, and 2025-12-24.
It has no missing or duplicate intervals, quarantined records, or zero-volume bars. No exposed
one-minute artifact existed, so the frozen universe remained SPY/QQQ at five minutes.

## Chronology and execution

- Discovery evaluation: 2025-07-01 13:30Z through 2025-10-31 19:55Z.
- Walk-forward fold 1: November–December 2025, with context from 2025-07-01.
- Walk-forward fold 2: January–February 2026, with context from 2025-09-02.
- Walk-forward fold 3: March–April 2026, with context from 2025-11-03.
- Final exposed fold: May 2026, with context from 2026-01-02.
- Controlled qualification: June 2026, with context from 2026-03-02, available only after a
  nonempty simultaneous cohort and controlled-plan freeze. Its evaluation range was never loaded
  or run.

Normal execution used 5 bps slippage, 1 bp commission, and a one-bar FIFO delay. Stress A was
frozen at 10/2 bps with one bar. Stress B was frozen at 20/5 bps with three bars. Isolated delay
variants used two and three bars while preserving decision cadence and original signal timestamps.
The exact zero-cost diagnostic used the normal one-bar delay and had no promotion authority.

Every contract emitted only `0`, `0.5`, or `1` long-only desired states, submitted orders only on
state changes, and flattened at each normal or early session close.

## Strategy budget and ledger

| Family | Name | Contracts | Parent configurations |
| --- | --- | ---: | ---: |
| A | opening-range-breakout | 5 | 48 |
| B | intraday-trend-following | 4 | 32 |
| C | intraday-momentum | 3 | 28 |
| D | mean-reversion-and-pullback | 4 | 43 |
| E | gap-continuation-and-fade | 4 | 32 |
| F | time-of-day | 1 | 16 |
| G | volatility-breakout | 2 | 18 |
| H | volatility-regime-filter | 2 | 16 |
| I | cross-asset-confirmation | 2 | 16 |
| J | relative-strength-rotation | 2 | 28 |
| K | session-high-low-breakout | 1 | 12 |
| L | causal-vwap | 2 | 18 |
| M | simple-combinations | 3 | 18 |

The ledger contains:

- 325 Normal discovery runs and 325 exact zero-cost pairs;
- five selected configurations × four folds = 20 Normal walk-forward runs and 20 zero-cost pairs;
- 690 completed runtime rows, zero failed, pending, or running rows;
- zero serious candidates, serious-stage cost/delay stress variants, parameter-neighbor runs,
  controlled reservations, or controlled runs.

All 690 stored run IDs, canonical specifications, result fingerprints, source commits, plan hashes,
dataset bindings, and authority fields revalidated after completion. Every evaluation ended no later
than 2026-05-29 19:55Z.

## Strongest discovery configuration per family

Returns are decimal returns. These are the predeclared per-family sort winners, not promoted
candidates.

| Family | Configuration | Strategy and parameters | Normal return | Zero-cost return | Turnover | Fills |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| A opening-range-breakout | `iec-651b2744538e5368f503` | `orb-trend-confirmed {"exit_bar":48,"opening_bars":3,"trend_window":24}` | -0.037874140105210285878460473 | 0.018553544823427040445805233 | 93.24847379517662492281699711 | 190 |
| B intraday-trend-following | `iec-cca4d645c63babb973ac` | `trend-pullback-continuation {"pullback_bars":6,"pullback_threshold_bps":10,"trend_window":12}` | -0.0170968588107843443218998608 | 0.000753353495857495115678663 | 29.72027740216864396709072269 | 60 |
| C intraday-momentum | `iec-6c77d7b01bb682507a59` | `absolute-momentum {"lookback":24,"threshold_bps":0}` | -0.2541505020636759449974127195 | 0.015196406508273611574376895 | 442.376360033354939152515754 | 1,028 |
| D mean-reversion-and-pullback | `iec-9e8f179ddf647f460b60` | `pullback-in-trend {"pullback_bars":6,"threshold_bps":10,"trend_window":12}` | -0.0170968588107843443218998608 | 0.000753353495857495115678663 | 29.72027740216864396709072269 | 60 |
| E gap-continuation-and-fade | `iec-1c91e81acdf3fae52a49` | `gap-fade {"entry_delay_bars":3,"gap_threshold_bps":10}` | 0.018134995808634259142738376 | 0.039744770285839854909240426 | 34.98782576393169882051341802 | 70 |
| F time-of-day | `iec-4d3e5821b2b6f6dff586` | `windowed-momentum {"lookback":6,"threshold_bps":5,"window_end_bar":11,"window_start_bar":0}` | -0.086664763939651289370027224 | 0.001139743090239230399735444 | 146.7011167309999244245226307 | 306 |
| G volatility-breakout | `iec-3beaa70309894b92c25a` | `rolling-range-breakout {"lookback":24,"threshold_half_ranges":3}` | -0.0111173733881260237615728035 | -0.003972775189170168928381637 | 11.93162258199168803326256928 | 24 |
| H volatility-regime-filter | `iec-811cfd4a35fcddb6e804` | `trend-volatility-filter {"maximum_average_absolute_return_bps":10,"trend_window":24,"volatility_window":12}` | -0.2746489340542831418832047676 | 0.019188346970138262858197276 | 484.4236199703112407758379443 | 1,134 |
| I cross-asset-confirmation | `iec-efefa3f3979040daac9e` | `cross-asset-trend-confirmation {"threshold_bps":5,"window":36}` | -0.2199513624434160144992490282 | -0.0131609432437960693152354318 | 346.4987520902549525569703026 | 784 |
| J relative-strength-rotation | `iec-f3388ef15a2b7f413aca` | `dual-horizon-relative-strength {"fast_lookback":12,"slow_lookback":36,"threshold_bps":5}` | -0.3207330989043627192771241045 | 0.005674920176440209661249617 | 543.2299662654192361591727636 | 654 |
| K session-high-low-breakout | `iec-34119e977ba181035280` | `completed-session-channel-breakout {"entry_lookback":24,"exit_lookback":6}` | -0.1067708718738206883325938324 | -0.0043167701761863270329427006 | 169.487519987152375292870878 | 362 |
| L causal-vwap | `iec-40ed614fe8856993dc36` | `cumulative-vwap-reversion {"entry_threshold_bps":30,"exit_threshold_bps":0}` | -0.0405406425245619910521523747 | 0.003014212416898150742043246 | 72.98034179912569329522590275 | 148 |
| M simple-combinations | `iec-31ea276981df159e206f` | `opening-range-plus-market-trend {"opening_bars":3,"trend_window":24}` | -0.1697870034709431306765096004 | 0.016843741564238617001864297 | 307.6786655566220942770139367 | 676 |

The exact JSON report includes all 22 required fields for each family winner: net and zero-cost
return, Sharpe, drawdown, turnover, fills, round trips, hit rate, average trade, cost, cost-to-gross
ratio, holding duration, exposure, state duration, chronological blocks, time of day, symbol
contribution, worst fold, fold dispersion, stress retention, and neighbor retention. Fields that
require an unreached later stage are explicitly null.

## Gross, cost, turnover, and fill findings

Across the 325 independent $100,000 discovery replays:

- 189 configurations had positive zero-cost return;
- only 11 had positive Normal return;
- 178 were positive before costs but nonpositive under Normal costs;
- total Normal cost paid was `$8,139,868.316545231244260859478`;
- aggregate Normal turnover was `135664.4716310838150447223162`, with a single-run maximum of
  `1310.185338138322064267313547`;
- Normal runs produced 306,182 fills and 153,091 completed round trips.

Costs erased most apparent discovery edge. High-churn momentum, volatility-filter, rotation, and
combination winners were deeply negative under Normal execution despite positive zero-cost results.
Family E was the only family with a discovery pass.

## Walk-forward and robustness findings

Eleven family-E gap-fade configurations passed discovery. The frozen cap selected these five. All
five completed all four Normal and zero-cost folds.

| Configuration | Parameters | Aggregate Normal return | Aggregate zero-cost return | Positive Normal folds | Worst Normal fold | Cost / zero-cost profit | Positive-profit symbol concentration |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `iec-1c91e81acdf3fae52a49` | `entry_delay_bars=3, gap_threshold_bps=10` | -0.0516132081280317582840106072 | 0.0158224988148345332482719234 | 0/4 | -0.0278834864486247784867338195 | 4.250167400226745952847792390 | null |
| `iec-22c0a6415c4710ec818f` | `entry_delay_bars=1, gap_threshold_bps=30` | -0.0389551933402432083405236340 | 0.0094752820193936867836209888 | 0/4 | -0.0196383384081670543887425613 | 5.106148071477891219512097664 | null |
| `iec-8235e2d113c489fd1085` | `entry_delay_bars=3, gap_threshold_bps=50` | -0.0122373469320991749204590310 | 0.0179284128996101973363463193 | 1/4 | -0.0209305912688674800065458162 | 1.677710556070913399700679934 | 1 |
| `iec-a5e8fd67ba143d22f352` | `entry_delay_bars=1, gap_threshold_bps=10` | -0.0542830257265473162558660871 | 0.0131281648074238094235893464 | 1/4 | -0.0311788846177908380900759454 | 5.122199467441593300623191945 | null |
| `iec-ed1fe5af3c1417ae9888` | `entry_delay_bars=3, gap_threshold_bps=30` | -0.0335557774172095813585030710 | 0.0149243673516547549727591708 | 1/4 | -0.0186379607775833782882642917 | 3.242795640206624469402288988 | null |

Every configuration failed:

- aggregate Normal return greater than zero;
- at least three positive Normal folds;
- worst Normal fold return at least `-0.015`;
- cost-to-zero-cost-profit ratio at most `0.75`;
- positive-profit symbol concentration at most `0.75`.

A null concentration means neither symbol had positive aggregate profit, which fails closed. All
five passed the aggregate zero-cost, minimum round-trip, and maximum-drawdown gates. Their positive
zero-cost aggregates alongside negative Normal aggregates show a small gross signal that did not
survive realistic costs. The failure also held across both declared entry-delay choices and all
three tested gap thresholds.

No configuration reached the serious stage. The program therefore ran no Stress A, Stress B,
two-bar delay, three-bar delay, or parameter-neighbor evaluation. It makes no empirical stress,
delay-retention, or parameter-plateau claim. Pre-run tests still verified that changing fill delay
does not change decision cadence or original signal timestamps; those mechanics did not rescue a
candidate from the earlier walk-forward rejection.

## Final cohort and controlled qualification

- Screened serious candidates: zero.
- Passing serious candidates: zero.
- Final frozen cohort: empty.
- Cohort fingerprint:
  `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.
- Controlled plan: none; no controlled-plan fingerprint exists.
- Controlled reservations and attempts: zero.
- Controlled PASS/FAIL results: none.
- Qualification evidence and successful qualification fingerprints: none.
- Recommended candidate for independent evaluation: none.

The create-only cohort freeze was written at 2026-08-20 17:21:17.280229845Z. It records an empty
cohort and no controlled-plan artifact. The SQLite registry contains zero controlled reservations,
zero controlled-stage rows, and zero controlled reports. The final JSON report was written later,
at 2026-08-20 17:21:17.940222520Z. No June strategy result exists.

## Evidence

- Exact runtime JSON report:
  `.trading-lab/intraday-exposed-001/final-report.json`.
  SHA-256 `0831b267abb0bd10e73e7a52f86edcb6a48de78f612fe64e51b68bbf39fc837e`;
  report fingerprint `8c4002c448439b71ab9d4dae4852dc8a8d717ed05fb61f9fc14e9102561fbd7a`.
- Exact runtime Markdown report:
  `.trading-lab/intraday-exposed-001/final-report.md`.
  SHA-256 `a5148eca50938a665911647231c5011bb61f9c8cd01b70e04eca89df4999454a`.
- Exact cohort freeze:
  `.trading-lab/intraday-exposed-001/cohort-freeze.json`.
  SHA-256 `13cf927ea4892595e70d2fd8ba368a82de93010c2e58188200551b9ff0b90fc5`;
  freeze fingerprint `bbc5b71c226e4ca17276033c5844e34bb0345a88b8bdaf787ecac490f69b9209`.
- Isolated SQLite registry snapshot after process exit:
  `.trading-lab/intraday-exposed-001/intraday-exposed.sqlite3`.
  SHA-256 `2ec0655e7cdea2bb3854343c501db7d682fe19fb4f319cdbc46dafbfd8e3ae9d`.
- Completed-run log:
  `.trading-lab/intraday-exposed-001-run-2.log`.
  SHA-256 `75e41a183d7aae2d5bb3aea42d7d54f4188cc0180c15522170a785c472882545`.
- Preserved first-start failure log:
  `.trading-lab/intraday-exposed-001-run.log`.
  SHA-256 `404c068dad5a241c4d3a95c17de258d8fca091dae21bebd963481ef93b73e908`.

The first start failed before program binding or strategy results because the runner from PR #142
compared the plan's `XNYS-v1` research-calendar label with the manifests'
`XNYS-regular-session-bars-v1` bar-grid policy. PR #143 validated both exact labels separately. It
did not change the frozen plan or datasets. The completed run then revalidated all four datasets,
source identity, policy fingerprint, and plan before creating result rows.

Independent closeout validation reproduced both canonical report fingerprints, all artifact hashes,
the Markdown rendering, strongest-family ordering, discovery selection, walk-forward rejection,
aggregate findings, and all 690 run-record fingerprints without loading market data.

## Safety boundary and stop condition

Every stored run binds one of the four allowed dataset IDs and the exact frozen source and plan.
Every evaluation ended by 2026-05-29. No June evaluation range was loaded or replayed, no protected
holdout was accessed, and no independent evaluation opened. Intraday V1, V2, and V3 state remained
untouched. The isolated runner has no PAPER, broker, live, order, risk, execution, reconciliation,
or `strategic-allocation-21` mutation path; none of those systems was read, activated, or changed.

The campaign is closed. Do not create a controlled plan for the empty cohort, substitute a nearby
gap parameter, reopen June, start independent evaluation, or authorize PAPER from this evidence.
