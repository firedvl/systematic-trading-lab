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

- Source commit/tree: `1b04483966c4463bb8d84cf504f965d813aa4ee2` /
  `1f6ae8a7af6e7c8c87d93ead6f0b75b7ebdf525a`
- Implementation root: `f397c827ceb766e5854ed8007e9591e6f6dc236276e83addfc854fff4258b0df`
- Implementation SHA-256/fingerprint:
  `6bc00a76f5681cec5ae560ede1fd76a1ae8e02eb6954a0e483b3f129e8ddd05d` /
  `3a4a310fb9e4eb0baee3439f5a626710c57c1d5070e0546d33fc3b2904a97bb9`
- Proposal SHA-256/fingerprint:
  `ed25205a35bb89ce36326c8e554b92661d63b117015ca6762bb65860a4496766` /
  `ab2da3f3d08b9267c6f03b93e09ccd4cd20bbe8359aba2e6f36fbf507f307ae0`

These v2 controls supersede v1's incorrect literal count of 58 bound tests. V1 remains immutable;
the source, sample, scientific rules, gates, budgets, and authority are unchanged.

The next gate is a finding-free independent review of the exact implementation and proposal, full
quality checks, green CI, and a clean synchronized-main merge. A later, separate slice must bind and
review an exact one-use standing child authority before names-only credential preflight, activation,
or provider transport.
