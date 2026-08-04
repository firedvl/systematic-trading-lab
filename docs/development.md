# Development

Use Python 3.12+, UTC-aware timestamps, `Decimal` for prices, frozen boundary types, transactions for catalog writes, and atomic publication for artifacts. Validate external records before constructing trusted models. Keep modules focused and use the standard library until a measured need justifies a dependency.

Commands and definition of done are in `README.md` and `AGENTS.md`. Tests use deterministic local fixtures and must not need a network or credentials. CI runs the same formatter, linter, type checker, tests, and secret scan as local development.

Ordinary CI also builds one wheel and its deterministic runtime-build manifest. The manual
`Build provenance` workflow runs only from `main`; it requests GitHub attestations for the wheel and
manifest, then uploads both in one retained artifact. This build path does not prove that a later
runtime installed or loaded that wheel. The runtime verifier separately requires a non-editable
archive install, the verified wheel hash in `direct_url.json`, exact wheel-owned files through both
`RECORD` copies, and loaded modules rooted in that distribution. The repository is public, so GitHub
can persist its artifact attestations. Main run `30933665065` produced the latest verified wheel and
manifest for commit `7f4a0a65fd449bf77c71261cd53bedc4727276e6`. If attestation fails, the workflow
retains the unsigned files for diagnosis and still reports failure; never treat that artifact as
verified provenance.
