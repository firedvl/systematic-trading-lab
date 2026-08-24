# Intraday Event Opening Breakout 001 final report

Status: complete negative exposed result.

This campaign tested one frozen scheduled-event SPY opening-range continuation hypothesis. It does
not establish future profitability. No candidate advanced past discovery, no controlled evaluation
occurred, and no trading authority opened.

## Immutable outcome

- Launch source commit: `d0eb9a70744afcc77beb7cd6ade73de39aa3cd4b`
- Reviewed implementation source: `017a7cbd91a151fbdc0ddf80f5f580f0c3f9eb34`
- Plan SHA-256: `73ea48a3e2c250db93aca0c7ebef16b5480e118ab9577684089147bb318dfd27`
- Plan fingerprint: `3164757c9f91a1318d48607b24bdaa1c4f3e5439a9657d1b31b0cc32d8163b68`
- Launch-control SHA-256: `dc42631f93e0e9dd91ad2b9c22f743a1a257a890bb709cf6256b62e8877cda9e`
- Launch-control fingerprint: `871b06339bf1d26900dec25b818ba37f51a30f4091a9ad42e2d8f48b2e79dc62`
- Outcome: `no-controlled-qualified-candidate`
- Runtime database SHA-256: `8260aafed73678967dc9b859253ef4fd247d1442cfac6c6ced55a5f3217d9ad7`
- Final-report JSON SHA-256: `f10fd0ebc7cc43c57209045be1b3ea1fb2debd6a34410fb32e15d01c2114fd08`
- Final-report fingerprint: `76a3f7257f53a91522ef6a6353f22de61d50f20b1161b4814463b1018eee9a9d`
- Runtime Markdown SHA-256: `f7e6dddc3e9b8409dc7cd161f588a761f64094dded1ddbf6602be1910faa1ecd`
- Final-freeze SHA-256: `ae8df0e96da1013e52c37d53a20c76f5a6113c8254644ec3b4f7a4b4b05bc527`
- Final-freeze fingerprint: `b7d60b060cd64a7c170404e605afd435094189c6b35174e1db64d227496cd9b1`
- Runtime file count: 35

Terminal validation found six completed runs, six attempts, zero pending, zero running, zero failed,
and no active lease. Every run completed on attempt one. All six report paths and hashes are unique.
Each report file and canonical database blob matches its recorded SHA-256 and bytes. Final artifact
fingerprints recompute, SQLite integrity is `ok`, foreign-key checks are empty, and every authority
field remains false.

## Stage accounting

| Stage | Candidates | Runs | Result |
| --- | ---: | ---: | --- |
| Discovery | 3 parents | 6 | all completed once; 0 eligible |
| Walk-forward | 0 | 0 | not opened |
| Stress and delay | 0 | 0 | not opened |
| Immediate neighbors | 0 | 0 | not opened |
| Final exposed cohort | 0 | — | frozen empty |
| Controlled evaluation | 0 | 0 | no eligible untouched range |

The campaign completed its required path. Later stages correctly contained no work because no parent
passed every discovery gate.

## Complete discovery result

Returns use the frozen initial capital and calibrated costs. The runtime ledger retains the exact
decimals and every gate result.

| Candidate | Buffer (bps) | Active events / round trips | Normal return | Zero-cost return | Average gross edge (bps) | Main failed gates |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ieb001-a01` | 2 | 4 / 4 | `0.0614%` | `0.0693%` | `3.4669` | minimum 5 bps gross edge; 50% event concentration |
| `ieb001-a02` | 4 | 3 / 3 | `0.1042%` | `0.1101%` | `7.3418` | minimum 4 events/trips; 50% event concentration |
| `ieb001-a03` | 8 | 1 / 1 | `-0.0877%` | `-0.0858%` | `-17.1505` | returns, activity, gross edge, undefined cost and concentration |

The 2-basis-point candidate passed both positive-return gates and minimum activity, but its average
gross trade edge was below 5 basis points. Its positive event profit concentration was
`0.5265223380`, above the fixed `0.5` limit.

The 4-basis-point candidate had the highest Normal and zero-cost returns and passed the gross-edge
gate, but only three of ten eligible events activated. Its positive event profit concentration was
`0.5266301866`. Positive return does not replace the frozen activity or diversification evidence.

The 8-basis-point candidate activated once and lost money under both cost settings. Required cost
and concentration metrics were undefined and therefore failed as frozen. Signal-trace and exact
accounting gates passed for all three parents.

## Postmortem

The central claim did not produce enough stable, diversified evidence. Lower breakout buffers found
positive continuation, but the 2-basis-point case lacked the minimum per-trade edge and both positive
cases depended too much on one event. Raising the buffer reduced activity from four events to three
and then one; it did not expose a stronger broad effect.

Calibrated friction did not cause the rejection. The 2- and 4-basis-point candidates stayed positive
at zero cost, and the 8-basis-point candidate stayed negative. Normal-minus-zero-cost return
differences were about `-0.0079%`, `-0.0059%`, and `-0.0020%` respectively. The failed activity,
edge, and concentration gates remain the relevant evidence.

No candidate reached chronological walk-forward, latency, stress, or exact-neighbor evaluation.
The campaign therefore has no valid later-stage retention or stability result. Discovery outcomes
must not be relabeled as later-stage evidence.

This result closes only the exact first-30-minute high breakout contract. It must not be rerun,
retuned with a lower edge floor, given a weaker concentration limit, or used to select numeric
inputs for a successor. Any next campaign must freeze a structurally different prospective claim
before it reads its own results.

## Execution performance and recovery

- Workers: 4 spawned processes
- Attempt wall time: `26.244867` seconds
- Sum of run durations: `79.155549` seconds
- Effective concurrent work factor: `3.016`
- Run duration minimum / mean / median / maximum: `12.810561` / `13.192592` /
  `13.290040` / `13.505190` seconds
- Runs completed by worker: 1, 1, 2, and 2
- Recorded infrastructure interruptions, retries, and terminal failures: 0
- Heartbeat events: 0; every run finished before the fixed 60-second heartbeat interval
- Maximum recorded process peak RSS: `198967296` bytes
- Minimum recorded available memory: `4402266112` bytes

The effective concurrent work factor is not a controlled sequential benchmark. It divides summed
run durations by the attempt wall interval. No SQLite busy, lock, publication, or lease failure was
recorded. The reviewed synthetic one-versus-four equivalence remains the valid process-equivalence
evidence.

## Protected and authority boundaries

June market data/results, Intraday V3, daily 2018–2019, PAPER/broker/live state, and
`strategic-allocation-21` remained untouched. Research qualification, controlled evaluation,
protected holdout, PAPER execution, broker writes, and live execution all remain false. Do not
relaunch, reset, delete, retry, or reinterpret this terminal campaign.

**INTRADAY EVENT OPENING BREAKOUT 001 COMPLETE — NO CONTROLLED-QUALIFIED CANDIDATE**
