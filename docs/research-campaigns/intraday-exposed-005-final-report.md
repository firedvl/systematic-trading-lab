# Intraday Exposed 005 final report

## Outcome

**INTRADAY EXPOSED 005 COMPLETE — NO CONTROLLED-QUALIFIED CANDIDATE**

The frozen exposed campaign completed all 272 required runs. Sixteen of 60 discovery parents
passed the discovery gates, the fixed family cap advanced 14, one passed walk-forward, and that
candidate passed every stress and delay gate. It failed the frozen immediate-neighbor gate, so the
final cohort is empty. No controlled evaluation occurred.

This is a negative historical simulation result. It does not establish future profitability or
support tuning the failed candidate.

## Identity and immutable evidence

- Program: `intraday-exposed-005`.
- Source commit: `789d0f260a43555e5ef2d62e4e74e626b6c4e933`.
- Plan SHA-256: `622d3ad769b12dad857bfe8ee60be4fa1a75b3f3d68becb9b750b323102fd811`.
- Plan fingerprint: `8d30af60d84f1baaa2365096b898960bef759fbafc5215eba68bb81061819ba3`.
- Cost-model SHA-256: `a9e6c2b86c6623d73e089de591c55eeec0711fa55f0933a4e3ea9a1c0c2392af`.
- Cost-model fingerprint: `94fc3ba4663b422fbb0dc0cce7e3d78a7ba81f22d71d5fa986ab6847b7925bb4`.
- Runtime database SHA-256: `0315d336882c43e3b574f4782ae0e592e32db5c3dd1391e7c9c504e32024cdf6`.
- Final-report JSON SHA-256: `ef450142eb29bc11e18c49dd58f83a54f7d49828088c29134380325549be6a10`.
- Final-report fingerprint: `29bad34f12da4d107bf1854a233e17744b8046fd562e19c905d07125a20365b5`.
- Generated `.trading-lab/intraday-exposed-005/final-report.md` SHA-256:
  `7ec76a5a931ae234ad844b0f4129bc3d57c94c039a3577f07558ceee487803e3`.
- Final-freeze SHA-256: `b828b9f1cc4b9183fb846249426727571effdc40a5fcc97415d8376c8975c931`.
- Final-freeze fingerprint: `de8deea77afef8cd271cf77a5e1854a275c538f24013e6ac987e9218b29f10fb`.

The ignored runtime root is `.trading-lab/intraday-exposed-005/`. It remains immutable.

## Campaign ledger

| Stage | Candidates | Runs | Passed or eligible | Advanced |
| --- | ---: | ---: | ---: | ---: |
| Discovery | 60 | 120 paired Normal and zero-cost | 16 | 14 |
| Walk-forward | 14 | 112 paired four-fold runs | 1 | 1 |
| Stress and delay | 1 | 16 | 1 | 1 |
| Immediate neighbors | 1 base and 3 neighbors | 24 | 0 | 0 |
| Final cohort | — | — | — | 0 |

The two eligible discovery points that did not advance belonged to the
`volatility-filtered-breakout-v1` family. The frozen four-per-family cap, not a result-dependent
change, excluded them.

The database contains 272 completed, zero pending, zero running, and zero failed runs. It records
284 attempts. Twelve exact runs retried once after lease expiry and completed on attempt two. No
run used a third attempt.

## Discovery findings

Across all 60 discovery parents:

- 42 had positive Normal return and 46 had positive zero-cost return.
- Median Normal and zero-cost returns were 0.270% and 0.457%.
- Median loss from zero-cost to Normal was 13.70 basis points.
- Median completed round trips were 58, median turnover was 57.85, and median holding time was
  38.76 five-minute bars.
- All 60 zero-cost diagnostics exceeded their paired Normal result; four changed from nonpositive
  Normal return to positive zero-cost return.

Nonexclusive discovery-gate failures were:

| Gate | Failed parents |
| --- | ---: |
| Average gross trade edge below 3 basis points | 39 |
| Positive-profit symbol concentration above 85% | 34 |
| Nonpositive Normal return | 18 |
| Nonpositive zero-cost return | 14 |
| Fewer than eight completed round trips | 6 |

No parent failed the drawdown, cost-ratio, holding-time, turnover-rate, or accounting-identity
gate. The main discovery defects were weak gross edge and symbol concentration. The calibrated
cost model reduced returns but was not the dominant rejection source.

Family-level discovery medians and advancement were:

| Family | Eligible / 6 | Selected | Normal | Zero cost |
| --- | ---: | ---: | ---: | ---: |
| Gap-down failed-continuation fade | 2 | 2 | 1.156% | 1.170% |
| Gap-up continuation | 0 | 0 | -1.505% | -1.443% |
| Opening-range breakout | 3 | 3 | 1.414% | 1.687% |
| Volatility-compression breakout | 1 | 1 | -0.021% | 0.002% |
| Trend-pullback recovery | 1 | 1 | -0.119% | -0.019% |
| Prior-session level | 0 | 0 | 0.086% | 0.158% |
| Morning-afternoon continuation | 0 | 0 | 0.162% | 0.225% |
| Cross-asset confirmed breakout | 3 | 3 | 1.129% | 1.341% |
| Volatility-filtered breakout | 6 | 4 | 1.631% | 1.868% |
| Minimum-edge hysteresis | 0 | 0 | 0.012% | 0.239% |

Most positive discovery results did not persist through chronology. Thirteen of 14 walk-forward
candidates failed the required three positive Normal folds, and 11 failed the positive-May gate.
All three opening-range points and all four volatility-filtered points produced only two positive
folds and failed May. The four volatility-filtered points also produced identical aggregate
walk-forward metrics, so the existing filter did not distinguish activation or outcomes. The
three SPY/QQQ cross-asset confirmation points produced one positive fold each and also failed edge
or concentration gates. The reports contain no formal market-regime labels, so the supported
finding is chronological instability, not performance in a named regime.

## Final serious candidate

The only serious candidate was `ie005-f05-a02-b01`,
`trend-pullback-recovery-v1`, with these exact parameters:

```text
trend_bars=12
minimum_trend_bps=20
pullback_fraction=1/3
recovery_buffer_bps=5
reentry_allowed=false
```

Its four Normal fold returns were 3.967%, -0.376%, 1.864%, and 1.057%. Aggregate evidence was:

| Metric | Result |
| --- | ---: |
| Normal return | 6.511% |
| Zero-cost return | 6.955% |
| Normal loss relative to zero cost | 44.42 basis points |
| Gross profit and loss | $6,952.13 |
| Execution friction | $440.89 |
| Net profit and loss | $6,511.24 |
| Completed round trips | 180 over 143 sessions |
| Average round trips per session | 1.259 |
| Average holding time | 34.99 five-minute bars |
| Average gross trade edge | 7.707 basis points |
| Worst fold | -0.376% |
| Maximum drawdown | 3.317% |
| Positive-profit symbol concentration | 62.46% QQQ |

All frozen stress and isolated-delay gates passed:

| Variant | Aggregate return | Normal-profit retention | Positive folds |
| --- | ---: | ---: | ---: |
| Stress A | 5.907% | 90.72% | 3 |
| Stress B | 6.297% | 96.71% | 3 |
| Normal delay 2 | 6.046% | 92.85% | 3 |
| Normal delay 3 | 6.599% | 101.34% | 3 |

Later delays change fill timing and the session-close cutoff. These results do not show that
latency or extra friction improves the strategy.

The candidate failed the final immediate-neighbor gate:

| Neighbor | Change | Normal return | Base-return retention | Positive |
| --- | --- | ---: | ---: | --- |
| `ie005-f05-a01-b01` | 12 to 6 trend bars | 4.756% | 73.04% | Yes |
| `ie005-f05-a02-b02` | 20 to 40 minimum trend basis points | 3.783% | 58.10% | Yes |
| `ie005-f05-a03-b01` | 12 to 18 trend bars | -2.129% | -32.70% | No |

Median neighbor retention was 58.10%, above its 50% floor. The positive-neighbor fraction was
exactly `2/3`, below the frozen `>= 0.67` threshold. The screen compares exact values; rounding
`2/3` to 0.67 would violate the plan. This was the only failed serious-stage gate, and it closes
the candidate. It must not be tuned, rescued as a near miss, or treated as controlled evidence.

## Attempt recovery and throughput

Attempt activity ran from `2026-08-22T23:24:30.089047Z` through
`2026-08-23T14:06:55.494286Z`, 52,945.405 seconds or 14.707 hours. Three concurrent
four-worker lease-loss episodes produced 12 expired leases under the fixed 300-second rule. The
official restart-safe path retried those exact runs. Empty sealed output and null exit status do
not establish why the workers stopped heartbeating.

- No-worker gaps totaled 2.577 hours; four workers were active for 11.975 hours.
- Mean concurrency over the full attempt span was 3.278.
- Four-worker utilization while workers existed was 99.355%.
- Completed-attempt duration was 513.790 seconds at the median, 1,635.016 seconds at p95, and
  1,902.188 seconds at maximum.
- The runtime retained 2,736 heartbeats. No heartbeat interval exceeded 70 seconds.
- Peak retained worker RSS was 184 MiB. Minimum recorded available host memory was 1.29 GiB.
- CPU-utilization and swap/compression samples were not retained. Host load cannot substitute for
  CPU utilization.
- No SQLite busy error, failed publication, or publication conflict was recorded. Transaction wait
  time and busy-retry telemetry were not retained, so the evidence does not prove zero contention.

Exposed 005 has no valid sequential equivalent, so its wall time does not support a campaign
speedup calculation. The prior deterministic fixture benchmark remains the valid comparison:
3,936.880792 seconds sequential, 1,149.137974 seconds with four workers, and 3.426x speedup.
Four workers remain the default. Any six- or eight-worker benchmark must use deterministic,
non-protected fixtures under controlled host pressure and retain CPU, memory, and SQLite-latency
telemetry.

## Terminal reconciliation

The closeout audit found:

- SQLite integrity check `ok` and no foreign-key violation;
- 272 valid and unique specifications, run IDs, and specification fingerprints;
- exact byte equality between all 272 canonical database report BLOBs and report files;
- 272 unique report paths and exactly-once publications;
- 284 valid attempt histories and 3,304 valid event fingerprints;
- 568 valid sealed attempt-output files;
- exact agreement between the final freeze, all 272 runtime rows, all attempt histories, and each
  stage-ledger reference;
- four datasets revalidated through their read-only catalogs and manifests;
- no active attempt, lease, coordinator, or worker; and
- maximum dataset `read_end` of `2026-05-29T19:55:00Z`.

All six authority fields remain false: research qualification, protected holdout, controlled
evaluation, PAPER execution, broker writes, and live execution. All five protected-access fields
remain false.

## Protected boundaries and disposition

June remains unread and ineligible. Intraday V3, the sealed daily 2018–2019 range, protected
campaign results, PAPER/broker/live state, and `strategic-allocation-21` remained untouched. No
controlled plan, controlled run, qualification fingerprint, candidate recommendation, or
intraday PAPER authority exists. Live trading remains disabled.

The next campaign must use a genuinely new, prospectively frozen economic hypothesis. Supported
directions include scheduled information-event drift with bound event data, a causally available
exogenous market-state condition with activation evidence, broader cross-asset risk transmission,
or a separate quote-grade auction/liquidity study. A new campaign must bind its data, mechanics,
parameters, identities, gates, costs, and no-adaptation rule and pass independent control review
before execution.

Do not lower a gate, expand the failed parameter grid, re-run the near miss under friendlier
assumptions, access June or V3, or change SA21 or PAPER state.

**INTRADAY EXPOSED 005 CLOSED — EMPTY FINAL COHORT; NO CONTROLLED EVALUATION**
