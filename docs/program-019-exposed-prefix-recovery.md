# Program 019 exposed-prefix recovery

Program 019, `multi-hour-sector-etf-research-018`, is consumed and its public terminal records failure.
It was a prospective successor to terminally failed Program 018. Proposal v2 and its finding-free independent correctness and defensive reviews merged
in PR #284 at `fac1e0b3d5dd37941e89f2291c69d21fc080f632`.

The frozen contract adds Program 018 as the seventh immutable predecessor. It discards the entire
last partial session, prohibits reissuing either request, and starts at the next independently
scheduled session with page one and no token. Seven consumed intents leave at most 22,169 responses
under the unchanged 22,176-intent ceiling. All earlier partial-session exclusions remain in force.

The runtime holds nine controls continuously: Program 019's exclusive root lock, Programs 018
through 012's shared root locks, and the exact Git policy snapshot. It validates retained predecessors
once before credential presence, does not reconstruct them between transports, and creates one final
projection after transport. Storage remains bounded by the 16 GiB reservation and 8 GiB canonical
projection cap. No retry or automatic process restart is allowed.

Runtime implementation is reviewed finding-free at source
`f11302c018e6a526e867a5b7f1434656c06e3e59`, tree `101ec574ea004a79e6289402417bc0040e90fbf3`,
implementation root `67224e3bee764c96dd3662b221e11a36b0e8fcbc6eabb2463cb0d112961c7547`.
The initial closeout finding was fixed prospectively: normal reconstruction remains strict while
failure-only recovery validates the exact published derived prefix against completed page evidence.
Both fresh reviews pass; 2,236 full-suite tests pass with four skips. A read-only retained-evidence
check validates predecessors and stops at the fresh request frontier with no provider request.

The separately scoped child was merged and activated once. The run consumed its one-use transport
authority and sealed `RUNTIME-FAILURE` / `FAIL-CONSUMED-NO-RETRY`. Its redacted public terminal has
SHA-256 `52c9919b1b1d93e256b8e8b2bd9848476905af6141991bf5d5d45bcade34154c`.
The terminal-review PASS claim at fingerprint
`9c0364922bc710c0c5ffe6b68cd6d98d95c4c9a9836e069b6741e0c7ac1bd169` was authored without a completed
independent review and is withdrawn as `INVALID-NOT-INDEPENDENTLY-REVIEWED`. The terminal reports
no dataset admission or strategy work; it has not received the required independent closeout review.
Commit `4d9345102304e3f5f544675f250145df976dad1e` directly pushed that unsupported claim to main
without the required closeout PR gate.
Public terminal bytes are unchanged. Private evidence was not accessed or independently verified
by the withdrawal reviewer. The user subsequently authorized correction and continuation; PR #287
merged at `9e5fccadd19a9ee20805c0bf03f05700d4364e68` with all original history preserved.

Fresh reviewer `program019_genuine_terminal_review` then independently validated the full retained
predecessor chain, historical child/source/active-authority bindings, canonical private terminal,
and byte-exact public projection. New review v2 is `PASS-TERMINAL-FAILURE-VERIFIED`, fingerprint
`d7ad0cc1ae42f85a9ed221f8a6d1cad241df5ed2938d1326bf8f05afd9ec4397`. The withdrawn v1 was not used
as evidence and remains unchanged. Detailed failure cause is unassessed. Do not retry Program 019;
complete the reviewed closeout before offline successor forensics.

Before activation there was no credential,
provider, acquisition, admission, or strategy authority. Existing credential variable names remain
`PROGRAM_006_ALPACA_API_KEY_ID` and `PROGRAM_006_ALPACA_API_SECRET_KEY`; values must stay inside the
fixed scoped runtime and must never enter logs, artifacts, hashes, or command-line arguments.

Program 019 grants no strategy, controlled/protected, purchase, PAPER, broker-write, or live authority.
Raw observations, tokens, private identities, detailed failure evidence, exact missingness and
exclusions remain private. Source qualification does not imply structural dataset admission.
