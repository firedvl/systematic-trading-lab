# Program 019 exposed-prefix recovery

Program 019, `multi-hour-sector-etf-research-018`, is a prospective successor to terminally failed
Program 018. Proposal v2 and its finding-free independent correctness and defensive reviews merged
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

Runtime implementation and fresh independent reviews must finish before a separately scoped standing
child is created, reviewed, merged, and internally activated. Until then there is no credential,
provider, acquisition, admission, or strategy authority. Existing credential variable names remain
`PROGRAM_006_ALPACA_API_KEY_ID` and `PROGRAM_006_ALPACA_API_SECRET_KEY`; values must stay inside the
fixed scoped runtime and must never enter logs, artifacts, hashes, or command-line arguments.

Program 019 grants no strategy, controlled/protected, purchase, PAPER, broker-write, or live authority.
Raw observations, tokens, private identities, detailed failure evidence, exact missingness and
exclusions remain private. Source qualification does not imply structural dataset admission.
