# Intraday Exposed 002 terminal report

Status: closed as terminally interrupted exposed research evidence. The campaign did not complete and
did not establish a qualification outcome.

Calibration-and-research task starting main: `1186e9356de742ed94d030f272ba5522553be78a`

Intraday Exposed 002 plan starting main: `71aa4da11875cffbff77693be83d116d11a5cb73`

Execution and final research main: `32fcfa35ac6d8628bc510b54a90554222f61a1fa`

Runtime root: `.trading-lab/intraday-exposed-002`

The runner completed four of 120 reserved discovery rows. Its process then disappeared while the
fifth row was `running`. No exit status, process log, report for that row, or other cause evidence
survived. On
2026-08-21, the frozen recovery path changed that stale claim to a terminal failure with the exact
error `RuntimeError: interrupted run is terminal and was not retried`, then stopped before any
pending row. The plan forbids retrying the failed row. The campaign cannot resume.

This is not either requested completion outcome. It would be false to report that all candidates
failed or that the campaign completed. No controlled-qualified candidate was established.

## Delivery history

| Pull request | Merged main | Scope |
| --- | --- | --- |
| #145 | `355e0ae3b8d1697553f3cfc8b3f230b2019b72dd` | Calibration v1 plan and runner |
| #146 | `86a13ba5cf26471b661d2f910048846c9bf15145` | Calibration v1 failure evidence and v2 plan |
| #147 | `caf2e51ed4a357f339dd6318c1f4884a8a8d7792` | Calibration v2 acquisition fix |
| #148 | `71aa4da11875cffbff77693be83d116d11a5cb73` | Frozen calibrated cost model and review |
| #149 | `1aedc2d4056c955a8fdd835a1795277979c94be4` | Exposed 002 plan and review |
| #150 | `01430416953559e0168a2192afb3f859440bc7a4` | May acquisition amendment and review |
| #151 | `8df22d0eb87f54c8fb19cb5713908f0dc93dc9d8` | Exact May data binding and review |
| #152 | `794045775d323f1ba2481b44a454be4386bc7edd` | Isolated Exposed 002 runner |
| #153 | `32fcfa35ac6d8628bc510b54a90554222f61a1fa` | Exact split-catalog dispatch |

## Calibration evidence

The complete calibration report is
`docs/research-campaigns/intraday-execution-calibration-001.md`. The old Exposed 001 model charged
5 bps adverse slippage and 1 bp commission on each fill, with one five-minute delay bar. A round
trip therefore cost 12 bps of one-way reference notional before any delay-price effect. It omitted
regulatory fees.

Calibration v2 used SIP quotes for SPY and QQQ. It sampled the first XNYS session on or after the
15th of each month from July 2025 through May 2026 plus every early close in that range: 14 sessions,
67 time windows, 134 symbol-window datasets, and 80,399 eligible causal one-second observations.
Each grid point used the latest unique quote strictly before the point and no more than five seconds
old. June, V3 periods, strategy returns, and candidate timestamps were excluded.

- Dataset-ID fingerprint: `6ea873f76a26ed38a5522d7a16d6773b7755d2511a3ad6a2681ce6d5fb2aa762`.
- Quote-dataset fingerprint: `3c5d4f853b281c635df1f6575fa98db11acd12d640798e043650c603e5a80036`.
- Analysis SHA-256: `0555a247138450ffc0e76b5b273d94e1a5c8c6a09634d5f063da57eda8df12be`.
- Analysis fingerprint: `5302ae235f4fba10c516fc6a110b0717ba81879a5944e25548fd0ee95e30d07d`.
- Minimum eligible symbol-window coverage: `0.9983333333333333333333333333`.

### Spread distribution

Combined values:

| Percentile | Spread dollars | Spread bps | Half-spread bps |
| --- | ---: | ---: | ---: |
| Median | 0.01 | 0.1636862135286655481442075541 | 0.08184310676433277407210377705 |
| p75 | 0.02 | 0.2808042232955183645962035269 | 0.1404021116477591822981017634 |
| p90 | 0.02 | 0.3315924728508662853353228882 | 0.1657962364254331426676614441 |
| p95 | 0.03 | 0.4058578820982852504481347448 | 0.2029289410491426252240673724 |
| p99 | 0.04 | 0.5653310720090452971521447248 | 0.2826655360045226485760723624 |

Half-spread bps by symbol:

| Symbol | Median | p75 | p90 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| QQQ | 0.08654786529690245190102386125 | 0.1617102475783890425136240884 | 0.1683359986533120107735039138 | 0.243299136288066177365070354 | 0.3528158230840336727421551402 |
| SPY | 0.07519418899307461519373782795 | 0.08000832086536999847984190355 | 0.1477759716270134476134180582 | 0.150414391648992975647909992 | 0.2153578889184008958888179006 |

Half-spread bps by time window, combined across symbols:

| Window | Median | p75 | p90 | p95 | p99 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Opening | 0.0812393881049287936763260299 | 0.15875031750063500127000254 | 0.1668418506098069639788444534 | 0.2461902065535832984563874049 | 0.3535092866889613190138504938 |
| Morning | 0.082213178772557240925720393 | 0.1436348228264460435788052456 | 0.1681548369738855538179555735 | 0.2432162922486967660340340665 | 0.3516248584709944654247276666 |
| Midday | 0.08159868136530913660435247365 | 0.134872680189900733707380233 | 0.1643844623806157841960777868 | 0.2022994706497184665700124752 | 0.2505616757564874593881283878 |
| Afternoon | 0.0829978835539693737809685853 | 0.1350092481334971445544019766 | 0.1656643970644268840183556152 | 0.2022994706497184665700124752 | 0.245180166559059815787968192 |
| Closing | 0.0804809541821927840776480246 | 0.08962741881996540381633549335 | 0.1602666837617796012564908007 | 0.1663478333194710138900440822 | 0.2424653880658535993986858376 |

### Frozen prospective model

Cost-model ID: `intraday-execution-cost-model-001-v1`. SHA-256:
`a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af`; fingerprint:
`94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4`.

| Scenario | SPY adverse half-spread per fill | QQQ adverse half-spread per fill | Delay | Monetary fees |
| --- | ---: | ---: | ---: | --- |
| Normal | 0.09 bps | 0.17 bps | 1 five-minute bar | SEC, TAF, CAT; zero assumed direct-retail commission |
| Stress A | 0.16 bps | 0.25 bps | 2 five-minute bars | Same fee schedule |
| Stress B | 0.22 bps | 0.36 bps | 3 five-minute bars | Same fee schedule |
| Zero-cost diagnostic | 0 | 0 | 1 five-minute bar | None; no promotion authority |

The model uses SEC `$0.0000206` per dollar of daily executed sell notional, TAF `$0.000195` per
executed sell share capped at `$9.79` per trade, and CAT `$0.000003` per executed equivalent share
on both sides. Each fee type aggregates by New York account day and rounds upward once to the
nearest cent. An applicable partner or Alpaca Elite commission invalidates the model.

Official Alpaca source identities were retrieved on 2026-08-20 UTC:

| Source | SHA-256 |
| --- | --- |
| <https://docs.alpaca.markets/us/docs/regulatory-fees.md> | `ee2d303dd467b1de58bea957fcfb0f6799e7f807c5260414308b38ef59f656be` |
| <https://files.alpaca.markets/disclosures/library/BrokFeeSched.pdf> | `cfed684b2554e856022bc80c4883260ea1414c4ba79fc65304f7fc08cc780a7e` |
| <https://docs.alpaca.markets/us/docs/paper-trading.md> | `8a8bfb57946d8ab1fb80ac8bdb65f6f43d904e955a676d6a5f9f76b6a145a846` |
| <https://docs.alpaca.markets/us/reference/stockquotes-1.md> | `5be32c1fa69c8d5e68fb3946d3e8e05da48ddd7e2afb3f0c7f375b33d0a7028c` |

The independent review passed all seven required controls before strategy execution. Review
SHA-256 is `fb197856b9229349e5de4bca742f328a8f1e5e53f9558dfd7324744e91a795aa`; fingerprint is
`8ade5190bb64330af037f88bf0911ed3cdb04578ca7a6d6e27a5fa6d651349b2`.

## Frozen research scope

Plan SHA-256: `8acb778eec43dd53b56c65712b5a076bdc6126de3504d68114aa714e2474b17f`;
fingerprint: `a255949e41c9776e82a04782c6183f5af1476a1dc97c36be4910e4d59424fb98`.
The frozen May data-binding SHA-256 is
`3d6a5dde3b05369ceeb1e3be5b1f47e73a541c74eed184e1850945ee56890769`; fingerprint:
`b6849987e7673c4073272ec891e7f7118b91eba6926aa4c16f262162f529ea9d`.

The plan fixed 60 parents across ten families: gap-down failed-continuation fade, gap-up confirmed
continuation, opening-range breakout, volatility-compression breakout, trend-pullback recovery,
prior-session level event, morning-afternoon continuation, cross-asset confirmed breakout,
volatility-filtered breakout, and minimum-edge hysteresis one-trade. Every discovery parent had a
Normal and exact zero-cost diagnostic row, for 120 initial reservations.

The complete frozen search, mechanics, gates, chronology, and June disposition remain in
`docs/research-campaigns/intraday-exposed-002-program.md` and
`config/research/intraday-exposed-002-plan-v1.json`.

## Partial runtime evidence

Only two parents completed their Normal/zero-cost pair. These exposed discovery results are
incomplete and cannot support family screening, parameter selection, a recommendation, or a claim
about the 60-parent search.

| Candidate | Normal return | Zero-cost return | Normal gross P&L | Normal friction | Normal net P&L | Fills | Round trips/session | Turnover | Cost/gross profitable-trade profit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ie002-f01-a01-b01` | 0.01531561141416355791868901 | 0.015679021469925302434747952 | 1567.425030841939393791772791 | 35.86388942558360192287183223 | 1531.561141416355791868901 | 30 | 0.1724137931034482758620689655 | 15.02938428780464228281235312 | 0.01811573214572930242742529052 |
| `ie002-f01-a01-b02` | 0.015358084081979096437477802 | 0.015721570105616705192469609 | 1571.665818661186735971034278 | 35.85741046327709222325409438 | 1535.8084081979096437477802 | 30 | 0.1724137931034482758620689655 | 15.02434441702777990162438466 | 0.01790298247767085151534252108 |

Both Normal reports recorded exact accounting, 15 completed round trips, average holding periods
of 55.46666666666666666666666667 and 54.6 bars, and average gross trade edges of
20.81614625801438496497132856 and 20.87161422685396866293335157 bps. These facts do not establish
advancement because the frozen screen required every parent to finish before uniform selection.

The interrupted row was Normal discovery run `ie002r-f0718fce63d8b518e7601c7e` for
`ie002-f01-a02-b01`. It has no report, SHA-256, fingerprint, or result.

## Missing stages and terminal disposition

- Discovery: 4 completed rows, 1 failed row, 115 pending rows.
- Walk-forward: not started.
- Stress A, Stress B, delay-2, and delay-3: not started.
- Immediate parameter neighbors: not started.
- Final cohort: not screened or frozen.
- Controlled plan: none.
- June access: none; June remained ineligible and unread.
- June result: none.
- Qualification fingerprint: none.
- Candidate recommendation: none.
- Runtime `final-freeze.json`, `final-report.json`, and `final-report.md`: absent.

The read-only status command reports `terminal: false`, `outcome: null`, and `cohort_size: null`
because those fields depend on an absent `final-report.json`. This does not make a resume legal. The
failed row is terminal, and every later runner invocation stops on the frozen no-retry gate.

## Runtime evidence hashes

| Evidence | SHA-256 |
| --- | --- |
| `intraday-exposed-002.sqlite3` after recovery | `9bc46956eeb228e8ce918c831588d55edc258c8ff159fb5779a839e4892f3a83` |
| `run-reports/ie002r-b1ed6bc788e22c3c731f5f07.json` | `68362c3e45bcbd2a5b4b1ea18b83400e2edf6db558f2e596d78f4a2fdaf677ed` |
| `run-reports/ie002r-f83d03a4633784804109d5e5.json` | `f8df3f3413788ac1ff102da58d7902c0326e0a6de00b57f25fc0fe81a45a3614` |
| `run-reports/ie002r-8982fd307fc77a05483deb11.json` | `31c77e6304ed07c7d765b8b0545ade1bcd275eb44005e41e212205b627f423be` |
| `run-reports/ie002r-fec03a5a77f6b78d8a0ba54f.json` | `4ce005f5639dab93ad3e006f94de7b33c826a23f075db7e94b071ea977efb783` |

The database byte hash changed only because the supported recovery path recorded the terminal
failure. The four create-only report hashes stayed unchanged.

## Boundaries and recommendation

No Intraday V1, V2, V3, Intraday Exposed 001, Rapid-002, Rapid-003, or Rapid-004 result was opened
or modified during execution or recovery. No June or V3 bar, quote, or result was accessed. PAPER,
broker, live, protected-holdout, and `strategic-allocation-21` state remained untouched. Every
authority field remained false.

Do not restart this campaign, reset a row, delete evidence, or reinterpret the two completed pairs.
Any further cost-aware intraday search requires a separate prospectively reviewed, versioned
program. It must preserve this interruption as immutable evidence.

**INTRADAY EXPOSED 002 CLOSED — TERMINALLY INTERRUPTED; NO QUALIFICATION OUTCOME**
