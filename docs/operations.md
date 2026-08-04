# Operations

1. Set `TRADING_LAB_HOME` to an isolated writable directory when the default is unsuitable.
2. Run `trading-lab doctor`; stop on any failed check.
3. Import offline fixtures with `trading-lab data import-fixture`.
4. Inspect `trading-lab status`, `data describe`, and `data validate`.
5. Preserve the dataset directory and manifest together when moving evidence.

Recovery: artifact directories are authoritative. After moving a disposable `catalog.sqlite3` aside, run `trading-lab data rebuild-catalog`. Never edit an artifact in place. The execution store can list journal-verified `submission-unknown` orders without changing state. The production reader can retain a sanitized immutable 404 from an exact lookup, but that result is historical evidence only. A read-only proof can bind it to later complete clean reconciliation and the unchanged protected controls for operator review. It does not authorize retry. There is no broker process, retry, cancel action, or live recovery procedure in this phase.

Run this command to inspect paper blockers without changing the execution database:

```console
trading-lab paper assess-startup --authorization AUTHORIZATION_ID --risk-config config/risk/alpaca-paper-v1.json
```

Supply both `--wheel` and `--manifest` only from an installed attested build. A nonzero result means
paper startup is blocked; never bypass a listed reason.

Cancellation recovery also remains read-only. Run a production exact-client-order lookup after the
attempt and any unknown outcome, then assess its immutable lookup provenance. Only a latest matching
terminal event can report `resolved-canceled`, `resolved-rejected`, or `resolved-filled`. A
nonterminal or stale lookup remains unresolved. No result authorizes another broker call.

Before any future paper mutation work, use [paper-write-readiness.md](paper-write-readiness.md). Its
current status is not ready and every listed blocker remains mandatory. Process opt-in opens only
the outer runtime gate and cannot override transaction-bound authority.

## Sustained paper observation

Start a bounded read-only campaign with `trading-lab paper start-observation CAMPAIGN_ID`. Set its
maximum gap to the planned sampling interval plus measured scheduler tolerance and set an explicit
duration. Run `record-observation` on that schedule and `assess-observation` after interruptions.
The command exits nonzero for current drift, read failure, or staleness. Failure records contain no
broker response text. A later healthy sample restores current health but does not erase historical
failure or drift counts. Campaign completion remains stale unless a final sample falls within the
configured gap of the end time. These records grant no activation, risk, settlement, emergency, or
broker authority.

Record action-plan equivalence with `paper record-equivalence`. Supply one replay plan, one shadow
plan, and every paper intent key for the decision. Replay and shadow files use this strict shape:

```json
{
  "schema_version": "paper-action-plan-v1",
  "strategy_id": "strategic-allocation-portfolio",
  "strategy_version": "1",
  "source_data_fingerprint": "64 lowercase hexadecimal characters",
  "configuration_fingerprint": "64 lowercase hexadecimal characters",
  "targets": [{"symbol": "SPY", "quantity": 4}],
  "evidence_fingerprints": ["64 lowercase hexadecimal characters"]
}
```

The store derives the paper plan from the named immutable quantity intents. It compares strategy,
source data, configuration, and sorted targets. A mismatch remains evidence and exits nonzero. The
comparison reads no broker state and grants no execution authority.

The first sustained campaign uses the Windows task `SystematicTradingLab-PaperObservation` as an
external 10-minute timer. It pins the exact attested runtime and campaign ID, runs from the repository
directory so the ignored `.env` loads, starts missed work when the computer becomes available, wakes
from sleep, and expires at the campaign end. It cannot run while the computer is powered off; any
resulting gap remains evidence. The one-shot command and database remain authoritative, not the task.
