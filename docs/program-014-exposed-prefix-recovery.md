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

The exact child authority and its finding-free independent review are merged on clean synchronized
`main` at `d81c09183ac3b3c48229205a9bf8f9034f6c69c9`. The child artifact SHA-256/fingerprint is
`561299d05ac40f41513d92a3076f0eaf789c861f9a17d442a3d34e6ef2a54e2a` /
`3b46ea5689db84cee4e069628574a117c23a2374deea02b2bcde1f6a48b3a4b4`; the independent review
artifact SHA-256/fingerprint is `b946917095f89a4d4c858a9df10658eda093ff6e1b917a5fed62fc9ea22e2061` /
`57cf2f12c069e0a2dbae9f8a758b4e282ceca2ebb93acdc3fd6dc1631d9e8a07`. The review passed all 12
required challenges with no findings. The derived child identity fingerprint is
`526cf757f999aa751c6dd60a18515eb65fbaaf7f60e88a943741ee6ed5378fd3`.

The names-only preflight ran on September 5, 2026 and reported both required environment-variable names
missing from the current process:

```text
PROGRAM_006_ALPACA_API_KEY_ID
PROGRAM_006_ALPACA_API_SECRET_KEY
```

No credential value was read and no provider request occurred. Credential restoration is the current
human-attention boundary. After those existing variables are exported, retry only the names-only preflight:

```console
uv run trading-lab data acquire program-014-ohlcv credential-preflight
```

When that preflight passes, the authorized runtime command is:

```console
uv run trading-lab data acquire program-014-ohlcv run
```

The public terminal digest remains intentionally unset until a separately reviewed post-run closeout binds
the exact redacted terminal.

No credential presence or value, provider request, private Program 014 state, dataset admission,
strategy calculation, or strategy return has occurred. Controlled or protected access, purchases,
PAPER, broker writes, and live execution remain disabled.
