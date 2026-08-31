# Program 011 raw OHLCV structural qualification

Program 011, `multi-hour-sector-etf-research-010`, is `PROPOSED-NOT-AUTHORIZED`. The source
contract and sample are frozen. No child authority, credential access, provider request, dataset,
strategy result, or protected action exists.

## Prospective correction

Program 010 remains `TERMINAL-FAIL-CONSUMED-NO-RETRY` and cannot replay. Its retained first page
showed why the received-order rule was invalid: each symbol array was timestamp-ascending, but JSON
object members did not appear in lexicographic symbol order. JSON object-member order has no semantic
meaning.

Program 011 keeps the Program 010 transport, pagination, missingness, coverage, and resource rules.
For each retained page it now:

1. Parses and validates the raw response after persistence.
2. Requires strictly ascending timestamps inside each symbol array.
3. Sorts parsed rows deterministically by symbol and timestamp.
4. Applies duplicate, repeated-page, token cycle/reuse, zero-progress, and cross-page frontier checks.

Timestamp equality or regression inside one symbol array fails after raw retention. JSON symbol
member order alone cannot fail. Cross-page order must still advance after deterministic sorting.

The implementation reuses Program 010's tested pagination engine. Program 010's public exact-type
entry points, terminal revocation, errors, and received-order semantics remain unchanged.

## Frozen sample

The sample rederives from committed evidence across Programs 002-010 and the current protected
chronology inventory:

- 199 OHLCV-observed sessions, fingerprint
  `3fb677dadeefb21dcab5a49d0d53030e064c9ac1a60becd1c5322b0b172729c8`
- 145 protected sessions inside the eligible chronology
- 1,188 eligible unobserved and unprotected sessions, fingerprint
  `9274779e7ce6d72349dea14a5f61849b374cde796036041075c8b6e3d5691bba`
- selection seed `program-011-raw-sip-qualification-sample-v1`

The three lowest normal-session digests select `2025-02-27`, `2025-01-06`, and `2021-04-28`.
The still-unrequested `2025-11-28` early-close pre-split control and `2025-12-15` post-split control
complete the sample.

| Session | Role | Coordinates |
| --- | --- | ---: |
| `2021-04-28` | normal | 1,014 |
| `2025-01-06` | normal | 1,014 |
| `2025-02-27` | normal | 1,014 |
| `2025-11-28` | early-close, pre-split | 546 |
| `2025-12-15` | post-split | 1,014 |

The total is 4,602 coordinates. Sample fingerprint is
`549a83f7af681088012d2867dfa63aebe6878f817fc13e692e3fe948e9ca62bc`. Program 010's observed
`2021-05-25` session is excluded. Prior observations cannot count as Program 011 qualification
evidence.

## Unchanged controls

- One exact XNYS regular session per thirteen-symbol chain.
- `GET https://data.alpaca.markets/v2/stocks/bars` with raw SIP `5Min`, `sort=asc`, `limit=1000`,
  and `asof=2026-07-31`.
- Null `next_page_token` is the only successful chain terminus.
- Sixteen pages per session is a resource cap, not an expected page count.
- Raw bytes are bounded and fsynced before parsing or continuation.
- Zero automatic retries.
- Terminal absence is `SOURCE-MISSING`; absence after an incomplete frontier is unobserved.
- Every symbol needs a strict majority: 40 of 78 normal coordinates or 22 of 42 early-close
  coordinates.
- No imputation or alternate-source repair during qualification.

Only a later complete exposed acquisition may apply the frozen whole-session dataset-admission
policy. No strategy may run before admission.

## Immutable controls

- Source commit/tree: `15477e31543b132da4994587d993a84fb7af801a` /
  `6d690298d1939473cd76f45ec106a82c02fa3267`
- Implementation root: `db3abe746e6d60b4a906137791f545208bb633c9c2a5f3a896f6ed8b17ee928d`
- Implementation SHA-256/fingerprint:
  `683e411d898c64d4d5ff872368572dec20879555695aa6390f09831f5b01430e` /
  `19da1ee5205bffc060cdeb860da77b245d8732cc782a415a45140abf762442bc`
- Proposal SHA-256/fingerprint:
  `e87a319a98cda47200d615d1a4cb1416033b545a313fd1d9f63c8791c42b5bb3` /
  `50747cee0606229b6e79c59f6a204806a415f3b4dde6205c1b5e950651357447`

The next gate is a finding-free independent review of the exact implementation and proposal, full
quality checks, green CI, and a clean synchronized-main merge. A later, separate slice must bind and
review an exact one-use standing child authority before names-only credential preflight, activation,
or provider transport.
