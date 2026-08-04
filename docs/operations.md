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
