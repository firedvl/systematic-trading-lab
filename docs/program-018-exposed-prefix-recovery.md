# Program 018 exposed-prefix recovery

Program 018, `multi-hour-sector-etf-research-017`, is
`FAIL-CONSUMED-NO-RETRY`. It was not a replay or retry of Program 017.

Read-only forensics validate Program 017's reviewed child, terminal, completed whole-session prefix,
and one final partial session containing a completed page followed by an intent-only next page.
Program 018 discards that session in full, never reissues either request, and begins at the next
independent scheduled session. Six consumed intents leave at most 22,170 responses under the
unchanged 22,176-intent ceiling.

Proposal v3 inherits Program 017's source, chronology, pagination, missingness, admission,
statistical, privacy, credential, 16 GiB storage, failure-closeout, and no-reissue controls. It adds
Program 017 as a sixth immutable predecessor and uses eight continuously held controls. Execution
validates the full predecessor corpus once before credential presence, performs no predecessor
reconstruction between transports, and reparses completed evidence once for the final projection.

The runtime is frozen at source commit/tree/root
`d53aec017d5ed5233f48e9bd1c32b46f06fd6480` / `f82d8cf53cc99b6db7d355b6b3e2ae4609187616` /
`a4a27e22a06e2e8d7436c0f7dd689f9f71f8f58900d96264dc00d631f4851369`.
Fresh independent correctness and defensive reviews pass finding-free after all raised integrity
findings were fixed prospectively.

## Terminal result

The reviewed child consumed its one use and the runtime sealed `RUNTIME-FAILURE`. The redacted public
terminal records `admission_passed=false`, no dataset lineage, no Program 002 admission, and no
strategy calculation or return. Its SHA-256 is
`90102e72d90391ec5f9e342bf21993daf9613f4fcfaf0218bfd25f041e73d396`; its derived active-authority
fingerprint is `57be4d7a576061773b4507fb4a00a897ff073a56a8ce3c20417a5dc40b304c7b`;
its child-artifact fingerprint is `defa5f68c7b7f8937c1d904b20f1151be5fdacefd7a5fae525dd21234b12a7a6`;
and its runtime source is `8e97e29e951e5e318f8139c1bbaa6a2372711f14`.

The closeout rejects a missing, changed, invalid, or exact terminal before credential or private-root
access. Program 018 cannot replay or retry. Dynamic counts, detailed failure evidence, private
identities, market data, provider tokens, exact missingness, and exclusions remain private. Do not
run Program 018 again. Controlled/protected, purchase, PAPER, broker, and live authority are disabled.
