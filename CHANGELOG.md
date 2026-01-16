# Changelog

All notable changes to TurboVault Engine will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0](https://github.com/ScalefreeCOM/turbovault-engine/compare/v0.3.0...v0.4.0) (2026-01-16)


### Features

* **export:** adding correct link hashkey generation to model export ([#28](https://github.com/ScalefreeCOM/turbovault-engine/issues/28)) ([3fbb324](https://github.com/ScalefreeCOM/turbovault-engine/commit/3fbb32431497be76b4cbedfcf229d50016ad32eb))
* make record_source and load_date required ([#29](https://github.com/ScalefreeCOM/turbovault-engine/issues/29)) ([4dd3ad0](https://github.com/ScalefreeCOM/turbovault-engine/commit/4dd3ad03f87ba01a43e77c01151a32cd94a5bfc0))


### Bug Fixes

* adding missing dependencies for excel import ([#26](https://github.com/ScalefreeCOM/turbovault-engine/issues/26)) ([78cb189](https://github.com/ScalefreeCOM/turbovault-engine/commit/78cb189e24e228b7828f89c3b90985bf03608fe6))


### Dependencies

* **deps:** update rich requirement from &lt;14.0,&gt;=13.0 to >=13.0,<15.0 ([#10](https://github.com/ScalefreeCOM/turbovault-engine/issues/10)) ([29e6081](https://github.com/ScalefreeCOM/turbovault-engine/commit/29e6081641876c4c83e9117d26c195d5b8da869f))

## [0.3.0](https://github.com/ScalefreeCOM/turbovault-engine/compare/v0.2.0...v0.3.0) (2026-01-16)


### Features

* **cli:** add ASCII art banner to startup ([131634f](https://github.com/ScalefreeCOM/turbovault-engine/commit/131634f839d411cc7bf37460c500e180c93e3f25))


### Bug Fixes

* **cli:** suppress ruff whitespace warnings for ASCII banner ([720300a](https://github.com/ScalefreeCOM/turbovault-engine/commit/720300a167b99647057c7e55fafa8ba9a344ff17))

## [0.2.0](https://github.com/ScalefreeCOM/turbovault-engine/compare/v0.1.2...v0.2.0) (2026-01-16)


### Features

* expand user home in dbt_project_dir normalization and add unit tests ([2d2c89c](https://github.com/ScalefreeCOM/turbovault-engine/commit/2d2c89c35030ca463b1007ac746b76976071e06f))

## [0.1.2](https://github.com/ScalefreeCOM/turbovault-engine/compare/v0.1.1...v0.1.2) (2026-01-16)


### Bug Fixes

* Delete temporary files ([70dfd70](https://github.com/ScalefreeCOM/turbovault-engine/commit/70dfd70395c28d1cfd5e47c8a170d5f30c555d53))

### Added

* Updated Link Backend model to reflect dependant child keys & multi-hub references

## [0.1.1](https://github.com/ScalefreeCOM/turbovault-engine/compare/v0.1.0...v0.1.1) (2026-01-16)


### Bug Fixes

* fixing issue with the release pipeline ([#17](https://github.com/ScalefreeCOM/turbovault-engine/issues/17)) ([ddb4c0a](https://github.com/ScalefreeCOM/turbovault-engine/commit/ddb4c0a7c1a499c4dc25ef658c0e737a587ec535))

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
