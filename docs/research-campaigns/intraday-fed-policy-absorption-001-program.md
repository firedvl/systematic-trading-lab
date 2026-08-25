# Intraday Fed Policy Absorption 001 program

Status: prospective plan/calendar and implementation reviews are finding-free. Launch control remains
unbound. The second exact-main launch review found a pre-reservation worker-readiness race; its repair
is local to Campaign 3 and is not merged or launch-reviewed. No reservation, attempt, market-data
read, report, or result exists.

Program ID: `intraday-fed-policy-absorption-001`.

Plan SHA-256/fingerprint:
`a3cd20e325f2e9eb6bc794df7a93db3763dab8e55d2fc1e02816a8480907c111` /
`99d03036512b3a8b03f38774e05779982379b1e956906a2ee36f612b52f20140`.

Independent plan/calendar review SHA-256/fingerprint:
`7f6216324a135f9c910edc6257ef1b408ced8d6b33feb9e43d9cd524fee66014` /
`831e85f7e7228652f06d4b5bbe1b3822333d0e53e1ce2d97852ede1a24a262aa`.

Source state revision 5 SHA-256/fingerprint:
`cd68f08b0b95839d41672a5df024e8867759911830f28d0a3d255c61c2643883` /
`c6eaa1acc6af58af2d0f4a937c89ad95690ee8743ec998526b5f16ebdf7ea9af`.

Reviewed state revision 6 SHA-256/fingerprint:
`7c414a92e22ca4ceead8d1cde5ad3429a8a62c5a5bd3ade7f88ce72c38f1b891` /
`4cc76196c71713fbf56a92cd2495a9a8cc137eb749da0ee0511a429144cc6b73`.

Starting main: `0d53fa654f72ebeb262a28713dec6254e87e169a`.

## Frozen provenance and calendar

The first two replacement designs failed control review before commit, implementation, reservation,
market-data read, or result. Their failure records remain immutable. V2 pre-design attestation then
bound a fresh no-history architect to eight exact non-result inputs, including the calibrated cost
model and its review. It required separate scenario-independent signal and scenario-specific
execution traces. The final design came only from that clean packet.

The campaign accepts one indivisible official Federal Reserve metadata calendar: 15 unique full
78-bar XNYS sessions from July 2025 through May 2026, containing eight meeting-minutes publications
and seven policy statements. Period counts are `6/3/2/3/1`. Every publication occurs at 14:00 New
York. Index 53 is the last completed pre-publication bar, index 54 is the publication bar, and index
77 is the final session bar. The 2025-08-22 notation-vote item remains excluded because it is the
wrong class and was published at 10:00 New York.

The calendar and source-evidence SHA-256/fingerprint pairs are:

- calendar: `8bcfd05031b44e2c31861c43aa2b8130d609c82fca9aeec10804809c37a01c97` /
  `54c937bbb42703213efdf14dc4becb50bc0f757bb6f16388254550e12f0c93ba`;
- source evidence: `1d72b74a04eadba87eb178fd7d67dc644c18d31b926f78e7a48f6f9c38f012c8` /
  `ed4dc2c9f638a4ef04da7d292732ee653d0040a5c844a54f90efc588d3005a7b`.

Any calendar count, class, time, session, uniqueness, or source defect closes the campaign before
implementation or market-data access. Dates, classes, and events cannot be widened, removed,
substituted, or selected from market behavior. Release bodies, decisions, votes, projections,
surprises, revisions, and headlines are unavailable to the strategy.

## Frozen signal and execution

For symbol `s`, event `e`, and horizon `h`, the reaction is:

```text
10000 * (close[s,e,53+h] / close[s,e,53] - 1)
```

The nine parents cross horizons `2/4/6` completed bars with inclusive joint SPY and QQQ floors of
`8/16/24` basis points. Parent IDs are:

```text
fedabs-h02-f0008  fedabs-h02-f0016  fedabs-h02-f0024
fedabs-h04-f0008  fedabs-h04-f0016  fedabs-h04-f0024
fedabs-h06-f0008  fedabs-h06-f0016  fedabs-h06-f0024
```

An activation atomically targets SPY and QQQ at one-half each. It allows no leverage, shorting,
resize, reentry, stop, profit target, or later signal. For delay `d`, entry fills occur at index
`53+h+d`. The fixed exit decision follows completed index 74, and exit fills occur at `74+d`, so the
one-, two-, and three-bar delays exit at indices `75/76/77`.

Every fill reads the stored `provider-adjusted-all-v1` bar's `open` before modeled slippage. No
separate unadjusted-price series is allowed. Normal and zero-cost use one-bar delay; Stress A and
Normal-delay-2 use two bars; Stress B and Normal-delay-3 use three. Normal-delay scenarios retain
Normal costs. The exact frozen regulatory-fee model applies to every nonzero-cost scenario.

All arithmetic uses precision-50 base-10 `Decimal` with `ROUND_HALF_EVEN`. Binary floating-point,
epsilon comparisons, tolerance reconciliation, and intermediate quantization are prohibited except
for the fee model's declared upward cent rounding. Symbols process SPY then QQQ, events process by
scheduled UTC then event ID, and every accounting identity compares exactly.

## Traces, screens, and budget

The scenario-independent cross-scenario trace contains only bound identity, causal closes,
reactions, activation, decision, and no-signal evidence. It excludes scenario, cost, delay, intended
fill index, fills, later prices, exit, P&L, accounting output, and its own hash. Normal, zero-cost,
stress, delay, and neighbor evidence for one candidate-period must share this hash.

The scenario-specific execution trace contains the linked cross-scenario hash, scenario, cost model,
delay, intended fills, stored opens, modeled fills, quantities, fees, returns, equity, concentration,
and accounting evidence. It excludes its own hash. Execution hashes are expected to differ across
scenarios.

| Stage | Maximum specifications |
| --- | ---: |
| Discovery: 9 parents × Normal/zero-cost | 18 |
| Walk-forward: cap 3 × 4 folds × Normal/zero-cost | 24 |
| Stress/delay: cap 1 × 4 folds × 4 scenarios | 16 |
| Four immediate neighbors × 4 folds × Normal/zero-cost | 32 |
| Total | 90 |

Discovery and serious-candidate selection use immutable parent order, never result ranking. The
neighbor lattice covers every horizon `1..7` and floors `4/8/12/16/20/24/28`; each selected parent
must pass all four `h±1` or `f±4` neighbors. Every required activity, class-support, return, gross
edge, cost, drawdown, concentration, chronology, fill, fee, trace, and accounting gate is
disqualifying. Undefined required metrics fail.

Only an expired no-result immutable run may retry, without changing bytes, and each run has at most
three attempts. Four workers remain fixed. A nonempty all-gate cohort freezes and records
`WAITING FOR FUTURE UNTOUCHED DATA`. An empty or post-observation interrupted Campaign 3 produces the
three-campaign synthesis and stops. Campaign 4 is prohibited.

## Review and implementation boundary

Independent review recomputed raw hashes and canonical fingerprints, parsed every JSON file without
duplicate keys, proved the calendar/source-evidence bijection, checked all 15 dates and counts,
revalidated timing, costs, traces, gates, neighbors, the `18+24+16+32=90` budget, three-attempt
ceiling, protected boundaries, and false authorities. It found no issue and accessed no market data,
runtime state, protected data, PAPER, broker, live, credential, or `strategic-allocation-21` input.

Immutable state revision 6 binds revision 5, the plan, review, calendar, source evidence, V2
attestation, and both preserved failures. The separate implementation branch adds a plan loader,
strategy, campaign-owned engine and store view, runner, reports, CLI, launch-disabled binding, and
focused tests without market-data read or reservation. The engine executes both half-weight entry or
exit legs from one shared equity base and commits the batch only after both fills succeed. The store
can reject a completed canonical report as terminal campaign evidence without changing the generic
attempt store or any closed campaign source.

Five synthetic fixtures produce byte-identical run specifications, reports, trace hashes, ledgers,
metrics, report hashes, and fingerprints with one and four workers. All seven repository gates pass,
including 1,062 tests with four skips. Independent implementation review rechecked frozen-calendar
identity and timing, atomic pair execution, immutable-result rejection, launch-disable behavior, and
protected boundaries. It found no issue and accessed no market data or protected input.

The implementation must merge through PR and CI. A separate review must then bind launch control to
the exact synchronized implementation main before runtime creation, reservation, market-data read,
or the first campaign run.

Implementation main `1e22649336fe4481ab9c7831c16d929e6227cf85` merged through PR #199 and
passed exact-main gates and five-fixture synthetic equivalence. The first launch review did not bind
it: spawned workers inherited the coordinator's source SHA but did not independently revalidate
their imported worktree before plan/data loading or the specification SHA before claim. The
pre-observation repair adds both checks. It must pass focused and full gates, merge, and receive a
fresh finding-free exact-main review; the failed review grants no launch authority.

Source-guard repair main `a90dc9b864fd8802b9ad915b70f35f7ae59d346c` merged through PR #200 and
passed all seven exact-main gates: 1,063 tests passed with four skips. Five synthetic fixtures were
byte-identical; one worker took `0.766139` seconds and four workers took `0.747410` seconds, a
`1.025060` speedup. The fresh exact-main launch review still failed: the generic process preflight
only proved that the factory and tasks could be pickled, so Campaign 3 reserved specifications before
spawned workers constructed and ran the new source guard.

An initial callback repair changed the shared process executor and passed focused review. The full
suite then proved that closed Event Drift launch evidence binds `research_executor.py` to SHA-256
`099f9ac9572aaaa640d51cb0dde50e2cba378a6ef0b2ddf9b07a63d0ed9b1b81`. The shared executor was
restored byte-for-byte.

The replacement repair is local to Campaign 3. Each stage gets an ephemeral coordinator-owned
attestation directory. Every initial spawned worker validates the loaded source, all stage
specification source SHAs, and the frozen plan, cost, and dataset inputs; writes a PID-bound source
marker; and waits for the full expected set of matching markers with no failure marker. Only then
may any worker create the attempt store and reserve the complete stage. Each worker reserves the full
stage before the unchanged executor sees that worker as ready, so the first task dispatch finds all
stage specifications reserved. A later replacement revalidates the same controls and reuses the
complete matching marker set without adding a marker. A source, input, or peer-attestation failure
stops the waiting pool before any worker opens the attempt store, reserves, claims, or receives a
task. This repair must pass focused and full gates, merge, and receive another finding-free exact-main
review; neither failed review grants launch authority.

June, Intraday V3, daily 2018–2019, protected results, PAPER or broker state,
`strategic-allocation-21`, credentials, and live data remain prohibited. Every authority field is
false. Historical simulation cannot establish future profitability or trading authority.
