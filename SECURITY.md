# Security policy

Report vulnerabilities privately through the repository's GitHub security advisory page. Do not open a public issue containing credentials, account data, broker responses, or an exploitable detail.

Live execution is prohibited. Secrets enter only through environment variables, must not be logged, and must never appear in source, docs, prompts, fixtures, snapshots, or artifacts. Missing or ambiguous mode, endpoint, broker state, portfolio state, or risk configuration disables broker writes. See `docs/threat-model.md` and `docs/risk-policy.md`.

The only future write endpoint permitted in M4 is `https://paper-api.alpaca.markets`. Endpoint
redirects, alternate hosts, and production trading hosts must fail closed.
