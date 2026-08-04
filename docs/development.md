# Development

Use Python 3.12+, UTC-aware timestamps, `Decimal` for prices, frozen boundary types, transactions for catalog writes, and atomic publication for artifacts. Validate external records before constructing trusted models. Keep modules focused and use the standard library until a measured need justifies a dependency.

Commands and definition of done are in `README.md` and `AGENTS.md`. Tests use deterministic local fixtures and must not need a network or credentials. CI runs the same formatter, linter, type checker, tests, and secret scan as local development.

Ordinary CI also builds one wheel and its deterministic runtime-build manifest. The manual
`Build provenance` workflow runs only from `main`; it requests GitHub attestations for the wheel and
manifest, then uploads both in one retained artifact. This build path does not prove that a later
runtime installed or loaded that wheel.
