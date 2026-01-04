# Changelog

All notable changes to TurboVault Engine will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0 (2026-01-04)


### ⚠ BREAKING CHANGES

* Release process changed from manual tags to automated Release Please workflow

### Features

* add automated developer setup scripts ([6f71d21](https://github.com/ScalefreeCOM/turbovault-engine/commit/6f71d2108d12843428bf7b258b3927ac58d86271))
* add Phase 2 Enhanced CI features ([a2d8ccb](https://github.com/ScalefreeCOM/turbovault-engine/commit/a2d8ccbaa4016b206755490e0e8a6d7f3eba1547))
* add Phase 3 Docker & Release automation ([1f721e0](https://github.com/ScalefreeCOM/turbovault-engine/commit/1f721e003c5487cdbcb0a030eecc0cefdd5255c3))
* adding automated releases ([#13](https://github.com/ScalefreeCOM/turbovault-engine/issues/13)) ([b815a73](https://github.com/ScalefreeCOM/turbovault-engine/commit/b815a73c0b039895f2d635a4c4151cb45d78f985))
* adding model structure and basic export logic ([#2](https://github.com/ScalefreeCOM/turbovault-engine/issues/2)) ([bb359a3](https://github.com/ScalefreeCOM/turbovault-engine/commit/bb359a3f8d71cf735ccf5331aaf200feefd7140e))
* adding more config values, improving CLI, adding final models ([997ae88](https://github.com/ScalefreeCOM/turbovault-engine/commit/997ae88ead845dc3b8c9a75311ba421dceb13ac6))
* adding prejoin model ([74e2591](https://github.com/ScalefreeCOM/turbovault-engine/commit/74e2591bbe36e3a51e3d34e4c5e86eea8526bdd3))
* adding validation and tests ([77dd27c](https://github.com/ScalefreeCOM/turbovault-engine/commit/77dd27c51eb9cdc10d9eda92830af20925da59e6))
* customizing admin area ([db022f0](https://github.com/ScalefreeCOM/turbovault-engine/commit/db022f04e4cc4c4278785a54f37d096d8b9bafb4))
* dbt project generation improvements and cli integration ([ec7c597](https://github.com/ScalefreeCOM/turbovault-engine/commit/ec7c597802855fc7335a28325438ae02a6d49fa4))
* Implement export service with new builder, models, and example configurations. ([d682aee](https://github.com/ScalefreeCOM/turbovault-engine/commit/d682aee3d766ae0c9e7808101635c9173a03d576))
* Implement snapshot control, export service models, CLI utilities, and add various configuration ([5e8144e](https://github.com/ScalefreeCOM/turbovault-engine/commit/5e8144ec8f60a6fbb6f37e69bccbd99a64b35cdc))
* implementing basic templating engine and foundation for dbt project generation ([9159ec7](https://github.com/ScalefreeCOM/turbovault-engine/commit/9159ec75b9c904ea40fbdb38e19ee416c4be31a0))
* implementing dbt project generation logic ([ecc9b5a](https://github.com/ScalefreeCOM/turbovault-engine/commit/ecc9b5a2ad55f41572a03bc8dd40f7abbc649ce5))
* Initialize Django project with core engine application structure and foundational documentation ([bd85674](https://github.com/ScalefreeCOM/turbovault-engine/commit/bd85674968fc8ada96368c5e2857ba420d8e6ae1))


### Bug Fixes

* resolve all remaining Ruff linting errors ([9379d32](https://github.com/ScalefreeCOM/turbovault-engine/commit/9379d323fe43d3feb1c92d4381fbca3cf0e00e0c))
* resolve Ruff linting errors (191 to 24) ([2f9dcf9](https://github.com/ScalefreeCOM/turbovault-engine/commit/2f9dcf911ca5f73659dcc3e2b60ac09fab48ad45))

## [Unreleased]

### Added
### Changed
### Fixed

## [0.1.0] - 2026-01-04

### Added
- Docker support with multi-stage Dockerfile
- docker-compose.yml for local development
- Automated release workflow for PyPI and GitHub releases
- Docker image publishing to GitHub Container Registry (GHCR)
- RELEASING.md guide for release process
- RELEASE_CHECKLIST.md for quick reference
- Dependabot configuration for automated dependency updates
- Documentation issue template
- GitHub Actions CI/CD pipeline
- Pre-commit hooks for code quality
- Contributing guidelines
- Issue and PR templates
- Developer setup scripts (setup-dev.ps1, setup-dev.sh)

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.1.0] - 2026-01-04

### Added
- Initial release of TurboVault Engine
- CLI commands: `init`, `generate`, `run`, `serve`, `reset`
- Django-based domain model for Data Vault entities
- dbt project generation with datavault4dbt macros
- Template customization via Django Admin
- Pre-generation validation
- Support for Hubs, Links, Satellites, PITs, Reference Tables
- Snapshot control configuration
- Prejoin definitions
- Comprehensive documentation

[Unreleased]: https://github.com/ScalefreeCOM/turbovault-engine/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ScalefreeCOM/turbovault-engine/releases/tag/v0.1.0
