# Security policy

## Reporting a vulnerability

Please report security vulnerabilities privately through this repository's GitHub Security Advisory interface. Do not open a public issue containing credentials, account data, sensitive broker responses, or details that would make an exploit easier to reproduce before a fix is available.

Include enough information to understand the affected boundary, expected behavior, observed behavior, and a minimal reproduction when safe to do so. Do not include real API keys, private account identifiers, or unnecessary broker/account data.

## Security-sensitive boundaries

The repository treats the following as protected controls:

- broker endpoint and transport restrictions;
- paper-write authorization and activation;
- runtime identity and build provenance;
- risk limits and capacity reservation;
- emergency-disable state;
- reconciliation and unknown-outcome recovery;
- append-only execution evidence;
- qualification and protected holdout access;
- credential handling and secret redaction.

Changes to these areas should fail closed when required evidence is missing, stale, ambiguous, inconsistent, or unverifiable.

## Execution scope

Real-money/live execution is prohibited. The only supported broker mutation scope is the explicitly authorized Alpaca paper environment. Production trading hosts, redirects, alternate mutation origins, or implicit endpoint substitution must not become valid through configuration fallback.

Paper mutation authority is not granted by credentials or environment mode alone. The execution path also requires the repository's authorization, activation, runtime identity, risk, reconciliation, and transaction-bound controls.

Rapid Research has no broker mutation path and cannot create paper or live authority. Report any path from a Rapid module or candidate export into protected holdout, risk, order, paper, execution, reconciliation, broker, or V3 state as a security boundary violation.

## Secrets and sensitive data

Secrets enter through environment variables or other explicitly documented local credential mechanisms and must never be committed to source control.

Do not place secrets or private broker/account data in:

- source code or documentation;
- fixtures or snapshots;
- prompts or generated artifacts intended for commit;
- logs or test output;
- GitHub issues or pull requests.

The repository includes a secret scan as one quality gate, but contributors must still inspect their own diffs before pushing.

## Threat model

See [`docs/threat-model.md`](docs/threat-model.md) for the detailed threat model, [`docs/risk-policy.md`](docs/risk-policy.md) for risk-control semantics, and [`docs/paper-execution-plan.md`](docs/paper-execution-plan.md), [`docs/paper-write-readiness.md`](docs/paper-write-readiness.md), and [`docs/operations.md`](docs/operations.md) for operational paper-execution boundaries.
