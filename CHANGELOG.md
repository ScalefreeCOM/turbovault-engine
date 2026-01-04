# Changelog

All notable changes to TurboVault Engine will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
