# Intraday Event Drift 001 final report

Status: complete negative exposed result.

This campaign tested one frozen scheduled-event drift hypothesis. It does not establish future
profitability. No candidate advanced past discovery, no controlled evaluation occurred, and no
trading authority opened.

## Immutable outcome

- Source commit: `6cce913be06c270477da1ad0eede665cf039593b`
- Outcome: `no-controlled-qualified-candidate`
- Runtime database SHA-256: `1b3e3f8a6449845e01789efa98859e60f88349fd09951c202236e6b0926cb193`
- Final-report JSON SHA-256: `a1fc8c7569d78857cd08ccfbefbeea37a15e9caba555660168553dd0eda87124`
- Final-report fingerprint: `08db46a4836150c718cad3f944d900fad57342603527080fc9569a5754d23c73`
- Runtime Markdown SHA-256: `d1afbcbe7b45bec963e74e380f2790c0c8f9df54f14c3f69e8b4b44a52d2fa99`
- Final-freeze SHA-256: `4858a1fc6f18a787a4dfb6eb58b7a6c7ede370ec776ad16c15bb3a8a2d01b931`
- Final-freeze fingerprint: `3878f153376cd5eb617e0478870b4ad0b5c334cdfb5e2cc1b077fce5faecfdd4`
- Runtime file count: 95

Terminal validation found 18 completed runs, 18 attempts, zero pending, zero running, zero failed,
and no active lease. All 18 report paths and hashes are unique. Each report file matches
the canonical database hash and byte count. Final artifact fingerprints recompute, SQLite integrity
is `ok`, foreign-key checks are empty, and every authority field remains false.

## Stage accounting

| Stage | Candidates | Runs | Result |
| --- | ---: | ---: | --- |
| Discovery | 9 parents | 18 | all completed once; 0 eligible |
| Walk-forward | 0 | 0 | not opened |
| Stress and delay | 0 | 0 | not opened |
| Immediate neighbors | 0 | 0 | not opened |
| Final exposed cohort | 0 | — | frozen empty |
| Controlled evaluation | 0 | 0 | no eligible untouched range |

The campaign completed its full required path. Later stages correctly contained no work because no
parent passed every discovery gate.

## Complete discovery result

Returns below use the frozen initial capital and calibrated cost model. `Cost/gross` is execution
friction divided by gross profitable trade profit. Each active event creates one SPY and one QQQ
round trip.

| Candidate | Reaction bars | Reaction floor (bps) | Active events | Round trips | Avg hold (bars) | Normal return | Zero-cost return | Cost/gross | Gross edge (bps/trade) | Event concentration |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ied001-a01-b01` | 3 | 10 | 2 | 4 | 48 | `0.004671043524414160804868933` | `0.004765737948206343340661757` | `0.01984045340368316147156332187` | `23.80636769944451719737189002` | `0.7343443323060845448841855427` |
| `ied001-a01-b02` | 3 | 20 | 0 | 0 | — | `0` | `0` | undefined | undefined | undefined |
| `ied001-a01-b03` | 3 | 40 | 0 | 0 | — | `0` | `0` | undefined | undefined | undefined |
| `ied001-a02-b01` | 6 | 10 | 2 | 4 | 45 | `0.003411055123199470109398762` | `0.00350567892757425011868177` | `0.02695715298362642309831448531` | `17.51388389684557387985368746` | `0.6187491610660699647340699449` |
| `ied001-a02-b02` | 6 | 20 | 1 | 2 | 35 | `0.00211058749582979205753082` | `0.002157852516498381306627498` | `0.02188686449594703627612263456` | `21.57852516498381306627498054` | `1` |
| `ied001-a02-b03` | 6 | 40 | 0 | 0 | — | `0` | `0` | undefined | undefined | undefined |
| `ied001-a03-b01` | 12 | 10 | 1 | 2 | 29 | `0.000092325252240510897614675` | `0.00013952748702848031244464` | `0.1716295342282233462257075004` | `1.395274870284803124446403863` | `1` |
| `ied001-a03-b02` | 12 | 20 | 1 | 2 | 29 | `0.000092325252240510897614675` | `0.00013952748702848031244464` | `0.1716295342282233462257075004` | `1.395274870284803124446403863` | `1` |
| `ied001-a03-b03` | 12 | 40 | 1 | 2 | 29 | `0.000092325252240510897614675` | `0.00013952748702848031244464` | `0.1716295342282233462257075004` | `1.395274870284803124446403863` | `1` |

All nine parents failed the minimum of four active events and eight completed round trips. All nine
also failed the maximum `0.5` positive-profit event concentration. Eight failed release-class
concentration, six failed average gross edge, six failed symbol concentration, and three zero-trade
parents failed both positive-return gates and every undefined trade metric. Three zero-trade parents
also failed cost-to-gross profit because the metric was undefined. Undefined values failed as
frozen.

Only two of the ten discovery event sessions ever activated: the 2025-07-03 Employment Situation
release and the 2025-10-24 CPI release. No PPI event activated. The best-populated parent earned
73.4% of positive event profit from one event; the next earned 61.9% from one event. These are
exposed observations from two dates, not evidence of a repeatable regime or future edge.

## Postmortem

Signal weakness was primarily insufficient and concentrated activation, not calibrated friction.
The joint opening-gap and positive-reaction contract produced at most two active events out of ten.
Raising the reaction floor removed trades quickly. Waiting from 3 to 12 reaction bars left one event
and reduced average gross edge from `23.8064` to `1.3953` basis points per trade on the comparable
surface.

Normal-versus-zero-cost degradation was small for the active 3- and 6-bar parents. Their
cost-to-gross ratios were about 2.0% to 2.7%, and zero cost did not change the activation, event
concentration, or sample-size failures. The 12-bar parents had 17.2% cost-to-gross because their
remaining gross edge was small. The frozen cost model therefore did not manufacture the negative
decision.

Turnover was low by design: zero to four completed round trips and turnover of zero to about `4.01`
times capital. Average holding periods were 29 to 48 five-minute bars. Lower turnover did not solve
the evidence problem because too few independent event sessions contributed returns.

No candidate reached the frozen latency, stress, walk-forward, or exact-neighbor stages. The
campaign therefore supplies no valid stress-retention, delay-retention, chronological-stability, or
formal neighbor-stability result. The complete discovery grid shows discontinuous activity across
thresholds, but that observation must not be relabeled as a completed neighbor test. Market-regime
dependence also remains unmeasured; release labels and two active dates are not regime evidence.

This was one family. Its negative disposition does not establish that scheduled events lack useful
intraday information. It closes only the exact joint long-only drift contract and its frozen grid.
The candidates must not be rescued by lowering gates, rounding failures, or rerunning the same
contract under friendlier assumptions.

## Execution performance and recovery

- Workers: 4 spawned processes
- Attempt wall time: `114.012441` seconds
- Sum of run durations: `427.290886` seconds
- Effective concurrent work factor: `3.748`
- Run duration minimum / mean / median / maximum: `13.949813` / `23.738383` / `18.856203` / `38.650973` seconds
- Runs completed by worker: 4, 4, 5, and 5
- Recorded infrastructure interruptions, retries, and terminal failures: 0
- Heartbeat events: 0; every run finished before the fixed 60-second heartbeat interval
- Maximum recorded process peak RSS: `195969024` bytes
- Minimum recorded available memory: `2926575616` bytes

The effective concurrent work factor is not a controlled sequential benchmark. It only divides
summed per-run durations by the attempt wall interval. No SQLite busy, lock, publication, or lease
failure was recorded, but the runtime does not instrument lock-wait duration. The prior controlled
fixture benchmark of `3.426x` remains the valid one-versus-four speedup measure. Four workers remain
the default: this run used 3.748 of four possible concurrent work slots, and the immutable evidence
does not establish unused capacity that would justify a six- or eight-worker benchmark.

## Disposition and next hypothesis

The next campaign must be prospective and structurally different. A suitable direction is
scheduled-event relative continuation: after a BLS release, use the signed completed-bar QQQ-minus-
SPY reaction to form one symmetric dollar-neutral pair, hold it for a fixed multi-hour interval,
and avoid target changes. This tests gradual relative repricing between rate-sensitive growth and
the broad market. It does not lower Event Drift's gates, reuse its joint long-only candidates, or
claim the exposed event dates are independent.

Any such campaign requires a new identity, exact plan and source bindings, friction-anchored entry
thresholds, simultaneous neighbor rules, a finding-free independent review, exact merged-main
launch control, and the existing four-worker restart-safe executor before execution.

## Protected and authority boundaries

June market data/results, Intraday V3, daily 2018–2019, PAPER/broker/live state, and
`strategic-allocation-21` remained untouched. Research qualification, controlled evaluation,
protected holdout, PAPER execution, broker writes, and live execution all remain false.

**INTRADAY EVENT DRIFT 001 COMPLETE — NO CONTROLLED-QUALIFIED CANDIDATE**
