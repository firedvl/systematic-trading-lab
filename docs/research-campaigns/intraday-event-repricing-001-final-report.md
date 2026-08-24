# Intraday Event Repricing 001 final report

Status: complete negative exposed result.

This campaign tested one frozen scheduled-event relative-continuation hypothesis. It does not
establish future profitability. No candidate advanced past discovery, no controlled evaluation
occurred, and no trading authority opened.

## Immutable outcome

- Launch source commit: `9d228e954cf0d007c6de902aabbe3ea8ddff4d70`
- Reviewed implementation source: `5454fb0b075fe29bbc1f1a96f08988ce847fea95`
- Plan SHA-256: `f24cae1372f346be02c0079b931c77d5efb5105a06cf26631b783010851bd8b8`
- Plan fingerprint: `2f98e0cc4565435c9974f65791fd830f7fb9509730f31872f97d77484c00c489`
- Launch-control SHA-256: `5605cd28ddb1e3d1851aeab20ec415f9680e9fdf2a28e17aad0439fb24204794`
- Launch-control fingerprint: `910a4764efde8cecb6c17be24c04c863ed9c910d9279ab57cec3219a951db2c2`
- Outcome: `no-controlled-qualified-candidate`
- Runtime database SHA-256: `af9ba44a82c48f58de283b63b056f04a6b0ab8adfc8f536c8f7a5cb3f9bb226a`
- Final-report JSON SHA-256: `ce6c763e71487d16ba75518836c9788f9ef8be7921a55bffa48eb0580f1bfc9e`
- Final-report fingerprint: `4d07181494898ffd2b342706879f12b45d7689b3f93ce8a7ef4287d1067c6660`
- Runtime Markdown SHA-256: `362b45ab6d12a60bdd2665f1aedbb71f7beea7d049d1d30cde48685a5b101cfc`
- Final-freeze SHA-256: `f763259d540ae8a29de983cf9e0d0d382cc37ef078a4c485e02b43f859285163`
- Final-freeze fingerprint: `d1effb43d73374d7087b3f583b9f4a26f3823d719a05d21c9d1994cbb682fa92`
- Runtime file count: 185

Terminal validation found 36 completed runs, 36 attempts, zero pending, zero running, zero failed,
and no active lease. Every run completed on attempt one. All 36 report paths and hashes are unique.
Each report file and canonical database blob matches its recorded SHA-256 and byte count. Final
artifact fingerprints recompute, SQLite integrity is `ok`, foreign-key checks are empty, and every
authority field remains false.

## Stage accounting

| Stage | Candidates | Runs | Result |
| --- | ---: | ---: | --- |
| Discovery | 9 parents | 36 | all completed once; 0 eligible |
| Walk-forward | 0 | 0 | not opened |
| Stress and delay | 0 | 0 | not opened |
| Immediate neighbors | 0 | 0 | not opened |
| Final exposed cohort | 0 | — | frozen empty |
| Controlled evaluation | 0 | 0 | no eligible untouched range |

The campaign completed its full required path. Later stages correctly contained no work because no
parent passed every discovery gate.

## Complete discovery result

Returns below are leader-arm returns under the frozen initial capital and calibrated costs.
Relative continuation compares matched leader and laggard market returns in basis points. The
runtime ledger retains the exact decimals and every individual gate result.

| Candidate | Reaction bars | Floor (bps) | Active events | Normal return | Zero-cost return | Aggregate relative continuation (bps) | Main failed gates |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `ier001-a01-b01` | 3 | 5 | 6 | `-0.2119%` | `-0.1986%` | `-14.9865` | return, relative continuation, gross edge, release concentration |
| `ier001-a01-b02` | 3 | 10 | 5 | `-0.4648%` | `-0.4542%` | `-23.4092` | return, relative continuation, gross edge, event and direction concentration |
| `ier001-a01-b03` | 3 | 20 | 2 | `-0.0713%` | `-0.0666%` | `-24.4533` | return, relative continuation, activity, gross edge, undefined cost and concentration |
| `ier001-a02-b01` | 6 | 5 | 7 | `0.6030%` | `0.6184%` | `-46.5023` | relative continuation, event and release concentration |
| `ier001-a02-b02` | 6 | 10 | 5 | `0.3664%` | `0.3771%` | `-50.1561` | relative continuation, event, release, and direction concentration |
| `ier001-a02-b03` | 6 | 20 | 3 | `0.0786%` | `0.0845%` | `-15.9539` | relative continuation, activity, event, release, and direction concentration |
| `ier001-a03-b01` | 12 | 5 | 9 | `-0.0697%` | `-0.0489%` | `-41.4758` | return, relative continuation, gross edge, event and release concentration |
| `ier001-a03-b02` | 12 | 10 | 7 | `-0.1625%` | `-0.1456%` | `-20.5926` | return, relative continuation, gross edge, event and release concentration |
| `ier001-a03-b03` | 12 | 20 | 3 | `-0.0601%` | `-0.0535%` | `-2.2323` | return, relative continuation, activity, gross edge, event and release concentration |

All nine parents failed Normal and zero-cost aggregate relative continuation and the minimum average
relative-continuation gate. Aggregate relative continuation ranged from `-50.1561` to `-2.2323`
basis points. Six parents failed both positive leader-return gates and the average gross-edge gate.
Three parents produced positive leader returns, but each matched laggard did better.

Three parents failed the minimum of four active events and four completed round trips per arm.
Eight failed positive-relative-event concentration, eight failed release-class concentration, and
three failed direction concentration. Drawdown, paired selection traces, paired fill matching, and
both accounting identities passed for every parent. Undefined required metrics failed as frozen.

## Postmortem

The frozen signal failed at its central claim. A signed completed-bar QQQ-minus-SPY reaction did not
identify a long-only leader that continued to outperform its matched long laggard over the fixed
24-bar hold. This held at every reaction time and threshold in the frozen grid. Positive absolute
leader returns at three 6-bar points do not rescue the hypothesis because their matched relative
continuation remained negative.

Calibrated friction did not cause the rejection. Every positive Normal leader return remained
positive at zero cost, every negative Normal return remained negative, and Normal-minus-zero-cost
return differences ranged only from about `-0.0047%` to `-0.0209%`. Relative continuation was
identical under Normal and zero-cost diagnostics and negative at all nine points.

Activity ranged from two to nine events, but more activity did not produce positive relative
continuation. Positive relative results were concentrated when defined: only one of eight parents
passed the event-concentration gate, and three reached `1`. One low-activity parent selected only
SPY. The campaign therefore found neither a positive paired effect nor stable, diversified evidence.

No candidate reached latency, stress, walk-forward, or exact-neighbor evaluation. The campaign has
no valid stress-retention, delay-retention, chronological-stability, or formal neighbor-stability
result. Discovery outcomes must not be relabeled as later-stage evidence.

This result closes only the exact relative-leader continuation contract. It must not be inverted
into a reversal campaign, retuned, rerun with friendlier gates, or used to select numeric inputs for
a successor. Any next campaign must freeze a structurally different prospective claim before it
reads its own results.

## Execution performance and recovery

- Workers: 4 spawned processes
- Attempt wall time: `126.733974` seconds
- Sum of run durations: `498.538672` seconds
- Effective concurrent work factor: `3.934`
- Run duration minimum / mean / median / maximum: `13.324780` / `13.848296` / `13.801996` / `14.541914` seconds
- Runs completed by worker: 9 each
- Recorded infrastructure interruptions, retries, and terminal failures: 0
- Heartbeat events: 0; every run finished before the fixed 60-second heartbeat interval
- Maximum recorded process peak RSS: `197869568` bytes
- Minimum recorded available memory: `4775788544` bytes

The effective concurrent work factor is not a controlled sequential benchmark. It divides summed
run durations by the attempt wall interval. No SQLite busy, lock, publication, or lease failure was
recorded. The prior controlled fixture benchmark remains the valid one-versus-four equivalence and
timing evidence; four workers remain the default.

## Protected and authority boundaries

June market data/results, Intraday V3, daily 2018–2019, PAPER/broker/live state, and
`strategic-allocation-21` remained untouched. Research qualification, controlled evaluation,
protected holdout, PAPER execution, broker writes, and live execution all remain false. Do not
relaunch, reset, delete, retry, or reinterpret this terminal campaign.

**INTRADAY EVENT REPRICING 001 COMPLETE — NO CONTROLLED-QUALIFIED CANDIDATE**
