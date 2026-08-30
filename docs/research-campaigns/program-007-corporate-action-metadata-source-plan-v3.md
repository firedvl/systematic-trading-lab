# Program 007 corporate-action metadata plan v3

Program 007, `multi-hour-sector-etf-research-006`, remains
`PROPOSED-NOT-AUTHORIZED`. This plan grants no credential access, provider request, source
qualification, OHLCV access, dataset admission, strategy result, protected access, PAPER action,
broker write, or live action.

The immutable contract is
`config/research/program-007-corporate-action-metadata-source-plan-v3.json`. It supersedes v2 only to
bind immutable official provider-documentation evidence. The scientific contract, query, budgets,
and authority state do not change. V1 required a provider-documented maximum creation lag. Current
Alpaca documentation says no such guarantee exists, so that gate could never establish negative-event
completeness.

## Evidence model

The public issuer, exchange, and SEC ledger is the foundation. Ledger v3 closes all thirteen current
identities for the `2020-06-26` through `2026-07-31` feature chronology under a bounded
best-evidence standard:

- XLB, XLE, XLK, XLU, and XLY each have a 2-for-1 split effective `2025-12-05`.
- IWM, MDY, SPY, XLF, XLI, XLP, XLRE, and XLV are
  `SUPPORTED-NO-KNOWN-ACTION` for feature-relevant unit changes.
- IWM's 2-for-1 split effective `2005-06-09` is outside the chronology.
- MDY and SPY retained their tickers, CUSIPs, CIKs, and trust terms across their January 2026
  marketing-name changes.

`SUPPORTED-NO-KNOWN-ACTION` is not proof that no event ever occurred. It means continuous identity
is supported and the reviewed first-party evidence revealed no applicable unit-changing event.

A future Alpaca query can only corroborate this ledger as of observation or reveal a discrepancy.
It must recover the five positive controls, reconcile current symbol and CUSIP chains, and fail on an
unresolved new unit or identity event. A matching or empty result cannot prove that a delayed record
will not appear later.

## Alpaca contract

Official documentation retrieved `2026-08-29` defines:

The plan binds `config/research/program-007-alpaca-corporate-actions-public-contract-evidence-v1.json`.
That manifest records the exact official Markdown response SHA-256, 47,697-byte size, ETag, upstream
`updatedAt`, embedded OpenAPI fingerprints, and one short no-guarantee excerpt. It retains no
third-party response body and grants no provider or credential authority.

- `GET https://data.alpaca.markets/v1/corporate-actions`;
- inclusive `start` and `end` interval bounds;
- results sorted by `process_date`;
- `limit` from 1 through 1000 and opaque `next_page_token` pagination;
- `region=us` and `data_quality=complete`;
- no guarantee on creation time because provider and Alpaca processing can delay records.

The documentation does not literally state that `start` and `end` filter `process_date`. Program 007
therefore makes only the following claim: request the inclusive interval and require every returned
`process_date` inside it. The query is process-date-bounded corroboration, not proof of undocumented
filter semantics.

The exact query interval is `1990-01-01` through `2026-08-29`.
`METADATA_QUERY_END=2026-08-29` is fixed before access. `METADATA_OBSERVATION_AS_OF` will be the UTC
time after a future bounded query completes. The observation time does not extend the query interval
or establish finality.

The `types` parameter is omitted. The adapter handles all sixteen current REST arrays and rejects an
unknown array:

`reverse_split`, `forward_split`, `unit_split`, `cash_dividend`, `stock_dividend`, `spin_off`,
`cash_merger`, `stock_merger`, `stock_and_cash_merger`, `redemption`, `name_change`,
`worthless_removal`, `rights_distribution`, `partial_call`, `reorganization`, and
`capital_gains_distribution`.

Current first-party OpenAPI documentation includes `capital_gains_distribution`; v2 retains it.

## Dates and transforms

`process_date` records provider processing provenance. It is never substituted for economic timing,
and the code does not assume it is close to an economic date. A record with an old `ex_date` or
`effective_date` and a later `process_date` remains valid.

Program 007 uses documented action-specific fields:

- `ex_date` for forward and reverse splits, dividends, spin-offs, rights distributions, and capital
  gains distributions;
- `effective_date` for unit splits, mergers, and reorganizations;
- no inferred economic field for redemptions, name changes, worthless removals, or partial calls.

A feature-relevant event without usable economic timing fails closed. Only stable-identity forward
and reverse splits get an exact factor, `Fraction(new_rate) / Fraction(old_rate)`. Raw prices remain
unchanged. Ambiguous unit or identity events require investigation or exclusion.

## Frozen request

Two chains query all thirteen current identities: one ascending symbol chain and one ascending CUSIP
chain. Each uses `region=us`, `start=1990-01-01`, `end=2026-08-29`, `limit=1000`,
`data_quality=complete`, and `sort=asc`.

Each chain may use four pages. The whole run allows at most eight requests, eight responses, 1 MiB
per accepted page, and 8 MiB in accepted response bytes. The bounded transport reads at most 1 MiB
plus one byte so it can detect an oversized page. It retries zero times and rejects redirects,
repeated tokens, malformed tokens, duplicate IDs, conflicting canonical content, unknown arrays,
identity mismatches, and budget overruns.

HTTP 401 is authentication failure. HTTP 403 is terminal `METADATA-ACCESS-FAIL`. HTTP 429 is
terminal. None permits a retry, purchase, or fallback provider.

## Transport and storage

The module now contains the fixed-host GET-only client, a disabled-redirect bounded standard-library
transport, and create-only private storage under
`.trading-lab/program-007-corporate-action-metadata-v2/`. Every intent is stored before transport.
Every bounded raw body and SHA-256 receipt is stored and fsynced before size, status, JSON, schema, or
semantic checks. Files use mode `0600` under a `0700` root, and the run holds `flock`.

The persistent executor requires an explicit mock transport and rejects the real HTTP transport. It
accepts only an explicit environment mapping, loads the two synthetic test values once, stores no
secret, and has no CLI or authority path. Tests exercise the path without reading the process
environment or contacting Alpaca.

## Stop and next step

Program 007 remains proposed. Ledger v3 permits a later metadata authority proposal; it does not
grant one. After this plan, implementation binding, finding-free review, CI, and clean synchronized
`main` merge, the next separate step is a reviewed one-use Program 007 corporate-action metadata
qualification authority proposal followed by a new explicit user grant. Do not create, authorize, or
execute that proposal in this change.
