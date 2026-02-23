# Changelog

All notable changes to TurboVault Engine will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.7.3...turbovault-engine-v0.8.0) (2026-02-23)


### Features

* Introduce a new YAML-based configuration system, workspace management, and initial CLI commands ([418ab77](https://github.com/ScalefreeCOM/turbovault-engine/commit/418ab77b66147981faf5718f7c1b1c69c2fe46fe))
* Introduce workspace and project CLI commands, refactor applicat… ([#83](https://github.com/ScalefreeCOM/turbovault-engine/issues/83)) ([23dd9bb](https://github.com/ScalefreeCOM/turbovault-engine/commit/23dd9bb08039bebdc5f02c3045d35d1352c8d8a2))
* Introduce workspace and project CLI commands, refactor application configuration, and update documentation ([23dd9bb](https://github.com/ScalefreeCOM/turbovault-engine/commit/23dd9bb08039bebdc5f02c3045d35d1352c8d8a2))
* YAML-only configuration system with workspace-based approach ([8e5e74d](https://github.com/ScalefreeCOM/turbovault-engine/commit/8e5e74d13f2c9a165c1047e8a6828cb38d9c2d9d))


### Bug Fixes

* **typo:** dependent child key ([#82](https://github.com/ScalefreeCOM/turbovault-engine/issues/82)) ([0b30270](https://github.com/ScalefreeCOM/turbovault-engine/commit/0b30270c287bb611001907efc1d4d55a49802e4f))

## [0.7.3](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.7.2...turbovault-engine-v0.7.3) (2026-02-11)


### Bug Fixes

* django migrations and admin user creation ([#73](https://github.com/ScalefreeCOM/turbovault-engine/issues/73)) ([df327e6](https://github.com/ScalefreeCOM/turbovault-engine/commit/df327e662cb48d6086a41b666487ebecd7b9baad))
* ensuring admin user is always created when running init ([df327e6](https://github.com/ScalefreeCOM/turbovault-engine/commit/df327e662cb48d6086a41b666487ebecd7b9baad))
* fixing ci job issue ([#69](https://github.com/ScalefreeCOM/turbovault-engine/issues/69)) ([47bd01f](https://github.com/ScalefreeCOM/turbovault-engine/commit/47bd01f2997d27d568da88424b0822be03b82dc5))
* fixing issue with migrations accidentially being reformatted ([df327e6](https://github.com/ScalefreeCOM/turbovault-engine/commit/df327e662cb48d6086a41b666487ebecd7b9baad))

## [0.7.2](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.7.1...turbovault-engine-v0.7.2) (2026-02-02)


### Bug Fixes

* generate referenced hub hashkeys for links ([fafe45f](https://github.com/ScalefreeCOM/turbovault-engine/commit/fafe45f265346866c879987fd028d78b089d62bf))
* multi hub references for links ([b101897](https://github.com/ScalefreeCOM/turbovault-engine/commit/b101897fa5423a6a35f8d2aaa3d5718d2ab20713))
* source_tables for links not empty anymore ([e94e4f5](https://github.com/ScalefreeCOM/turbovault-engine/commit/e94e4f5f3811d32e1963a6e6c4f2ac3ffaf38048))
* sources for ref hubs ([398ca61](https://github.com/ScalefreeCOM/turbovault-engine/commit/398ca61767422d11e2e0d0d139b109e6706c64bb))

## [0.7.1](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.7.0...turbovault-engine-v0.7.1) (2026-01-27)


### Bug Fixes

* linting ([a0fb55a](https://github.com/ScalefreeCOM/turbovault-engine/commit/a0fb55a5de4f978aee75dd925279641c95f7d00d))
* typo in Docker pull command in README ([#42](https://github.com/ScalefreeCOM/turbovault-engine/issues/42)) ([5dec902](https://github.com/ScalefreeCOM/turbovault-engine/commit/5dec902648dad67e3a28ac058f2c594a0686abb4))

## [0.7.0](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.6.0...turbovault-engine-v0.7.0) (2026-01-23)


### ⚠ BREAKING CHANGES

* The --json-only and --export-json flags have been replaced with --type flag.

### Features

* adding new configuration system for dynamic database settings ([#38](https://github.com/ScalefreeCOM/turbovault-engine/issues/38)) ([70a5287](https://github.com/ScalefreeCOM/turbovault-engine/commit/70a528754fc0e63fd2d103bd5c704c29c0fc98c5))
* consolidate commands and add debug mode  ([#39](https://github.com/ScalefreeCOM/turbovault-engine/issues/39)) ([d52ca68](https://github.com/ScalefreeCOM/turbovault-engine/commit/d52ca684a738531c37094f0f091341eaa3901eab))

## [0.6.0](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.5.1...turbovault-engine-v0.6.0) (2026-01-20)


### Features

* adding new configuration system for dynamic database settings ([#36](https://github.com/ScalefreeCOM/turbovault-engine/issues/36)) ([124dc9b](https://github.com/ScalefreeCOM/turbovault-engine/commit/124dc9b0f607d47a16032f63be61e3032569816f))

## [0.5.1](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.5.0...turbovault-engine-v0.5.1) (2026-01-20)


### Bug Fixes

* **model_generation:** aligned sql templates with best practices ([ded720c](https://github.com/ScalefreeCOM/turbovault-engine/commit/ded720c85a25a73910aa84d06eea897312c0c991))
* **model_generation:** source generation to include name ([aac42ce](https://github.com/ScalefreeCOM/turbovault-engine/commit/aac42ce4b14335f43bc1eeae49bb34c4bc392d0d))
* **model_generation:** stage generation proper source syntax ([5c7121f](https://github.com/ScalefreeCOM/turbovault-engine/commit/5c7121f6095034ae3f5665f1f62e3b1722a6c36d))


### CI/CD

* bump actions/download-artifact from 6 to 7 ([73c7bc7](https://github.com/ScalefreeCOM/turbovault-engine/commit/73c7bc78e308249757d1d634d991c58b9561a411))
* bump docker/build-push-action from 5 to 6 ([6259a83](https://github.com/ScalefreeCOM/turbovault-engine/commit/6259a83cb679f18e9fa3ad00e38394579db4833a))

## [0.5.0](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.4.0...turbovault-engine-v0.5.0) (2026-01-16)


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
* Adjusted Link Data model and update admin interface ([134cdd4](https://github.com/ScalefreeCOM/turbovault-engine/commit/134cdd43aa8b012479803022742954d61653e08d))
* **cli:** add ASCII art banner to startup ([131634f](https://github.com/ScalefreeCOM/turbovault-engine/commit/131634f839d411cc7bf37460c500e180c93e3f25))
* customizing admin area ([db022f0](https://github.com/ScalefreeCOM/turbovault-engine/commit/db022f04e4cc4c4278785a54f37d096d8b9bafb4))
* dbt project generation improvements and cli integration ([ec7c597](https://github.com/ScalefreeCOM/turbovault-engine/commit/ec7c597802855fc7335a28325438ae02a6d49fa4))
* expand user home in dbt_project_dir normalization and add unit tests ([2d2c89c](https://github.com/ScalefreeCOM/turbovault-engine/commit/2d2c89c35030ca463b1007ac746b76976071e06f))
* **export:** adding correct link hashkey generation to model export ([#28](https://github.com/ScalefreeCOM/turbovault-engine/issues/28)) ([3fbb324](https://github.com/ScalefreeCOM/turbovault-engine/commit/3fbb32431497be76b4cbedfcf229d50016ad32eb))
* Implement export service with new builder, models, and example configurations. ([d682aee](https://github.com/ScalefreeCOM/turbovault-engine/commit/d682aee3d766ae0c9e7808101635c9173a03d576))
* Implement snapshot control, export service models, CLI utilities, and add various configuration ([5e8144e](https://github.com/ScalefreeCOM/turbovault-engine/commit/5e8144ec8f60a6fbb6f37e69bccbd99a64b35cdc))
* implementing basic templating engine and foundation for dbt project generation ([9159ec7](https://github.com/ScalefreeCOM/turbovault-engine/commit/9159ec75b9c904ea40fbdb38e19ee416c4be31a0))
* implementing dbt project generation logic ([ecc9b5a](https://github.com/ScalefreeCOM/turbovault-engine/commit/ecc9b5a2ad55f41572a03bc8dd40f7abbc649ce5))
* Initialize Django project with core engine application structure and foundational documentation ([bd85674](https://github.com/ScalefreeCOM/turbovault-engine/commit/bd85674968fc8ada96368c5e2857ba420d8e6ae1))
* **link-remodeling:** Fix Excel import for links ([edfdb46](https://github.com/ScalefreeCOM/turbovault-engine/commit/edfdb46908acf793c7e4a99b950692b64f31df13))
* make record_source and load_date required ([#29](https://github.com/ScalefreeCOM/turbovault-engine/issues/29)) ([4dd3ad0](https://github.com/ScalefreeCOM/turbovault-engine/commit/4dd3ad03f87ba01a43e77c01151a32cd94a5bfc0))


### Bug Fixes

* adding missing dependencies for excel import ([#26](https://github.com/ScalefreeCOM/turbovault-engine/issues/26)) ([78cb189](https://github.com/ScalefreeCOM/turbovault-engine/commit/78cb189e24e228b7828f89c3b90985bf03608fe6))
* **cli:** suppress ruff whitespace warnings for ASCII banner ([720300a](https://github.com/ScalefreeCOM/turbovault-engine/commit/720300a167b99647057c7e55fafa8ba9a344ff17))
* Delete temporary files ([70dfd70](https://github.com/ScalefreeCOM/turbovault-engine/commit/70dfd70395c28d1cfd5e47c8a170d5f30c555d53))
* fixing issue with releases ([#30](https://github.com/ScalefreeCOM/turbovault-engine/issues/30)) ([dd811be](https://github.com/ScalefreeCOM/turbovault-engine/commit/dd811be564bc2bb736a2b6e0e6502ee9d588b050))
* fixing issue with the release pipeline ([#17](https://github.com/ScalefreeCOM/turbovault-engine/issues/17)) ([ddb4c0a](https://github.com/ScalefreeCOM/turbovault-engine/commit/ddb4c0a7c1a499c4dc25ef658c0e737a587ec535))
* resolve all remaining Ruff linting errors ([9379d32](https://github.com/ScalefreeCOM/turbovault-engine/commit/9379d323fe43d3feb1c92d4381fbca3cf0e00e0c))
* resolve Ruff linting errors (191 to 24) ([2f9dcf9](https://github.com/ScalefreeCOM/turbovault-engine/commit/2f9dcf911ca5f73659dcc3e2b60ac09fab48ad45))


### Documentation

* update v0.1.0 changelog to focus on application features ([d5fe205](https://github.com/ScalefreeCOM/turbovault-engine/commit/d5fe20583deab823c236607741cdd7ad0caa107c))


### Code Style

* format code with Black ([d1634cd](https://github.com/ScalefreeCOM/turbovault-engine/commit/d1634cda27127437d3328f6bae5751b540f87760))
* reformat 4 files with Black after Ruff changes ([198163b](https://github.com/ScalefreeCOM/turbovault-engine/commit/198163bfb0499f0c509e7e24964fdee0abe5d40a))


### Refactoring

* refactoring docs ([8d00a86](https://github.com/ScalefreeCOM/turbovault-engine/commit/8d00a8692f1785ea9c877de02abf6699326865a3))
* remove redundant GitHub release job ([#23](https://github.com/ScalefreeCOM/turbovault-engine/issues/23)) ([bc858ad](https://github.com/ScalefreeCOM/turbovault-engine/commit/bc858ad8077c46cf1cac85b26c4eeb0fbbc7b869))


### CI/CD

* add GitHub Actions workflows and development infrastructure ([8706bfa](https://github.com/ScalefreeCOM/turbovault-engine/commit/8706bfa13f4c5daa9575797e7f09ce09a0edf400))
* bump actions/checkout from 4 to 6 ([#8](https://github.com/ScalefreeCOM/turbovault-engine/issues/8)) ([66e3c61](https://github.com/ScalefreeCOM/turbovault-engine/commit/66e3c614485edda694310bdd908e745711412550))
* bump actions/setup-python from 5 to 6 ([#9](https://github.com/ScalefreeCOM/turbovault-engine/issues/9)) ([d43c93a](https://github.com/ScalefreeCOM/turbovault-engine/commit/d43c93a354ee0e65d323a90456279e7ed3d304ed))
* bump actions/upload-artifact from 4 to 6 ([#7](https://github.com/ScalefreeCOM/turbovault-engine/issues/7)) ([dd2d5c6](https://github.com/ScalefreeCOM/turbovault-engine/commit/dd2d5c6ea580c44098bed4c057504383aa81e848))


### Miscellaneous

* **main:** release 0.1.0 ([90d2fc8](https://github.com/ScalefreeCOM/turbovault-engine/commit/90d2fc8504a5feb8c4a07011ee3e1d63e884c267))
* **main:** release 0.1.0 ([90d2fc8](https://github.com/ScalefreeCOM/turbovault-engine/commit/90d2fc8504a5feb8c4a07011ee3e1d63e884c267))
* **main:** release 0.1.0 ([b8fcf31](https://github.com/ScalefreeCOM/turbovault-engine/commit/b8fcf31f32cb53c9c4428fbe409409da6821b530))
* **main:** release 0.1.1 ([#18](https://github.com/ScalefreeCOM/turbovault-engine/issues/18)) ([ef0003d](https://github.com/ScalefreeCOM/turbovault-engine/commit/ef0003d863273e986229e7c6a47590dc87773360))
* **main:** release 0.1.2 ([c4559fc](https://github.com/ScalefreeCOM/turbovault-engine/commit/c4559fc8fb96964938264fd1fa8e4671300211f1))
* **main:** release 0.2.0 ([#22](https://github.com/ScalefreeCOM/turbovault-engine/issues/22)) ([cc7d980](https://github.com/ScalefreeCOM/turbovault-engine/commit/cc7d9804ad14d1be070012507a511e6545914233))
* **main:** release 0.3.0 ([#25](https://github.com/ScalefreeCOM/turbovault-engine/issues/25)) ([5acfe69](https://github.com/ScalefreeCOM/turbovault-engine/commit/5acfe69982a197506cad2e0a5406c8dad9e4cc5e))
* **main:** release 0.4.0 ([#27](https://github.com/ScalefreeCOM/turbovault-engine/issues/27)) ([d806efe](https://github.com/ScalefreeCOM/turbovault-engine/commit/d806efe41d95ad0aada46023b193b88987825d48))
* release v0.1.0 ([c4f7c44](https://github.com/ScalefreeCOM/turbovault-engine/commit/c4f7c447366abc2b5c19477bd44d9b69409df2fb))

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

* Updated Link Backend model to reflect dependent child keys & multi-hub references

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
