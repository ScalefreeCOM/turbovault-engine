# Changelog

All notable changes to TurboVault Engine will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
### Changed
### Fixed

## [0.1.0] - 2026-01-04

### 🎉 Initial Release

TurboVault Engine is a CLI-first, Django-based engine for Data Vault modeling and dbt project generation.

### Added

**Core Functionality:**
- CLI commands: `init`, `generate`, `run`, `serve`, `reset`
- Django-based domain model for Data Vault entities
- dbt project generation with datavault4dbt macros
- Template customization via Django Admin
- Pre-generation validation
- Export to JSON and ZIP formats

**Data Vault Support:**
- Hubs (standard and reference)
- Links (standard and non-historized)
- Satellites
- Point-in-Time (PIT) tables
- Reference Tables
- Snapshot control configuration
- Prejoin definitions

**Developer Infrastructure:**
- Docker support with multi-stage Dockerfile
- docker-compose.yml for local development
- Automated release workflow (Release Please)
- Docker image publishing to GitHub Container Registry (GHCR)
- CI/CD pipeline with GitHub Actions
- Pre-commit hooks for code quality
- Dependabot for automated dependency updates
- Comprehensive documentation and contribution guidelines

[Unreleased]: https://github.com/ScalefreeCOM/turbovault-engine/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ScalefreeCOM/turbovault-engine/releases/tag/v0.1.0
