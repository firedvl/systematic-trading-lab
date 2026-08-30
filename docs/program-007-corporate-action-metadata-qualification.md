# Program 007 corporate-action metadata qualification

Program 007, `multi-hour-sector-etf-research-006`, is terminally consumed and failed. Exact root
`a3e65f85bcc9adaedcfe3842d3b148ed1fb6230ac303ff2cdedadfe33c0bfbbd` activated authority v2 on
clean synchronized main `a624acbe86177323e88042c5dbfe6ef00862e1c8`. The run loaded the required
credential pair once, wrote its immutable claim immediately before transport, made one request,
and received one HTTP 200 response of 115,628 bytes with zero retries.

The retained first symbol-chain page contains 538 cash-dividend records and five forward-split
records. Frozen normalization stopped on the first cash-dividend record whose required `cusip` was
empty. In total, 189 cash-dividend records across all thirteen requested symbols have an empty
`cusip`. The CUSIP chain, positive-control qualification, symbol/CUSIP reconciliation, and complete
date and pagination validation were not reached.

The metadata qualification result is `FAIL`. Preserve the ignored private authority, claim, intent,
body, receipt, lock, and terminal failure records. Do not retry, issue replacement authority, buy an
upgrade, use a fallback, start Program 007 OHLCV qualification, admit a dataset, or execute a
strategy. Public terminal artifact SHA-256/fingerprint is
`99bc4397909f364efac2f189351bff9ebaae9b886833fc7e0555b3fa5751119f` /
`991bd9892ee32f4badc08350160a03c3514e0ae1a33dfa623406b534c73bd352`.
Current code verifies that exact artifact and rejects authority derivation before credential access
or private-state creation.

The historical names-only preflight checks these required names:

- `PROGRAM_007_CORPORATE_ACTIONS_API_KEY_ID`
- `PROGRAM_007_CORPORATE_ACTIONS_API_SECRET_KEY`

Run the non-consuming preflight with:

```console
uv run trading-lab data acquire program-007-metadata credential-preflight
```

It prints only `PASS` or one `MISSING: <name>` line per absent variable. It does not load a value or
contact Alpaca, but it grants no authority to replay the consumed qualification.

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

Blocked proposal v1, proposal v2, and their reviews remain immutable historical evidence. The
authorized root and private active packet remain execution evidence, not current authority. The
consumed failure permits no second activation or qualification execution.
