# Open-source project guidance

Systematic Trading Lab is developed in public as research and software infrastructure. External contributions, issue reports, documentation improvements, test cases, and review are welcome.

The repository deliberately keeps research claims, execution authority, and operational evidence separate. Public collaboration must preserve that distinction: a successful backtest is not a production claim, qualification is not execution authorization, and paper operation is not live-trading approval.

Rapid Research is the default public contribution path for strategies and historical evaluation. It needs no campaign registration or broker credential. Its artifacts are exploratory and cannot grant authority.

## Good first contribution areas

Useful contributions that do not require broker credentials include:

- fixture-backed regression tests;
- daily strategies and public registry parameter validation;
- Rapid Research metrics, walk-forward, stress, and data-usability fixes;
- documentation and examples;
- deterministic reporting and inspection tools;
- backtest correctness and reproducibility improvements;
- data-validation and provenance checks;
- developer tooling and portability fixes;
- static analysis, typing, and test infrastructure.

Changes to paper execution, risk controls, runtime provenance, holdout access, or recovery paths are welcome but receive stricter review because they affect protected controls.

## Project maturity

The project is under active development. Public interfaces, evidence schemas, and operating procedures may change while the architecture is still being refined. Significant compatibility changes should be documented in the pull request and durable project documentation.

## Maintainer workflow

The repository uses focused pull requests and keeps durable architecture/policy decisions in version control. Review should favor explicit evidence, narrow authority, deterministic behavior, and failure paths over convenience shortcuts.

See `CONTRIBUTING.md`, `SECURITY.md`, `CURRENT_STATE.md`, and `ROADMAP.md` for the current contribution, security, and development context.
