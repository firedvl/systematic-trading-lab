# Program 017 exposed-prefix recovery

Program 017, `multi-hour-sector-etf-research-016`, is
`FAIL-CONSUMED-NO-RETRY`. It was not a replay or retry of Program 016.

Read-only forensics bind Program 016's exact scientific contract, reviews, runtime, child, terminal,
and terminal review. Its final partial session contains completed page evidence followed by one
intent-only next-page checkpoint. Program 017 discards that session in full, never reuses or reissues
either request, classifies its coordinates as unobserved, and begins at the next independent session.
Five consumed intents leave at most 22,171 responses under the unchanged 22,176-intent ceiling.

## Bounded runtime design

Program 016 fully reconstructed the predecessor corpus before every transport. Independent review
rejected Program 017 proposal v1 because its proposed spool lacked aggregate storage accounting and
its protected terminal, credential, and topology contracts were implicit.

Proposal v5 removes the spool. Credential preflight performs one full validation pass. Execution
performs one full validation pass before credential presence, makes provider requests with no
predecessor reconstruction at transport boundaries, then performs one final canonical projection
pass after all provider requests complete. All seven controls remain held throughout.

Before every provider call, the runtime must revalidate the exact reviewed authority, synchronized
Git snapshot, held root and lock descriptors, predecessor manifest, disk capacity,
and protected chronology. Immutable predecessor roots and all lock files use an exact full metadata
tuple. Program 017's mutable root keeps stable identity, ownership, and mode; its expected full tuple
refreshes only after an authorized create-only write and parent fsync. Unaccounted drift still fails
before transport. If an authorized write fails after changing root metadata, the runtime enters
irreversible failure-closeout-only mode, validates immutable controls and stable root identity, scans
the root once, permits only the exact failed target delta, prohibits transport, and seals the redacted
terminal without refreshing the continuation baseline. A final metadata check precedes normal
terminal fsync. The stricter 16 GiB additional
free-space reservation explicitly covers remaining raw responses, an 8 GiB final canonical projection
cap, metadata and derived evidence, atomic publication, and safety margin.

V5 also binds the first request to the exact privately rederived next scheduled session, page one,
null incoming token, request identity, and URL. Every Program 017 intent is permanently non-reissuable
after durable persistence; ambiguous transport consumes the request. Private strategy counters must
be exact integer zeros, and the sole public timestamp records terminal closeout only.

Source, pagination, missingness, admission gates, cumulative budgets, zero retry, no reissue,
single-process execution, inline-only credential loading, privacy, and forbidden authority remain
unchanged. Proposal v5 SHA-256/fingerprint is
`10086f90ae320397914f95fdf9c780ae9c782f93a6b65f48f8d9af4f09cd41a7` /
`ecb8bffdbc5af0c5ffc9d189c1d49d5ca99b6b7d2257dcfa1002d747142f8f98`.

Fresh independent proposal design/correctness and defensive reviews pass finding-free. Review
SHA-256/fingerprint is `e2aaecb0c6cd44e359d0ead286aae5513cd6d08ed75e7aa96a91c0506de81000` /
`03ac9a8a0109d3d4a65cfd9d6e2f85d1418b73fdc89928a573e8f83ab89bbf32`.
The runtime is frozen at exact source commit/tree/root
`efcf5ef2abf56167be7f3741c10a98e2acf3e5f8` / `6bd870133b606d2232e00146cfe4777709a4888c` /
`bce103b0719eea804d4ab1e320729f4272a79e18c47c3c313fcd07a32916225e`.
Fresh independent correctness and defensive reviews of that exact runtime pass finding-free after
all raised temp-recovery findings were fixed prospectively. The implementation binding must merge
before a separate exact one-use child and review can exist.

## Terminal result

The reviewed one-use child and its independent review merged on exact clean main before activation.
The transaction later ended before publishing a public terminal. The built-in credential-free
recovery path sealed `RUNTIME-FAILURE` / `FAIL-CONSUMED-NO-RETRY` without another credential load or
provider request. The redacted public terminal records `admission_passed=false`, no dataset lineage,
no Program 002 admission, and no strategy calculation or return. Its SHA-256 is
`4bf6b7e644a72e052d9d861fbd6f3ac499a18fec7b159624bb3caf98e2741de3`; its derived active-authority
fingerprint is `ed1ff2abbf2ea7cc76a04a01f638873b61970bd31e5389588c7e0a763035123c`; its distinct child-artifact
fingerprint is `09a303caec3c589921009c2d2865f115ddcf1b607514050dcb84a967a4225410`; and its runtime source commit
is `40d7f0a2628560eb7b586e4ff9a5df4480fb04fa`.

The closeout requires those exact public bytes and rejects a missing, changed, or invalid terminal
before credential preflight, authority derivation, execution, or private-root access. Program 017
cannot replay or retry. Dynamic acquisition counts, detailed failure evidence, private identities,
exact missingness, provider tokens, and market observations remain private.

Fresh independent terminal review reconstructed the public child and runtime bindings, verified 22
focused terminal tests and 14 direct API/CLI rejection sentinels, and passed finding-free. Its review
fingerprint is `9fe0cf53e78db7768db04c29f6a9ae679f17ce49f73fd58be03cd8d1c4d75945`.

Do not run Program 017 credential preflight or acquisition again. Controlled or protected access,
purchases, PAPER, broker writes, and live execution remain disabled.

Read-only Program 018 forensics validate a completed whole-session prefix followed by one partial
session containing a completed page and an intent-only next page. Any successor must discard that
session in full, preserve six consumed intents, begin at the next independent session, and inherit
the bounded transport-boundary design. Program 018 has no authority.
