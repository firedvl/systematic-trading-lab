## What changed

Describe the change and why it is needed.

## Boundaries touched

Note whether this changes research behavior, data provenance, qualification/holdout logic, risk controls, paper execution, runtime provenance, migrations, or operational behavior.

## Verification

- [ ] Relevant focused tests pass.
- [ ] `ruff format --check` and `ruff check` pass.
- [ ] `mypy` passes for the affected code.
- [ ] Relevant `pytest` coverage passes.
- [ ] Secret checks pass.
- [ ] Documentation matches behavior.

List any additional verification performed.

## Safety and compatibility

Describe failure-path coverage, migration or compatibility impact, and any new operational assumptions.

- [ ] No credentials, private account data, generated private datasets, or raw broker responses are included.
- [ ] Protected controls are unchanged or explicitly reviewed.
- [ ] Live trading remains disabled.

State explicitly when a change adds no broker-write or live-execution authority.