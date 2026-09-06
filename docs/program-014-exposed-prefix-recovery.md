# Program 014 exposed-prefix recovery

Program 014, `multi-hour-sector-etf-research-013`, is `FAIL-CONSUMED-NO-RETRY`. It preserved
Program 013's source, chronology, pagination, missingness, structural admission, privacy, and
no-strategy contracts. Programs 012 and 013 remain terminal and immutable.

Read-only forensics found a completed whole-session prefix followed by one Program 013 intent-only
page frontier. Program 014 could reuse only the completed sessions in place, discard the incomplete
session and page, and issue the frontier once under a reviewed child. It had zero retries and may
never reissue a retained Program 014 request.

The runtime used a distinct ignored private root and one lock-held activation/execution transaction.
It held the Program 014 exclusive lock, both predecessor shared locks, and the Git-policy snapshot
through public-terminal fsync. It rejected restarted launcher state, ambiguous or surviving
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

## Terminal result

The reviewed child left consumed runtime state after transport began. The built-in recovery path
sealed `RUNTIME-FAILURE` with `admission_passed=false`, no dataset lineage, no Program 002 admission,
and no strategy calculation or return. Recovery made no second credential check or provider request.
The public terminal was observed at `2026-09-06T10:52:24.166713Z`. Its SHA-256 is
`8630f5748266f75a676da31ca3463bb25dcf2bb9447eb7b1fbe5c3b4c636ddf9`; its authority
fingerprint is `52be3ed20d80f0abe62b58a6e3d3ce6667279d55a9d04915229f8805c89254dc`; its source
commit is `818a923349ec13b18ec6dc1743e1f136f56bcc8c`.

The closeout requires those exact public bytes and rejects a missing, changed, or invalid terminal
before credential preflight, authority derivation, execution, or private-root access. Program 014
cannot replay or retry. Dynamic acquisition state, detailed failure evidence, private identities,
exact missingness, provider tokens, and market observations remain private.

Independent review found two callable credential-reader bypasses. Commits
`4c3eb75598ead8f8c385ebcabefe18cd09b793a3` and
`085f062b448901e30e22f40732cd6583032cccda` removed the public and internal helpers, respectively;
credential parsing now occurs only inside the lock-bound loader after launcher validation and durable
access reservation. Fresh exact-head correctness and defensive reviews passed finding-free. The
review artifact SHA-256/fingerprint is
`04a5ec8b50a051ed457d0d5dc7cc001c4224be3750cab6c2d552c94d26ba07f2` /
`db9b391c9e7770da16ab2414102a0e8148785c957d8ca5f182eb02acaac9cdb6`. The original dedicated
security reviewer returned HTTP 503 before output; the approved fresh-context alternate path supplied
the final defensive validation.

After merge, bounded offline forensics may support a prospective successor only if the retained
evidence does so without changing the inherited science.

Do not run Program 014 credential preflight or acquisition again. Controlled or protected access,
purchases, PAPER, broker writes, and live execution remain disabled.
