# Program 007 corporate-action metadata qualification

Program 007, `multi-hour-sector-etf-research-006`, has an exact one-use corporate-action metadata
qualification proposal. The names-only preflight passed for both required credential names, and
immutable proposal v2 has a finding-free review with status `READY FOR USER AUTHORIZATION`:

- `PROGRAM_007_CORPORATE_ACTIONS_API_KEY_ID`
- `PROGRAM_007_CORPORATE_ACTIONS_API_SECRET_KEY`

Run the non-consuming preflight with:

```console
uv run trading-lab data acquire program-007-metadata credential-preflight
```

It prints only `PASS` or one `MISSING: <name>` line per absent variable. It does not load a value,
build an authenticated client, contact Alpaca, create authority, or consume the one use.

## Frozen qualification

The credential-free request plan uses two chains: all thirteen symbols and all thirteen CUSIPs.
Both use `GET https://data.alpaca.markets/v1/corporate-actions`, `region=us`,
`start=1990-01-01`, `end=2026-08-29`, `limit=1000`, `data_quality=complete`, and `sort=asc`.
The `types` parameter is omitted. Each chain may use four pages; the run permits two to eight
requests and responses, 1,048,576 bytes per response, 1,048,577 bytes for bounded oversize
detection, 8,388,608 bytes total, one credential load, and zero retries.

The public issuer, exchange, and SEC ledger remains authoritative. Alpaca can only corroborate it
or reveal a discrepancy. Qualification requires one reconciled 2-for-1 `forward_split` effective
`2025-12-05` for each of XLB, XLE, XLK, XLU, and XLY. A missing control, unexpected relevant event,
symbol/CUSIP disagreement, unusable economic date, pagination failure, oversize response, or
ambiguous transport fails the consumed use. A matching result cannot prove global completeness or
rule out a delayed future record.

## One-use boundary

The future active packet may set only `provider_contact`, `credential_access`, `source_requests`,
and `source_qualification` to true. It cannot call an OHLCV or broker endpoint, admit a dataset, or
run a strategy. Every other authority flag stays false.

Before activation, the code requires clean synchronized `main`, exact reviewed artifacts, the
caller-supplied root, and both credential names. It repeats repository and credential checks under
the private run lock, loads the credential pair once, and writes the irreversible claim immediately
before the first provider transport invocation. A sent or ambiguous transport consumes the use and
gets no retry. Raw bounded bytes and their SHA-256 receipt are stored and fsynced before parsing.

Blocked proposal v1 and its review remain immutable historical evidence and cannot activate. The
v2 external authorization root is derived only from the exact proposal, review, implementation
lineage, and final clean synchronized `main`; it is not stored in Git. Reporting that root does not
activate authority or create a claim. Activation and qualification execution require a later exact
user authorization.
