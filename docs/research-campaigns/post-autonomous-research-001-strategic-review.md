# Post-Autonomous Research 001 strategic review

Status: complete strategic analysis; no new strategy run, market-data acquisition, controlled
evaluation, PAPER action, or broker action was performed.

Source state: clean synchronized `main` at
`0068842ef4c57485020db28446e16e5a111e2ed6` on 2026-08-25.

Decision: the SPY/QQQ five-minute OHLCV surface is **mostly exhausted**. Stop broad search on that
surface. The preferred next direction is a bounded cross-sectional program on twelve liquid US
equity ETFs, with signals formed on fixed 30-minute aggregates and positions held for two or four
hours. The secondary direction is a broader-ETF overnight program. Neither direction is authorized.

The machine-readable companion is
[`next-research-program-002-proposal.json`](next-research-program-002-proposal.json).

## 1. Executive research status

The completed history contains useful negative evidence, several partial results, and repeated
control failures that must not be treated as market evidence. No intraday candidate is serious,
controlled-qualified, replay/shadow ready, or PAPER ready. Every strategy, qualification, protected
holdout, PAPER, broker-write, and live authority is false in the final autonomous-program state.

| Check | Verified state |
| --- | --- |
| Git | `HEAD`, local `main`, and `origin/main` were all `0068842`; the worktree was clean before this review branch |
| Autonomous program | Closed at revision 8; Campaign 4, repair, relaunch, and automatic successor authority are prohibited |
| Campaign 1 | `intraday-spy-qqq-lead-lag-001`, terminal empty cohort |
| Campaign 2 | `intraday-relative-volume-drift-001`, terminal empty cohort |
| Campaign 3 | `intraday-fed-policy-absorption-001`, terminal pre-execution data-boundary failure; hypothesis unassessed |
| Active work | No live coordinator or worker process and no active terminal-program lease |
| Runtime caveat | Exposed 003 retains one immutable literal `running` row from its stopped coordinator; its PID is absent and it is not active work |
| Controlled evaluation | None for the completed autonomous program |
| Protected access | June, Intraday V3, daily 2018-2019, protected results, and PAPER/broker/live state remained untouched in this review |

Primary state evidence:

- [`intraday-autonomous-research-001-state-v2-revision-008.json`](intraday-autonomous-research-001-state-v2-revision-008.json)
- [`intraday-autonomous-research-001-cross-campaign-synthesis-v1.json`](intraday-autonomous-research-001-cross-campaign-synthesis-v1.json)
- [`intraday-autonomous-research-001-closeout-independent-review-v1.json`](intraday-autonomous-research-001-closeout-independent-review-v1.json)

## 2. Evidence boundary and classification

This review analyzed 23 canonical, non-superseded market-hypothesis campaign identities and 26
material lineage/control records. The larger count includes baseline v1 and calibration v1/v2
because those superseded or non-strategy records explain what the strategy evidence does and does
not show. Intraday V3 is listed separately as a protected future boundary and is not one of the 26
completed or terminal records.

Classifications used below:

- **NR**: negative research result. The campaign ran enough of its frozen design to support its
  stated rejection.
- **II**: infrastructure interruption. Partial or absent results cannot decide strategy merit.
- **PC**: pre-execution control failure. No strategy evidence exists.
- **SI**: superseded implementation. The old result is method evidence, not financial evidence.
- **DS**: data or cost study. It informs execution assumptions but is not a strategy result.

Factor notation is `cost / chronology / parameter / concentration-or-sample / delay`. `Y` means
material, `N` means not a binding cause, `U` means unmeasured or unresolved, and `-` means not
applicable.

## 3. Complete campaign timeline

### Daily and broad-universe research

| # | Campaign | Hypothesis, universe, horizon | Search and furthest stage | Outcome and strongest evidence | Dominant failure; factors | New information |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | `alpaca-baselines-20260802-v1` | 20-session trend and momentum; five liquid ETFs; daily | 22 records | **SI**; symbol-order cash contention invalidated financial comparison | Full-portfolio targets were emitted per symbol; `U/U/-/U/U` | Established the need for an atomic portfolio boundary |
| 2 | `alpaca-baselines-20260802-v2` | Same corrected daily baselines | 22/25 records; three yearly validation folds | No qualification; fixed weight beat both trend baselines in every year | Benchmark inferiority and missing qualification metrics; `Y/Y/U/U/N` | Corrected provider-data baseline and cost/delay sensitivity evidence |
| 3 | `alpaca-qualification-evidence-20260802-v3` | 20-session moving average and momentum with neighbors | 34/34; three folds, cost, delay, and neighbors | **NR**; both candidates rejected after policy approval | Benchmark wins, Sharpe, concentration, turnover, or neighbor retention; `N/Y/Y/Y/N` | Added registry-backed qualification and showed material parameter dependence |
| 4 | `alpaca-long-horizon-training-20260803-v4` | 189/252/315-session time-series momentum; five ETFs | 4/4; training only | **NR**; all three momentum variants lost money with negative Sharpe | No gross edge, high turnover, concentration; `Y/U/Y/Y/-` | Rejected this exact slow per-symbol momentum family before validation |
| 5 | `m3-relative-strength-v1` | 84/126/168-session top-three relative strength | 4/4; training only | **NR**; 126 and 168 beat fixed weight in return but had Sharpe 0.120/0.161 and 53/45 trades | Weak risk-adjusted evidence and sample size; `N/U/Y/Y/-` | Partial evidence that allocation helped drawdown, not enough to open validation |
| 6 | `m3-risk-managed-momentum-v1` | Momentum with inverse-volatility weights and 40% caps | 4/4; training only | **NR**; base lost 6.34%; 84-session neighbor gained 6.24% but could not replace it | Base/neighbor instability, benchmark deficit, concentration; `N/U/Y/Y/-` | Showed that risk weighting did not rescue the frozen base |
| 7 | `m3-volatility-balanced-v1` | Inverse-volatility allocation without return signal | 4/4; training only | **NR**; 63-session base lost 3.41% and both neighbor conditions failed | Return, Sharpe, drawdown, concentration, neighbors; `N/U/Y/Y/-` | Rejected this exact allocation-only contract |
| 8 | `rapid-002-rmm-40-40-10-controlled-v1` | Risk-managed momentum; SPY/QQQ/IWM/TLT/GLD; daily | 1 frozen candidate, 28/28 controlled records | **NR**; 19 gate groups passed, but benchmark wins were 0/3 and instrument concentration was 54.81% | Benchmark and concentration; `N/Y/N/Y/N` | Proved that favorable stresses do not offset failed base gates |
| 9 | `rapid-003-bounded-strategy-discovery` | Sixteen daily tactical families; five ETFs | 1,219 parents, 1,395 rows, 162 folds, 14 stresses | **NR**; 5/84 complete fixed-block identities passed base gates; all five failed one-parameter neighbors | Benchmark, activity, concentration, chronology, neighbor fragility; `Y/Y/Y/Y/N` | Broadly exposed the five-ETF daily rule surface and made neighbor fragility repeatable evidence |
| 10 | `rapid-004-expanded-universe` | A-U daily allocation families; 37 liquid ETFs | 629 parents; 35 identities reached all three fixed blocks | **NR**; none passed every visible gate; sleeve concentration failed 35/35 and instrument concentration 29/35 | Concentration, fixed-block Sharpe/returns, some turnover/cost; `Y/Y/U/Y/-` | Showed that daily breadth alone did not solve concentration or benchmark-relative weakness |

Daily evidence: [baseline v2](alpaca-baselines-20260802-v2.md),
[qualification v3](alpaca-qualification-evidence-20260802-v3.md),
[long horizon](alpaca-long-horizon-training-20260803-v4.md),
[relative strength](alpaca-relative-strength-training-20260803-v5.md),
[risk-managed momentum](alpaca-risk-managed-momentum-training-20260803-v6.md),
[volatility balance](alpaca-volatility-balanced-training-20260803-v7.md),
[Rapid 002](rapid-002-risk-managed-momentum-promotion.md),
[Rapid 003](rapid-003-final-report.md), and [Rapid 004](rapid-004-final-report.md).

### Intraday research and execution calibration

| # | Campaign | Hypothesis, universe, horizon | Search and furthest stage | Outcome and strongest evidence | Dominant failure; factors | New information |
| ---: | --- | --- | --- | --- | --- | --- |
| 11 | `intraday-research-v1` | Cash, 1-bar momentum, 12-bar MA; SPY/QQQ 5m | 60 reserved; 0 strategy candidates ran | **PC**; first acquisition exposed an extended-hours filtering defect | Acquisition/control failure; `-/-/-/-/-` | Corrected the XNYS transport-to-normalization boundary |
| 12 | `intraday-research-v2` | Corrected V1 matrix; SPY/QQQ 5m | 60/60; 12 base qualification groups | **NR with confounding**; all 12 groups failed; cost add-back ranged around zero | Exact-weight churn and legacy costs; delay changed application cadence; `Y/Y/U/U/Y` | Proved the frozen implementation failed, not that the signals lacked all predictive content |
| 13 | `intraday-execution-calibration-001-v1` | SIP quote calibration | One probe; no strategy | **SI/PC**; raw `ask >= bid` check rejected three valid transient crosses | Quote-state validation model; `-/-/-/-/-` | Required preservation and explicit exclusion of crossed states |
| 14 | `intraday-execution-calibration-001-v2` | Causal SIP spread and fee calibration; SPY/QQQ | 134 symbol-windows, 80,399 eligible one-second observations | **DS**; p75/p95/p99 half-spreads froze the later cost model | No strategy outcome; `-/-/-/-/-` | Replaced the 12-bps legacy round-trip assumption with symbol-specific quote evidence |
| 15 | `intraday-exposed-001` | Eleven frequent and sparse 5m families; SPY/QQQ | 325 parents, 690 rows; 11 discovery passes, top 5 walk-forward | **NR**; all five walk-forward candidates remained negative under Normal costs | Small gross edge could not pay legacy costs; chronology and concentration also failed; `Y/Y/U/Y/U` | Motivated sparse holds and quote-based recalibration |
| 16 | `intraday-exposed-002` | Ten sparse 5m families under calibrated costs | 60 parents/120 discovery planned; 4 rows complete, 1 failed, 115 pending | **II**; two completed parents were positive with about 20.8 gross bps/trade | Runner disappeared; no uniform screen; `U/U/U/U/U` | Proved the need for attempt journals and retryable expired leases; no family conclusion |
| 17 | `intraday-exposed-003` | Exact clean re-execution of Exposed 002 | 55 complete, 64 pending, 1 stale literal running row | **II**; partial strategy merit was not inspected | Throughput supersession after SIGTERM; `U/U/U/U/U` | Produced process-equivalence and throughput evidence, not strategy evidence |
| 18 | `intraday-exposed-004` | Restart-safe successor to Exposed 003 | 120 pending; 0 attempts | **PC**; `mappingproxy` could not cross the spawn queue | Task transport failure; `-/-/-/-/-` | Required a picklable immutable task envelope |
| 19 | `intraday-exposed-005` | Same ten sparse families with repaired process path | 60 parents, 272 runs; 14 walk-forward, 1 serious | **NR**; serious trend-pullback gained 6.511%, passed every stress/delay gate, failed one immediate neighbor | Gross edge 39/60, symbol concentration 34/60, chronology 13/14, final neighbor; `N/Y/Y/Y/N` | Strongest calibrated intraday evidence; slower holds helped cost efficiency but did not establish stability |
| 20 | `intraday-event-drift-001` | Joint post-BLS long drift; SPY/QQQ; multi-hour | 9 parents/18 runs; discovery only | **NR**; best point gained 0.467% with 23.8 gross bps/trade, but only 2/10 events activated | Sample and event/release/symbol concentration; `N/U/U/Y/U` | Sparse event work can show large apparent trade edge without enough independent events |
| 21 | `intraday-event-repricing-001` | QQQ-versus-SPY event leader continuation; 24-bar hold | 9 parents/36 runs; discovery only | **NR**; relative continuation was negative at all nine points, from -50.16 to -2.23 bps | Central relative-continuation claim failed; concentration secondary; `N/U/U/Y/U` | Relative behavior was not more robust than absolute returns on this contract |
| 22 | `intraday-event-opening-breakout-001` | SPY first-30-minute BLS breakout continuation | 3 parents/6 runs; discovery only | **NR**; 4-bp buffer gained 0.104% and 7.34 gross bps/trade but used only 3 events | Activity and event concentration; `N/U/U/Y/U` | Positive return did not supply enough independent event evidence |
| 23 | `intraday-event-prior-low-rejection-001` | Pre-open BLS prior-low breach/reclaim; SPY | 3 parents/6 runs; discovery only | **NR**; all points activated twice and lost 0.025%-0.040% under Normal costs | No gross edge and insufficient activation; `N/U/U/Y/U` | Rejected the exact reclaim contract without opening later stages |
| 24 | `intraday-spy-qqq-lead-lag-001` | Fixed SPY leader and delayed QQQ catch-up; 24-bar hold | 9 parents/18 runs; discovery only | **NR** after corrected reassessment; max 3 active sessions versus 12 required | Sparse activation, mostly negative rows, complete concentration in the lone positive row; `N/U/U/Y/U` | Rejected fixed SPY-to-QQQ catch-up on the frozen grid |
| 25 | `intraday-relative-volume-drift-001` | Joint same-clock participation shock and drift; 24-bar hold | 9 parents/18 runs; discovery only | **NR**; 4 parents positive; best gained 0.878% with 15.106 gross bps/trade | At most 6 sessions/12 trips; every row failed participation-bucket concentration; `N/U/U/Y/U` | Partial gross-edge evidence, but no robustness evidence |
| 26 | `intraday-fed-policy-absorption-001` | Late-session post-Fed information absorption | 9 parents/18 specifications; 0 strategy reports | **II/PC**; all 18 failed on `plan data must be an object` before bounded bar loading | Deterministic nested-plan loader defect; `-/-/-/-/-` | No evidence for or against the Fed hypothesis |

Intraday evidence: [V2 postmortem](intraday-campaign-v2-postmortem.md),
[calibration](intraday-execution-calibration-001.md),
[Exposed 001](intraday-exposed-001-final-report.md),
[Exposed 002](intraday-exposed-002-terminal-report.md),
[Exposed 003](intraday-exposed-003-program.md),
[Exposed 005](intraday-exposed-005-final-report.md),
[Event Drift](intraday-event-drift-001-final-report.md),
[Event Repricing](intraday-event-repricing-001-final-report.md),
[Opening Breakout](intraday-event-opening-breakout-001-final-report.md), and the final
[autonomous synthesis](intraday-autonomous-research-001-cross-campaign-synthesis-v1.json).

## 4. Cross-campaign failure taxonomy

Counts below are used only where the immutable reports share a valid denominator. They are not
pooled percentages across unlike campaigns.

| Failure mechanism | Evidence | Frequency and scope | Assessment |
| --- | --- | --- | --- |
| No or weak gross edge | Exposed 005: 39/60 failed the 3-bp edge gate. Event Repricing: all 9 relative continuations negative. Prior-Low: all 3 negative. | Common in calibrated discovery, but not universal: 42/60 Exposed 005 parents had positive Normal return. | Structural on the tested 5m OHLCV grids |
| Legacy cost domination | Exposed 001: 189 positive zero-cost configurations but 11 positive Normal; 178 crossed from positive to nonpositive. V2 churn paid costs close to its losses. | Common before calibration. | Historical implementation/model issue, not a current universal claim |
| Calibrated costs | Exposed 005, all event campaigns, and autonomous Campaigns 1-2 rejected mainly elsewhere. | Rare as the primary post-calibration blocker. | Campaign-specific after calibration; model still excludes impact and queue effects |
| Excessive turnover | V2 exact-weight churn; selected Rapid 003/004 families. | Common in legacy/frequent or some daily families; not an Exposed 005 gate failure. | Mechanism-specific |
| Execution-delay sensitivity | Exposed 005's serious candidate passed both delay gates. V2 delay changed target-application cadence. | Rare as a clean binding failure; legacy evidence is confounded. | Unresolved broadly, not structural |
| Chronological instability | Exposed 005: 13/14 failed three positive folds and 11/14 failed May. Exposed 001: all five walk-forward candidates failed. | Common among intraday candidates that reached chronology. | Structural warning on the current surface |
| Parameter-neighbor fragility | Exposed 005's sole serious candidate failed the final neighbor gate. Rapid 003's 5/5 visible-base survivors failed one-parameter retention. | Recurring with a small reached sample. | Structural warning, not a population rate |
| Regime dependence | Chronological blocks changed sharply, but most intraday reports lack fixed regime labels. | Suggested, not directly measured for most campaigns. | Unresolved; do not relabel chronology as a named regime |
| Symbol or sleeve concentration | Exposed 005: 34/60 symbol failures. Rapid 004: 29/35 instrument and 35/35 sleeve failures. | Common across intraday and daily breadth. | Structural |
| Event/release/bucket concentration | Event Drift and Opening Breakout depended on very few dates; Relative Volume failed its bucket gate throughout. | Common in sparse/event campaigns. | Structural for the tested small calendars and thresholds |
| Insufficient activation/sample | Lead-Lag max 3 versus 12 sessions; Relative Volume max 6 versus 12; Event Drift max 2/10 events. | Common in autonomous and event campaigns. | Structural for the current exposed period, not proof about future events |
| Excessive drawdown | Several daily families failed; no Exposed 005 parent failed its discovery drawdown gate. | Campaign-specific. | Not a main calibrated intraday cause |
| Late-stage controlled failure | Rapid 002 failed benchmark and concentration after 28 controlled records. | Rare because few candidates reached controlled evaluation. | Real rejection, not evidence that controlled gates are too strict |
| Infrastructure/control failure | V1, Exposed 002-004, and Fed Campaign 3. | Repeated operational lesson. | Never strategy evidence |

The dominant cross-campaign pattern is not one failure. Early intraday work was distorted by churn
and coarse costs. After calibration, gross-edge weakness, sparse activation, concentration,
chronology, and immediate-neighbor fragility became the binding sequence.

## 5. What the program learned

### A. Exact hypotheses reasonably rejected

- The frozen five-ETF daily moving-average, momentum, long-horizon momentum, relative-strength,
  risk-managed momentum, and inverse-volatility contracts.
- Rapid 002's exact 40/40/10 candidate; Rapid 003's fixed five-ETF family universe; Rapid 004's
  A-U daily rules on the 37-ETF exposed universe.
- The exact Exposed 001 and Exposed 005 intraday grids.
- Event Drift's joint long-only gap/reaction contract, Event Repricing's relative leader
  continuation, Opening Breakout's first-30-minute SPY contract, and Prior-Low's reclaim contract.
- Autonomous Campaign 1's fixed SPY-to-QQQ catch-up and Campaign 2's joint relative-volume drift.

These rejections do not transfer to every possible strategy bearing a similar label.

### B. Hypotheses weakly tested because of sample size

- Scheduled-event drift and opening behavior. Ten eligible BLS events with one to four active dates
  cannot establish a broad event premium.
- Same-clock relative-volume drift. Positive gross evidence appeared in four parents, but at most six
  active sessions and one profit bucket supplied no robustness sample.
- Early daily relative strength. The exact contract stopped correctly, but one training range and
  45-53 trades do not reject all cross-sectional allocation.

### C. Genuinely untested hypotheses

- Fed-policy absorption. Campaign 3 produced no strategy result.
- Cross-sectional multi-hour behavior across a broader intraday ETF universe.
- Overnight close-to-open effects separated from intraday returns.
- Signals conditioned on historical quotes, depth, or trade imbalance. Quotes have been used for
  cost calibration, not strategy features.
- Causally timestamped release surprise versus consensus, rates/yields, futures relationships, and
  options-derived state.

### D. Partial evidence that failed robustness

- Exposed 005's trend-pullback candidate passed return, stress, delay, drawdown, activity, edge, and
  concentration gates, then failed one immediate neighbor.
- Relative Volume's strongest row earned 0.878% and 15.106 gross bps/trade, but all profit occupied
  one participation bucket and only six sessions activated.
- Opening Breakout's 4-bp point was positive with 7.34 gross bps/trade, but only three events
  activated and event concentration failed.
- Rapid 002 passed 19 gate groups, then failed benchmark wins and concentration.
- Rapid 003 produced strong-looking full-range and stress results, but fixed-block, activity,
  concentration, or neighbor evidence rejected every survivor.

### E. Infrastructure lessons, not market lessons

- A failed loader, acquisition boundary, task transport, or vanished process says nothing about
  expected returns.
- A literal stale database status is not live authority.
- Attempt IDs, leases, heartbeats, create-once reports, process preflight, and stage barriers are
  necessary and reusable.
- Partial results from Exposed 002/003 cannot support family screening or parameter choice.

## 6. Direct answers to the strategic questions

- **Did generic every-session five-minute continuation fail mainly because there was no gross
  edge?** Not cleanly. V2 was confounded by repeated exact-weight scheduling and legacy costs.
  Exposed 001 was cost-dominated. Under the calibrated model, weak gross edge became a leading but
  non-universal failure.
- **Were costs the primary bottleneck after recalibration?** No. They reduced returns but activation,
  gross edge, concentration, chronology, or neighbors usually bound first.
- **Did slower holding periods behave better?** They improved cost efficiency and produced the best
  calibrated intraday candidate, but did not establish qualification. Daily long-horizon momentum
  also failed. Slower is a justified direction, not a proven advantage.
- **Did sparse/event strategies have higher information value?** They sometimes had larger apparent
  edge per trade, but the small reused calendar made concentration and sample size decisive.
- **Was SPY/QQQ relative behavior more robust than absolute direction?** No. Event Repricing's
  relative continuation was negative at all nine points even when the chosen leader was positive.
- **Did chronology matter more than transaction friction?** For the advanced calibrated intraday
  candidates, yes. Many other parents failed before chronology.
- **Did neighbors repeatedly kill promising candidates?** Yes where reached: Exposed 005's one
  serious candidate and Rapid 003's five base survivors. The sample is too small for a broad rate.
- **Did one event, month, symbol, or bucket create recurring false positives?** Yes. Event, symbol,
  sleeve, and participation-bucket concentration recurred across otherwise different campaigns.
- **Is the event sample too small for meaningful qualification?** Yes for the completed event
  campaigns. More parameter search on the same ten events would increase researcher freedom, not
  information.

## 7. SPY/QQQ five-minute surface assessment

Classification: **B. MOSTLY EXHAUSTED**.

Broad search on SPY/QQQ five-minute OHLCV should stop. The repository has exposed frequent
continuation, moving-average, gap, opening-range, breakout, pullback, prior-level, relative-volume,
cross-asset, event-drift, event-repricing, and rejection mechanisms across the available pre-June
periods. The strongest calibrated survivor failed its local parameter neighborhood. Later campaigns
reused the same market path and small event calendar. Another broad grid would make it easy to keep
changing thresholds until one backtest passed.

The surface is not **effectively** exhausted because Fed absorption never ran and richer causal
information has not been tested. Those are not reasons to reopen broad OHLCV search. A future Fed or
microstructure study would require a new data type, mechanism, and authorization.

## 8. Material dimensions and slower horizons

| Horizon | Edge and cost case | Statistical case | Main disadvantages | Decision |
| --- | --- | --- | --- | --- |
| 5-minute | Small edges, frequent state changes, and exact timing dominate | Many bars but highly dependent observations | High researcher freedom and delay sensitivity | Stop broad SPY/QQQ OHLCV search |
| 15-minute | Some noise reduction, but still many decisions and small edge per trade | More samples than 30/60m | May retain the same microstructure noise | Do not lead with it |
| 30-minute | Can hold 2-4 hours with one entry set per session; costs are small relative to a 5+ bp target edge | Twelve symbols and about 13 decision bars per full session add breadth without treating bars as independent | Needs synchronized multi-symbol intraday support | Preferred |
| 60-minute | Lower turnover and timing sensitivity | Six full hours plus a partial final interval complicate session alignment | Fewer decisions and awkward half-hour close | Valid fallback within a later plan, not a parallel axis now |
| Overnight | Plausibly larger gap-scale edge and low turnover | Broad universe gives cross-sectional observations, but session count remains the unit | Gap risk, auction/slippage semantics, corporate actions | Secondary direction |
| Multi-day | Low cost-to-edge ratio and simple execution | Long history available | Rapid 003/004 already exposed much of the daily rule surface; fewer independent periods | Defer another broad daily program |

The end goal should remain systematic unattended PAPER trading, but intraday frequency should not.
The better target is one fixed portfolio decision per session with multi-hour holds. This reduces
turnover and operational load without assuming that slow signals are profitable.

## 9. Broader universe and richer information

The proposed traded universe is:

`IWM MDY XLK XLF XLE XLV XLI XLP XLY XLU XLB XLRE`

`SPY` is a context and benchmark symbol, not a traded member. This rule takes every sector ETF in
the frozen Rapid 004 universe plus its small- and mid-cap broad sleeves. The choice uses the prior
non-return liquidity, completeness, product, and duplicate-exposure screen; no hidden strategy
return selects a symbol. Cross-sectional samples will still be correlated, so gates count sessions
and folds as independent units and treat symbol breadth as concentration evidence only.

Remaining exclusively in US equity ETFs is justified for one next program because the repository
already has stock/ETF acquisition, XNYS validation, costs, and PAPER controls. Futures, options, or
international market sessions would change data licensing, calendars, contract identity, margin,
and execution at the same time. Those may become useful, but they are not the smallest defensible
next test.

| Data type | Causal/history prospect | Burden and leakage risk | Use now |
| --- | --- | --- | --- |
| 5m SIP OHLCV | Alpaca's historical API supports five-minute SIP bars and adjustment controls | Moderate acquisition; corporate-action and bar-condition validation required | Yes, then aggregate deterministically to 30m |
| Relative volume | Derived only from prior completed bars/sessions | Low burden; current-session normalization can leak if not prior-only | Yes, one fixed formula |
| Realized volatility | Causal when derived from completed bars | Low burden, but it adds an unused conditioning choice | Defer; not part of the primary mechanism |
| Historical NBBO quotes | Alpaca exposes paginated historical SIP quotes | Large raw volume; crossed/stale states and entitlement must fail closed | Cost calibration only |
| Quote depth | NBBO size is not full order-book depth | High interpretation risk and incomplete venue depth | Defer |
| Trade imbalance | Historical trades can be causal | Condition filtering, corrections, and storage are substantial | Defer |
| Rates/yields and futures | Economically useful cross-asset state | Vendor, timestamp, roll, calendar, and execution work | Defer to a separate program |
| Official release contents | Causal if original publication timestamp and revisions are preserved | Vintage/revision and parsing controls required | Not in the primary program |
| Consensus/surprise | Strong event rationale | Historical point-in-time consensus is often licensed; vendor timestamps can leak | Defer until a source contract is reviewed |
| Options-derived state | Potential volatility/risk information | Surface construction, corporate actions, liquidity, and licensing are substantial | Defer |

Current provider facts used only for planning: Alpaca documents 1-59 minute and 1-23 hour
historical bars, explicit `sip`/`iex` feeds, adjustment options, and 10,000-record pagination. Its
current Trading API table lists Basic at $0 with 200 requests/minute and Algo Trader Plus at
$99/month with 10,000 requests/minute; its FAQ says historical SIP requests ending at least 15
minutes ago do not require the real-time subscription. Recheck these terms before acquisition:
[bars API](https://docs.alpaca.markets/us/v1.4.2/reference/stockbarsingle-1),
[plans](https://docs.alpaca.markets/us/docs/about-market-data-api), and
[FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).

## 10. Candidate directions

### A. Cross-sectional sector ETF continuation and reversal at 30 minutes

- **Rationale:** sector-level information and temporary price pressure can diffuse over hours rather
  than one five-minute bar. Cross-sectional ranks remove part of the broad market move.
- **Prior motivation:** calibrated costs were not dominant; the best intraday candidate held about
  175 minutes; two-symbol concentration and chronology repeatedly failed.
- **Change:** twelve traded symbols, one fixed midday decision, 30-minute features, 2/4-hour holds.
- **Data:** historical SIP 5m OHLCV plus prior-only derived volume/volatility; quotes only for costs.
- **Expected turnover/sample:** medium-low, at most one entry per symbol/session; roughly 1,500
  exposed sessions, with sessions/folds as the statistical unit.
- **Execution/engineering:** feasible long-only ETF execution; moderate research engineering.
- **Risks:** correlated symbols, sector concentration, market-regime dependence, and rank
  instability.
- **Failure information:** a clean failure would show that breadth and slower aggregation do not
  repair the OHLCV edge, concentration, and chronology problems.

### B. Cross-sectional overnight ETF effects

- **Rationale:** close-to-open returns may carry distinct risk premia and information arrival with
  larger edge per trade and lower turnover.
- **Change:** overnight rather than regular-session intraday exposure; broad ETF cross-section.
- **Data:** daily or close/open bars, corporate actions, and auction-aware spread/slippage evidence.
- **Expected turnover/sample:** one round trip per selected symbol/session; about 1,500 exposed
  sessions.
- **Execution/engineering:** research data are accessible, but causal close-order and opening-auction
  semantics need new code and cost evidence.
- **Risks:** gap tails, auction slippage, dividends, stale overseas NAVs, and fewer independent
  periods.
- **Failure information:** would decide whether overnight decomposition contains more usable edge
  than already-exposed close-to-close daily rules.

### C. Macro-release surprise repricing across ETFs

- **Rationale:** price changes should depend on surprise relative to consensus, not only a calendar
  label.
- **Change:** new causal information content, more asset sleeves, and 30-120-minute holds.
- **Data:** point-in-time official releases, point-in-time consensus, revisions, rates/yields, and
  ETF bars.
- **Expected turnover/sample:** very low turnover but few independent releases.
- **Execution/engineering:** substantial data-contract and timestamp work.
- **Risks:** vendor leakage, revisions, licensing, release concentration, and low sample size.
- **Failure information:** high, but only after the causal data contract is credible.

### D. Quote/liquidity-conditioned intraday signals

- **Rationale:** OHLCV may omit spread, imbalance, and liquidity states that determine short-horizon
  behavior.
- **Change:** new microstructure information, likely 5-15-minute horizon.
- **Data:** SIP quotes/trades and possibly depth.
- **Expected turnover/sample:** high sample count but highly dependent observations and higher
  turnover.
- **Execution/engineering:** substantial storage, cleaning, simulator, and validation work.
- **Risks:** severe feature multiplicity, feed-condition errors, queue/impact omission, and overfit.
- **Failure information:** useful but expensive; not justified before the simpler broader-horizon
  test.

### E. Futures/rates cross-market transmission

- **Rationale:** rates and index futures may lead ETF repricing and trade nearly around the clock.
- **Change:** market, information set, calendars, and execution venue.
- **Data:** point-in-time futures with rolls, rates/yields, and synchronized ETF or futures prices.
- **Expected turnover/sample:** moderate with good time-series length.
- **Execution/engineering:** substantial contract, margin, roll, calendar, data, and broker work.
- **Risks:** roll construction, stale cross-market clocks, licensing, leverage, and a new risk model.
- **Failure information:** high, but platform expansion is not justified as the first response to the
  current evidence.

## 11. Decision matrix

Every score is 1-5, where 5 is better. For engineering complexity and overfitting risk, 5 means
lower burden or lower risk. Scores are decision aids, not empirical probabilities. Totals apply
equal weights only.

| Direction | Econ | Novel | Edge | Cost | Sample | Avail | Clean | Eng | Exec | Overfit | Protected | Info | Platform | Total / 65 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A. 30m sector cross-section | 4 | 4 | 3 | 4 | 5 | 4 | 4 | 3 | 4 | 4 | 4 | 5 | 4 | **52** |
| B. Overnight ETF cross-section | 4 | 5 | 4 | 5 | 3 | 5 | 3 | 3 | 3 | 4 | 4 | 4 | 4 | **51** |
| C. Macro surprise repricing | 5 | 5 | 4 | 5 | 2 | 2 | 2 | 1 | 3 | 2 | 4 | 5 | 2 | **42** |
| D. Quote/liquidity intraday | 4 | 5 | 2 | 2 | 5 | 3 | 2 | 1 | 2 | 1 | 4 | 4 | 2 | **37** |
| E. Futures/rates transmission | 4 | 5 | 4 | 4 | 4 | 2 | 3 | 1 | 2 | 3 | 4 | 5 | 1 | **42** |

### No-program comparator

Pausing and authorizing no new program has no strategy hypothesis to score. It requires no new data
or engineering, adds no researcher degrees of freedom, and preserves every future boundary. It also
adds no new evidence and leaves the next strategy decision to the already sealed V3 chronology after
2027-04-15. Because no historical campaign produced a controlled-qualified candidate, rejecting
this proposal and pausing is a fully supported, lower-cost decision. The matrix ranks research
directions only and is conditional on the user deciding that another bounded research program is
worth its cost and uncertainty.

## 12. Recommendation and deferrals

**Primary:** Direction A. It changes both the two-symbol universe and five-minute decision horizon,
uses obtainable causal data, preserves long-only unlevered execution, and directly tests the two
most plausible remedies supported by prior evidence: breadth and a larger edge-per-trade horizon.
It is materially different in universe, signal structure, decision frequency, and holding period,
not in data type: it remains OHLCV research.

**Secondary fallback:** Direction B. Use it only under a separate prospective plan if Direction A
is rejected before execution or finishes negative. Do not authorize it automatically from Direction
A results.

**Defer:** Direction C until a point-in-time consensus license and revision policy exist; Direction D
until the simpler OHLCV test says richer microstructure is worth its burden; Direction E until ETF
research justifies a new market, leverage, roll, and execution stack.

**Reject now:** another broad SPY/QQQ 5m OHLCV grid, another broad daily ETF A-U search, and complex
ML. Their main justification would be untried combinations on already exposed surfaces.

This recommendation does not assume that research must continue. Choose the no-program comparator
if the uncertain information gain does not justify moderate research engineering and new data.

## 13. Proposed bounded program

Proposed identity: `multi-hour-sector-etf-research-001`.

Status: `PROPOSED - NOT AUTHORIZED FOR STRATEGY EXECUTION`.

### Mechanism and scope

Use fixed initial cash of $100,000. At one fixed 11:30 New York decision each session, aggregate each
set of six consecutive complete regular-session 5m SIP bars into one 30-minute bar. For lookback
`L`, return is the 11:30 completed close divided by the close `L` completed 30-minute bars earlier,
minus one. Residual return is the ETF return minus SPY's return over the same bars. Same-clock
relative volume is cumulative volume over the 24 complete 5m bars in `[09:30, 11:30)` New York
time divided by the arithmetic mean of the same sum over exactly 20 prior complete sessions.
Missing, invalid, or incomplete required input is a terminal data failure. Test two families:

1. relative continuation when positive residual return coincides with relative volume at least 1.2;
2. residual reversal when negative residual return of at least 10 bps in magnitude coincides with
   relative volume at least 1.5.

Each family has the same two fixed axes: a 1/2 30-minute-bar lookback and a 4/8 30-minute-bar hold.
Select at most three eligible symbols by the stated rank, breaking residual-return ties by symbol
ascending. Selected ETFs receive fixed one-third weights; unused slots remain cash and weights are
not rescaled. No signal means cash. There is no shorting, leverage, resizing, reentry, or second
decision. Unsupported early closes remain flat. Entry and exit targets use the scenario's fixed fill
delay; the exit target occurs exactly 4 or 8 completed 30-minute bars after the decision.

The fixed benchmark is participation-matched SPY: on each candidate-active session it holds SPY for
the same target interval at the candidate's total gross target weight, with the same cash, costs,
and delay; otherwise it holds cash. Exposed reports carry paired benchmark metrics. Each controlled
block stores separate candidate and benchmark Normal specifications bound to the frozen candidate
activation trace.

### Budget and sequence

| Item | Ceiling |
| --- | ---: |
| Strategy families | 2 |
| Parent configurations | 8, four per family |
| Strategy campaigns | 2: one exposed campaign and one separately authorized controlled campaign |
| Discovery specs | 48 = 8 configs x 3 fixed blocks x Normal/zero-cost |
| Walk-forward and neighbor specs | 108 maximum = 6 unique configs x 9 folds x Normal/zero-cost |
| Stress/delay specs | 72 maximum = 2 serious configs x 9 folds x 4 scenarios |
| Controlled specs | 4 maximum = one frozen candidate and one benchmark in each of two blocks |
| Aggregate run specifications | **232 maximum** |
| Infrastructure attempts | 3 per spec, 696 maximum; attempts do not create new strategy specs |
| Workers | 4, with stage barriers |

Campaign 1, `multi-hour-sector-etf-exposed-001`, uses only the three fixed Rapid 003/004 exposed
blocks from 2020-07-27 through 2026-07-31. It runs all eight discovery configurations before reading
merit. At most one base per family advances, together with its two immediate grid neighbors. The
base rank is worst fixed-block Normal benchmark excess, aggregate Normal benchmark excess,
aggregate Normal return, maximum drawdown, then canonical identity. The final rank is worst-fold
Normal benchmark excess, aggregate Normal benchmark excess, aggregate Normal return, then canonical
identity. At most one final candidate may freeze.

Campaign 2, `multi-hour-sector-etf-controlled-001`, does not exist unless Campaign 1 freezes one
candidate, an independent review passes, the next future block is complete and isolated, and the
user grants new one-use authority for that block. Block B also requires Block A to pass and a new
one-use authorization. Campaign 1 cannot create either authority.

### Gates and stop rules

Discovery requires positive Normal and zero-cost aggregate returns, aggregate Normal return above
the paired benchmark, at least two positive fixed blocks, at least two blocks with positive Normal
benchmark excess, at least 60 active sessions in each fixed block, at least 300 aggregate round
trips, maximum 10% drawdown, average gross trade edge of at least the greater of 5 bps or three times
modeled round-trip friction, cost/gross-profit no more than 35%, symbol profit concentration no more
than 35%, block profit concentration no more than 60%, exact accounting, and equal paired signal
traces.

Walk-forward uses nine fixed 252-train/126-test/126-step folds. It requires positive Normal and
zero-cost aggregates, aggregate Normal return above the paired benchmark, at least seven positive
Normal folds, at least six benchmark wins, worst Normal fold at least -1%, no more than 35% symbol
concentration, and every discovery edge/cost/accounting invariant. Both immediate neighbors must
have positive aggregate Normal return and median base-return retention must be at least 50%.

Stress uses symbol-specific p95 and p99 spreads, two- and three-5m-bar delays, and the same folds.
Every variant must remain positive in at least seven folds; Stress A/delay-2 must retain at least
50% of Normal profit and Stress B/delay-3 at least 25%.

Stop globally on an empty stage, data/control contamination, a terminal deterministic failure,
attempt exhaustion, any protected-boundary breach, or the 232-spec ceiling. Do not add a family,
parameter, symbol, feature, chronology, inverse hypothesis, replacement range, or weaker gate.

## 14. Data acquisition plan - not executed

- **Provider/feed:** Alpaca historical stock API, explicit `feed=sip`.
- **Symbols:** twelve traded ETFs plus SPY context/benchmark.
- **Exploratory range:** 2020-07-27 through 2026-07-31, split physically into the three existing
  fixed chronology blocks.
- **Source timeframe:** 5m. Build 30m features only by deterministic six-bar regular-session
  aggregation; never ask the provider to define session alignment.
- **Adjustment:** `all`, bound as `provider-adjusted-all-v1`.
- **Timestamps/calendar:** inclusive UTC bar opens on exact XNYS regular sessions; retain expected
  early closes and reject missing, duplicate, extra normalized, or malformed bars.
- **Raw policy:** retain every mapped transport record unchanged; publish normalized Parquet and a
  canonical manifest only after full validation.
- **Identity:** content-address the provider, feed, request, universe, adjustment, processing,
  calendar/timestamp policies, raw SHA-256, and normalized fingerprint.
- **Rate limits:** design for Basic's current 200 requests/minute and 10,000 records/page; paginate
  and resume by immutable request segment. A faster paid plan must not change bytes or policy.
- **Expected provider cost:** $0 under current historical Basic terms; contingency $99 for one month
  of Algo Trader Plus if entitlement or acquisition-time terms require it. Reconfirm before spend.
- **Expected storage:** plan for 2-5 GB for roughly 1.5 million 5m bar rows plus immutable raw data,
  normalized data, manifests, quote-calibration samples, and quarantine headroom.
- **Cost calibration:** acquire fixed historical SIP quote windows for every symbol before strategy
  execution. Freeze p75/p95/p99 symbol half-spreads, regulatory fees, timestamp rules, stale/crossed
  handling, and a small-order capacity limit in a reviewed artifact.
- **Capacity:** use fixed $100,000 initial cash and fail an order above 1% of the symbol's median 5m
  close-times-volume across exactly 20 prior complete sessions.
- **Isolation:** exploratory artifacts must end at 2026-07-31. V3 and future controlled timestamps
  must not exist in the exploratory catalog. Controlled blocks use separate storage and one-use
  access records.

No data was acquired during this review.

## 15. Platform changes

Reusable:

- `DatasetService`, content-addressed manifests, Parquet validation, and XNYS 5m completeness;
- `ResearchAttemptStore`, three-attempt expired-lease recovery, four-worker process execution, and
  stage barriers;
- immutable canonical reports, cohort freezes, launch-control review, qualification, and one-use
  protected-access patterns;
- regulatory-fee formulas and the quote-calibration method;
- broker-free intents, risk, reconciliation, and PAPER controls for a much later qualified handoff.

Required for Campaign 1:

- an explicit SIP historical-bars acquisition path; the current Alpaca adapter is fixed to IEX;
- the fixed 12-symbol universe and SPY context binding;
- deterministic 5m-to-30m aggregation with early-close rules;
- synchronized atomic multi-symbol intraday targets and cross-sectional metrics;
- symbol-specific quote calibration and a capacity check;
- program-specific plans, reports, screens, and synthetic equivalence tests.

Research engineering is **MODERATE** because the data, attempt, reporting, and control layers already
exist. Any PAPER planner for this portfolio would be **SUBSTANTIAL** and is outside this proposal.

## 16. Controlled evaluation and protected data

Already exposed:

- daily bars/results from 2020-07-27 through 2026-07-31 in the five- and 37-ETF programs;
- SPY/QQQ 5m results from 2025-07-01 through 2026-06-30 in V2;
- SPY/QQQ pre-June bars reused through 2026-05-29 by later exposed campaigns;
- June 2026 as ineligible/exposed by frozen disposition, even where a later runner did not read it.

Still protected and untouched here:

- Intraday V3 A: 2026-10-01 through 2026-12-03;
- Intraday V3 B: 2026-12-04 through 2027-02-09;
- Intraday V3 C: 2027-02-10 through 2027-04-15;
- daily independent evaluation: 2018-01-02 through 2019-12-31;
- protected campaign results and PAPER/broker/live state.

The proposed program does not use the daily 2018-2019 seal or any V3 date. Its proposed controlled
blocks are:

1. 2027-04-16 through 2027-10-15;
2. 2027-10-18 through 2028-04-14.

The dates are fixed now, before acquisition or strategy results. Each block requires complete XNYS
calendar coverage and a separate one-use user authorization. No substitute range is allowed. Block
B remains unopened if Block A fails. The installed calendar currently ends before all proposed
dates, so a later reviewed calendar dependency update is a pre-acquisition requirement, not license
to move the dates.

Each block independently requires positive candidate Normal return, return above the
participation-matched SPY benchmark, at least 15 active sessions and 30 round trips, maximum 10%
drawdown, the same gross-edge, cost, symbol-concentration, and accounting gates used in discovery,
and no undefined metric. Both blocks must pass; aggregate performance cannot rescue a failed block.
The candidate, source, formulas, benchmark, costs, and gates freeze before Block A. A failed Block A
stops the campaign before Block B acquisition or access; a passing Block A still grants no Block B
authority.

## 17. Researcher-degrees-of-freedom audit

| Flexibility | Bound |
| --- | --- |
| Families | Exactly two; no inversion after results |
| Parameters | Two axes per family, two values per axis |
| Configurations | Eight total |
| Universe | Twelve fixed traded symbols; SPY context only |
| Features | Exact close-to-close residual return and prior-only same-clock relative volume formulas |
| Chronology | Three fixed blocks and nine fixed folds |
| Selection | Frozen lexicographic base/final ranks; symbol ties ascending; one final candidate maximum |
| Gates | Visible disqualifying gates; undefined values fail |
| Succession | Empty stage stops; controlled campaign requires separate user authority |
| Escape hatches | No new family, feature, symbol, range, threshold, inverse, or retry class |

An operator cannot keep changing choices until one passes without creating a new reviewed program.

Automated feature/model search is not appropriate now. The effective sample is closer to about
1,500 correlated sessions than to twelve times every 5m bar. A regularized linear ranker would still
multiply feature, target, loss, and retraining choices; trees and representation models would add
more leakage and stability burden. Use the two hand-designed economic hypotheses. Any later ML
proposal needs a separate program and a substantially larger, causally stable feature panel.

## 18. Independent strategic review

An independent read-only reviewer challenged exhaustion, evidence scope, novelty, data-mining risk,
controlled independence, the 232-run budget, simpler alternatives, engineering burden, and bias
toward continued research. The first pass found two material issues:

1. signal formulas, cash/sizing behavior, selection order, benchmark mechanics, and controlled gates
   were not frozen tightly enough to support the no-adaptation claim;
2. the decision matrix omitted the valid choice to pause and authorize no new program.

The revised review and proposal freeze those mechanics and add the no-program comparator. A second
read-only pass found no remaining issue. The reviewer judged the **mostly exhausted** classification
defensible, Direction A materially different in universe and horizon while still OHLCV-based, the
controlled dates independent if the frozen sequence is enforced, the research-only engineering
estimate reasonable, and the `48 + 108 + 72 + 4 = 232` budget internally consistent.

## 19. Exact authorization decision

The next user decision is only whether to authorize strategy implementation planning and historical
data-acquisition planning for `multi-hour-sector-etf-research-001` under the companion proposal's
exact universe, data boundary, two-family/eight-configuration design, 232-run ceiling, false
authority flags, and independent pre-execution review.

Authorization must **not** grant data acquisition or strategy execution. A later reviewed
acquisition artifact and explicit approval are required before acquiring data. A later reviewed
plan, data binding, cost model, implementation, launch control, and explicit strategy-execution
approval remain required before a strategy run. Controlled evaluation, PAPER, broker writes, and
live execution require still later separate authorizations.
