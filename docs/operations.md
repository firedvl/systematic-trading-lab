# Operations

1. Set `TRADING_LAB_HOME` to an isolated writable directory when the default is unsuitable.
2. Run `trading-lab doctor`; stop on any failed check.
3. Import offline fixtures with `trading-lab data import-fixture`.
4. Inspect `trading-lab status`, `data describe`, and `data validate`.
5. Preserve the dataset directory and manifest together when moving evidence.

Recovery: artifact directories are authoritative. After moving a disposable `catalog.sqlite3` aside, run `trading-lab data rebuild-catalog`. Never edit an artifact in place. The execution store can list journal-verified `submission-unknown` orders without changing state. The production reader can retain a sanitized immutable 404 from an exact lookup, but that result is historical evidence only. Each unknown order still requires full clean reconciliation before any future retry assessment. There is no broker process, retry, cancel action, or live recovery procedure in this phase.
