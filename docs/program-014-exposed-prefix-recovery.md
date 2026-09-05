# Program 014 exposed-prefix recovery

Program 014, `multi-hour-sector-etf-research-013`, is
`IMPLEMENTED-PROSPECTIVE-NOT-AUTHORIZED`. It preserves Program 013's source, chronology,
pagination, missingness, structural admission, privacy, and no-strategy contracts. Programs 012 and
013 remain terminal and immutable.

Read-only forensics found a completed whole-session prefix followed by one Program 013 intent-only
page frontier. Program 014 may reuse only the completed sessions in place, discard the incomplete
session and page, and issue the frontier once under a later reviewed child. It has zero retries and
may never reissue a retained Program 014 request.

The runtime uses a distinct ignored private root and one lock-held activation/execution transaction.
It holds the Program 014 exclusive lock, both predecessor shared locks, and the Git-policy snapshot
through public-terminal fsync. It rejects restarted launcher state, ambiguous or surviving
operational checkpoints, changed predecessor evidence, protected overlap, and budget exhaustion
before credential access or transport. The unchanged cumulative limits are 22,176 request intents
and at most 22,174 receipted responses.

Runtime source commit/tree/root is
`e3c1e49e45c5c75c29feb050fb687ca4405ccc07` /
`0a66061a785617c1d0475dd54a9f26bf03adcc7b` /
`e5bff812bc2a47b349f56f8860ea350c61574bd209883e7edae88be8f463391c`. The implementation
artifact SHA-256/fingerprint is
`c233f35850d709bca15d3abae2bbf8463d5da570f92afdcd5efe667fce55b147` /
`a79e7d4281b0265b3d7a2302f1910ca23d20366ba7338f3583cad731ecd58d2d`.

Fresh independent design/correctness and alternate defensive-boundary reviews passed without
findings. Dedicated security-review attempts returned infrastructure failures only: HTTP 503, a
policy-service rejection before review output, and HTTP 429. The alternate review used the approved
fresh-context independent-review path. The full suite reports 1,759 passed and four skipped; Ruff,
mypy, secret, shell, wheel, and diff checks pass.

## Current gate

Do not run either command yet:

```console
uv run trading-lab data acquire program-014-ohlcv credential-preflight
uv run trading-lab data acquire program-014-ohlcv run
```

The runtime binding must first merge to clean synchronized `main`. That exact main then becomes the
child runtime source. Only the exact child authority and its independent review may be added before
the names-only credential preflight. The public terminal digest remains intentionally unset until a
separately reviewed post-run closeout binds the exact redacted terminal.

No credential presence or value, provider request, private Program 014 state, dataset admission,
strategy calculation, or strategy return has occurred. Controlled or protected access, purchases,
PAPER, broker writes, and live execution remain disabled.
