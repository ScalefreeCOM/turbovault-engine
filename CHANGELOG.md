# Changelog

All notable changes to TurboVault Engine will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.11.0](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.10.3...turbovault-engine-v0.11.0) (2026-03-19)


### ⚠ BREAKING CHANGES

* The --json-only and --export-json flags have been replaced with --type flag.
* Release process changed from manual tags to automated Release Please workflow

### Features

* add automated developer setup scripts ([44c406b](https://github.com/ScalefreeCOM/turbovault-engine/commit/44c406b0b30958fa7517dde1a013a3aa32e2b47b))
* add Phase 2 Enhanced CI features ([cad7655](https://github.com/ScalefreeCOM/turbovault-engine/commit/cad7655fc76de48e5295c25ae196743312a4de0e))
* add Phase 3 Docker & Release automation ([e7088bf](https://github.com/ScalefreeCOM/turbovault-engine/commit/e7088bf7e0cfe78203f7600569f032a79a77bb0d))
* adding automated releases ([#13](https://github.com/ScalefreeCOM/turbovault-engine/issues/13)) ([3defe03](https://github.com/ScalefreeCOM/turbovault-engine/commit/3defe032615327ab75de2e0430d497e92241d33b))
* adding model structure and basic export logic ([#2](https://github.com/ScalefreeCOM/turbovault-engine/issues/2)) ([5eaafc0](https://github.com/ScalefreeCOM/turbovault-engine/commit/5eaafc0692b4abcc03af6ccd8dbcf4c2c9951431))
* adding more config values, improving CLI, adding final models ([1babcd0](https://github.com/ScalefreeCOM/turbovault-engine/commit/1babcd0bca27ca4f9d72a5a805cd74784ea2bb63))
* adding new configuration system for dynamic database settings ([#36](https://github.com/ScalefreeCOM/turbovault-engine/issues/36)) ([3f71230](https://github.com/ScalefreeCOM/turbovault-engine/commit/3f71230a52f03a45fa5a043a1fbc4e33ce9d517d))
* adding new configuration system for dynamic database settings ([#38](https://github.com/ScalefreeCOM/turbovault-engine/issues/38)) ([1c36c97](https://github.com/ScalefreeCOM/turbovault-engine/commit/1c36c97937eb1fec1fcb84e18879d752f89fe2fb))
* adding package building and preparing pypi publishing ([#112](https://github.com/ScalefreeCOM/turbovault-engine/issues/112)) ([e72d325](https://github.com/ScalefreeCOM/turbovault-engine/commit/e72d32519e489de413e98c55bd23dbd11acd919d))
* adding prejoin model ([124400c](https://github.com/ScalefreeCOM/turbovault-engine/commit/124400c2de895f7a2b1a04769e61709dba770ee5))
* adding validation and tests ([af2df8c](https://github.com/ScalefreeCOM/turbovault-engine/commit/af2df8c9657e7d36529e77593e2bdca20a8cd1a9))
* adding version cli flag ([#95](https://github.com/ScalefreeCOM/turbovault-engine/issues/95)) ([c16bf88](https://github.com/ScalefreeCOM/turbovault-engine/commit/c16bf882c73ab43a138ffddde5dd7efee6d04225))
* Adjusted Link Data model and update admin interface ([726922a](https://github.com/ScalefreeCOM/turbovault-engine/commit/726922a8826f9bf27ceb04d892e08a7cb6eeb366))
* **ci:** logo and colors updated ([#86](https://github.com/ScalefreeCOM/turbovault-engine/issues/86)) ([89118d4](https://github.com/ScalefreeCOM/turbovault-engine/commit/89118d4eca4c8e1072d243898d59aa31c3d157ba))
* **cli:** add ASCII art banner to startup ([7f880b4](https://github.com/ScalefreeCOM/turbovault-engine/commit/7f880b446f39f1f13e7eef3ecd9dba5d15981012))
* consolidate commands and add debug mode  ([#39](https://github.com/ScalefreeCOM/turbovault-engine/issues/39)) ([0572f56](https://github.com/ScalefreeCOM/turbovault-engine/commit/0572f56a649fb2ff626eeaf79ac566d9916d13a6))
* customizing admin area ([6997ffc](https://github.com/ScalefreeCOM/turbovault-engine/commit/6997ffc4d217a53812019fc67c34ddfaffa828ae))
* dbt project generation improvements and cli integration ([cd8a50e](https://github.com/ScalefreeCOM/turbovault-engine/commit/cd8a50e8e72f4f4f4a00050bd7a47fed688fd495))
* expand user home in dbt_project_dir normalization and add unit tests ([e7aba95](https://github.com/ScalefreeCOM/turbovault-engine/commit/e7aba959fd456ca29436c90b579885db2aa4e521))
* **export:** adding correct link hashkey generation to model export ([#28](https://github.com/ScalefreeCOM/turbovault-engine/issues/28)) ([813a00d](https://github.com/ScalefreeCOM/turbovault-engine/commit/813a00d98549e5783d6273d2325c4ec4070c8987))
* Implement anonymous usage statistics for the CLI with an opt-ou… ([#96](https://github.com/ScalefreeCOM/turbovault-engine/issues/96)) ([d2d9fb1](https://github.com/ScalefreeCOM/turbovault-engine/commit/d2d9fb1944a694736314b9a774cbafeb07f1d583))
* Implement anonymous usage statistics for the CLI with an opt-out option ([d2d9fb1](https://github.com/ScalefreeCOM/turbovault-engine/commit/d2d9fb1944a694736314b9a774cbafeb07f1d583))
* Implement export service with new builder, models, and example configurations. ([bbafe55](https://github.com/ScalefreeCOM/turbovault-engine/commit/bbafe5546cd024655376f35f69a58921d2d524d2))
* Implement snapshot control, export service models, CLI utilities, and add various configuration ([387e35c](https://github.com/ScalefreeCOM/turbovault-engine/commit/387e35c519b198838e4f58afc8487d816741eb51))
* implementing basic templating engine and foundation for dbt project generation ([5d0fef2](https://github.com/ScalefreeCOM/turbovault-engine/commit/5d0fef2452fafcffa4b6a6d13c6343e687367ee7))
* implementing dbt project generation logic ([3b481b3](https://github.com/ScalefreeCOM/turbovault-engine/commit/3b481b37b7bee30fceff076af334cc1836a30101))
* Initialize Django project with core engine application structure and foundational documentation ([7c9e6b2](https://github.com/ScalefreeCOM/turbovault-engine/commit/7c9e6b224581aebcd8264dba89eedd03191d27bf))
* Introduce a new YAML-based configuration system, workspace management, and initial CLI commands ([0ba55d2](https://github.com/ScalefreeCOM/turbovault-engine/commit/0ba55d2b7bd0ed868e94dbb948990b7a3c8c4ba7))
* Introduce workspace and project CLI commands, refactor applicat… ([#83](https://github.com/ScalefreeCOM/turbovault-engine/issues/83)) ([63c90f7](https://github.com/ScalefreeCOM/turbovault-engine/commit/63c90f72188d4535a251492566936340428de6c3))
* Introduce workspace and project CLI commands, refactor application configuration, and update documentation ([63c90f7](https://github.com/ScalefreeCOM/turbovault-engine/commit/63c90f72188d4535a251492566936340428de6c3))
* **link-remodeling:** Fix Excel import for links ([ca86717](https://github.com/ScalefreeCOM/turbovault-engine/commit/ca86717b3a634dacc2af7887cd72f9c6ffb5e794))
* make record_source and load_date required ([#29](https://github.com/ScalefreeCOM/turbovault-engine/issues/29)) ([ca51bb0](https://github.com/ScalefreeCOM/turbovault-engine/commit/ca51bb0e4335adbc83854e0103662bcea34bacd3))
* **sources:** one yml per source ([#97](https://github.com/ScalefreeCOM/turbovault-engine/issues/97)) ([c34864e](https://github.com/ScalefreeCOM/turbovault-engine/commit/c34864e0511a8a3036f46f3d0f55c11826aee1da))
* YAML-only configuration system with workspace-based approach ([eb8cec0](https://github.com/ScalefreeCOM/turbovault-engine/commit/eb8cec0e920182d9437fa420fb0853a3ca131ae8))


### Bug Fixes

* adding missing dependencies for excel import ([#26](https://github.com/ScalefreeCOM/turbovault-engine/issues/26)) ([ceb9661](https://github.com/ScalefreeCOM/turbovault-engine/commit/ceb966142472c4e14433928444f80ca1d1cfc64e))
* **cli:** suppress ruff whitespace warnings for ASCII banner ([6b39c23](https://github.com/ScalefreeCOM/turbovault-engine/commit/6b39c23a499f662fbdd2f696ae7cf24a74f0eb61))
* Delete temporary files ([7ff795e](https://github.com/ScalefreeCOM/turbovault-engine/commit/7ff795e158f89de06e350057ce98e0a38712e85c))
* django migrations and admin user creation ([#73](https://github.com/ScalefreeCOM/turbovault-engine/issues/73)) ([151598f](https://github.com/ScalefreeCOM/turbovault-engine/commit/151598fa227c2f4ad27454ddc2f6498d735df26c))
* ensuring admin user is always created when running init ([151598f](https://github.com/ScalefreeCOM/turbovault-engine/commit/151598fa227c2f4ad27454ddc2f6498d735df26c))
* fixing ci job issue ([#69](https://github.com/ScalefreeCOM/turbovault-engine/issues/69)) ([413c959](https://github.com/ScalefreeCOM/turbovault-engine/commit/413c9593f9e2227b8e72c0a171df6b3957973e79))
* fixing issue with migrations accidentially being reformatted ([151598f](https://github.com/ScalefreeCOM/turbovault-engine/commit/151598fa227c2f4ad27454ddc2f6498d735df26c))
* fixing issue with releases ([#30](https://github.com/ScalefreeCOM/turbovault-engine/issues/30)) ([8c51e3f](https://github.com/ScalefreeCOM/turbovault-engine/commit/8c51e3f1f3bc8d19ebc7bd7d2be65f19d6e4e95d))
* fixing issue with the release pipeline ([#17](https://github.com/ScalefreeCOM/turbovault-engine/issues/17)) ([a801b2b](https://github.com/ScalefreeCOM/turbovault-engine/commit/a801b2bec382c2f7ab273353aad31bc799239d67))
* generate referenced hub hashkeys for links ([f382afa](https://github.com/ScalefreeCOM/turbovault-engine/commit/f382afacdfb44911f1d9310899fd709b56b8e2ff))
* linting ([206301e](https://github.com/ScalefreeCOM/turbovault-engine/commit/206301e710ac9c8be6219a489b8d46006abfda0e))
* **model_generation:** aligned sql templates with best practices ([a4251d7](https://github.com/ScalefreeCOM/turbovault-engine/commit/a4251d7ae59df422739407d4ccf6a465808443c5))
* **model_generation:** source generation to include name ([3f5d70f](https://github.com/ScalefreeCOM/turbovault-engine/commit/3f5d70f1f2b057e5adbdb46ed1efa5f0d3a375e9))
* **model_generation:** stage generation proper source syntax ([ce46ca8](https://github.com/ScalefreeCOM/turbovault-engine/commit/ce46ca82f231eb911dcf11b845bf72da668ed7de))
* multi hub references for links ([0962fe0](https://github.com/ScalefreeCOM/turbovault-engine/commit/0962fe0119c01f6bcee5e94ec5d8b13bba301c11))
* **prejoin:** use new syntax and allow col renamings ([630cb8c](https://github.com/ScalefreeCOM/turbovault-engine/commit/630cb8cecccf4270c308d3d77bff06e02fcdd548))
* resolve all remaining Ruff linting errors ([6300073](https://github.com/ScalefreeCOM/turbovault-engine/commit/63000732c192295dd860cd5d64fb8dff1a9bfbda))
* resolve Ruff linting errors (191 to 24) ([06369da](https://github.com/ScalefreeCOM/turbovault-engine/commit/06369dad57b2067cbc05ede3f35c1426cb789781))
* Schema Configs are now properly used in dbt_project.yml ([#100](https://github.com/ScalefreeCOM/turbovault-engine/issues/100)) ([9abcfe0](https://github.com/ScalefreeCOM/turbovault-engine/commit/9abcfe0ca9c012416e9a7678004bc65efa56305e))
* **schema:** bdv_schema added and all propagated to dbt_project.yml ([9abcfe0](https://github.com/ScalefreeCOM/turbovault-engine/commit/9abcfe0ca9c012416e9a7678004bc65efa56305e))
* source_tables for links not empty anymore ([1ba0e15](https://github.com/ScalefreeCOM/turbovault-engine/commit/1ba0e155796d926ec8a01dbcd3a0cd2d04ad688f))
* sources for ref hubs ([3316ced](https://github.com/ScalefreeCOM/turbovault-engine/commit/3316ced370bd1c30bb68d76b524d3cbe99381807))
* typo in Docker pull command in README ([#42](https://github.com/ScalefreeCOM/turbovault-engine/issues/42)) ([f17772f](https://github.com/ScalefreeCOM/turbovault-engine/commit/f17772f7d7934eef8353746e66ebd9becb81417b))
* **typo:** dependent child key ([#82](https://github.com/ScalefreeCOM/turbovault-engine/issues/82)) ([5e6828f](https://github.com/ScalefreeCOM/turbovault-engine/commit/5e6828f6938c1cf530544a9fa9fb44dee98f2bc1))


### Documentation

* finalizing initial turbovault documentation ([#121](https://github.com/ScalefreeCOM/turbovault-engine/issues/121)) ([c15dcb3](https://github.com/ScalefreeCOM/turbovault-engine/commit/c15dcb35a744948560000a4f54e53b5681691da5))
* generalize data vault version ([#110](https://github.com/ScalefreeCOM/turbovault-engine/issues/110)) ([9154b96](https://github.com/ScalefreeCOM/turbovault-engine/commit/9154b9676f1e87f296228ea570327f772c4f1599))
* update v0.1.0 changelog to focus on application features ([dce9a21](https://github.com/ScalefreeCOM/turbovault-engine/commit/dce9a21ec589a07c77c6b2d90776eb504621b03d))


### Code Style

* fix black and ruff formatting ([e72d325](https://github.com/ScalefreeCOM/turbovault-engine/commit/e72d32519e489de413e98c55bd23dbd11acd919d))
* format code with Black ([f105cb3](https://github.com/ScalefreeCOM/turbovault-engine/commit/f105cb3c194f79d4a7d8e933805700c42d0937e1))
* reformat 4 files with Black after Ruff changes ([df34aa3](https://github.com/ScalefreeCOM/turbovault-engine/commit/df34aa381ca733485bf59214d2335ab14dc5eb2a))


### Refactoring

* refactoring docs ([9e4fc04](https://github.com/ScalefreeCOM/turbovault-engine/commit/9e4fc047663e8a172c9000e83c7180bda44c644b))
* remove redundant GitHub release job ([#23](https://github.com/ScalefreeCOM/turbovault-engine/issues/23)) ([38877f8](https://github.com/ScalefreeCOM/turbovault-engine/commit/38877f8fb5763d949e5a393cbc8b35608287eb28))


### CI/CD

* add GitHub Actions workflows and development infrastructure ([adec7cc](https://github.com/ScalefreeCOM/turbovault-engine/commit/adec7cc4dae50a5427e8f6776342713cc9710eff))
* auto-commit black formatting fixes ([e72d325](https://github.com/ScalefreeCOM/turbovault-engine/commit/e72d32519e489de413e98c55bd23dbd11acd919d))
* bump actions/checkout from 4 to 6 ([#116](https://github.com/ScalefreeCOM/turbovault-engine/issues/116)) ([409a256](https://github.com/ScalefreeCOM/turbovault-engine/commit/409a256d73927f2ba103efb1736173c724f53c29))
* bump actions/checkout from 4 to 6 ([#8](https://github.com/ScalefreeCOM/turbovault-engine/issues/8)) ([f5332a6](https://github.com/ScalefreeCOM/turbovault-engine/commit/f5332a6b32ffa13e94151152270d15ae6ea375c5))
* bump actions/download-artifact from 4 to 8 ([#117](https://github.com/ScalefreeCOM/turbovault-engine/issues/117)) ([59f7b12](https://github.com/ScalefreeCOM/turbovault-engine/commit/59f7b1240a24f2bbd0b0c1214a628b26d2cf32f4))
* bump actions/download-artifact from 6 to 7 ([6fa0336](https://github.com/ScalefreeCOM/turbovault-engine/commit/6fa0336ed357bf6239888be4e35b41e6e3bcf228))
* bump actions/download-artifact from 7 to 8 ([#98](https://github.com/ScalefreeCOM/turbovault-engine/issues/98)) ([b425c7c](https://github.com/ScalefreeCOM/turbovault-engine/commit/b425c7c2055d8daaa8215b366cdbb6f08c41cbd0))
* bump actions/setup-python from 5 to 6 ([#9](https://github.com/ScalefreeCOM/turbovault-engine/issues/9)) ([fe23eb0](https://github.com/ScalefreeCOM/turbovault-engine/commit/fe23eb03ad8cb710f5e46c9057273d855c9a20a7))
* bump actions/upload-artifact from 4 to 6 ([#7](https://github.com/ScalefreeCOM/turbovault-engine/issues/7)) ([4a91c92](https://github.com/ScalefreeCOM/turbovault-engine/commit/4a91c924e7e5729a9641551aa0c2065cadb1041c))
* bump actions/upload-artifact from 6 to 7 ([#99](https://github.com/ScalefreeCOM/turbovault-engine/issues/99)) ([168e405](https://github.com/ScalefreeCOM/turbovault-engine/commit/168e405b695aec013ba84a6dd83ae3e5fa3edad0))
* bump docker/build-push-action from 5 to 6 ([279ab0c](https://github.com/ScalefreeCOM/turbovault-engine/commit/279ab0c3271179d405cc64c70ebf1b25f339b9bd))
* bump stefanzweifel/git-auto-commit-action from 5 to 7 ([#115](https://github.com/ScalefreeCOM/turbovault-engine/issues/115)) ([281e0d3](https://github.com/ScalefreeCOM/turbovault-engine/commit/281e0d364126a802a3b258fb31a9d80095c9aa28))
* fix gh release upload by adding checkout step ([#113](https://github.com/ScalefreeCOM/turbovault-engine/issues/113)) ([b67e28b](https://github.com/ScalefreeCOM/turbovault-engine/commit/b67e28b1702daf0d21bd066fa2a7b5cde41bb64b))


### Miscellaneous

* **main:** release 0.1.0 ([034a477](https://github.com/ScalefreeCOM/turbovault-engine/commit/034a47749793cbf81a58e3c0b7585606de0e0610))
* **main:** release 0.1.0 ([034a477](https://github.com/ScalefreeCOM/turbovault-engine/commit/034a47749793cbf81a58e3c0b7585606de0e0610))
* **main:** release 0.1.0 ([a1cf67d](https://github.com/ScalefreeCOM/turbovault-engine/commit/a1cf67d15c29403e5db418a897f7791a79c627c8))
* **main:** release 0.1.1 ([#18](https://github.com/ScalefreeCOM/turbovault-engine/issues/18)) ([5803780](https://github.com/ScalefreeCOM/turbovault-engine/commit/5803780e5c7192f0afb6adeffd562316b95ef478))
* **main:** release 0.1.2 ([4857a1e](https://github.com/ScalefreeCOM/turbovault-engine/commit/4857a1eec6be6f69aaba406b30260e2e4ab048a4))
* **main:** release 0.2.0 ([#22](https://github.com/ScalefreeCOM/turbovault-engine/issues/22)) ([1e1d9bb](https://github.com/ScalefreeCOM/turbovault-engine/commit/1e1d9bb224117bb8276e70dcaea709ecf08190a3))
* **main:** release 0.3.0 ([#25](https://github.com/ScalefreeCOM/turbovault-engine/issues/25)) ([e4b5b3d](https://github.com/ScalefreeCOM/turbovault-engine/commit/e4b5b3dec523d2b188de7a463fbd32f261d6185a))
* **main:** release 0.4.0 ([#27](https://github.com/ScalefreeCOM/turbovault-engine/issues/27)) ([24a83b7](https://github.com/ScalefreeCOM/turbovault-engine/commit/24a83b7da61413a212eb54a8c01e27ec77f3bfdf))
* **main:** release turbovault-engine 0.10.0 ([#111](https://github.com/ScalefreeCOM/turbovault-engine/issues/111)) ([847f058](https://github.com/ScalefreeCOM/turbovault-engine/commit/847f058c4db82f344b0a5f99e05547e23ca06744))
* **main:** release turbovault-engine 0.10.1 ([#114](https://github.com/ScalefreeCOM/turbovault-engine/issues/114)) ([5685b25](https://github.com/ScalefreeCOM/turbovault-engine/commit/5685b25bf74778cf7bd491e54b5763715ae7a94f))
* **main:** release turbovault-engine 0.10.2 ([#120](https://github.com/ScalefreeCOM/turbovault-engine/issues/120)) ([848fab0](https://github.com/ScalefreeCOM/turbovault-engine/commit/848fab0a5a3ea1c3315d92e32fd3bb881a69a46c))
* **main:** release turbovault-engine 0.10.3 ([#122](https://github.com/ScalefreeCOM/turbovault-engine/issues/122)) ([604d663](https://github.com/ScalefreeCOM/turbovault-engine/commit/604d663ae3d4e40fc3c4c5a4c8e6cbac28553f51))
* **main:** release turbovault-engine 0.5.0 ([#31](https://github.com/ScalefreeCOM/turbovault-engine/issues/31)) ([0c677ae](https://github.com/ScalefreeCOM/turbovault-engine/commit/0c677ae3ba6a5b922388e8d48146c87a7c178694))
* **main:** release turbovault-engine 0.5.1 ([677f076](https://github.com/ScalefreeCOM/turbovault-engine/commit/677f0767092109eef5dc2b3fe0a73fdb30cce0ff))
* **main:** release turbovault-engine 0.6.0 ([#37](https://github.com/ScalefreeCOM/turbovault-engine/issues/37)) ([d0d50e1](https://github.com/ScalefreeCOM/turbovault-engine/commit/d0d50e1e75ba2b9db59feee7c99fb62f116fbba0))
* **main:** release turbovault-engine 0.7.0 ([#40](https://github.com/ScalefreeCOM/turbovault-engine/issues/40)) ([0aca076](https://github.com/ScalefreeCOM/turbovault-engine/commit/0aca076a7e0da6634c20c395766ef2a7e298fff7))
* **main:** release turbovault-engine 0.7.1 ([bcbf8a0](https://github.com/ScalefreeCOM/turbovault-engine/commit/bcbf8a00e02c36ced92a165618844b3ab62c2e8b))
* **main:** release turbovault-engine 0.7.2 ([ece33db](https://github.com/ScalefreeCOM/turbovault-engine/commit/ece33dba9383841690b072b1dce66b50d99608a5))
* **main:** release turbovault-engine 0.7.3 ([#70](https://github.com/ScalefreeCOM/turbovault-engine/issues/70)) ([662847b](https://github.com/ScalefreeCOM/turbovault-engine/commit/662847b417893a5931a18bfd19c655db164bff7d))
* **main:** release turbovault-engine 0.8.0 ([#81](https://github.com/ScalefreeCOM/turbovault-engine/issues/81)) ([5bce413](https://github.com/ScalefreeCOM/turbovault-engine/commit/5bce4132416493ffb894a9993d2f001238ecfc48))
* **main:** release turbovault-engine 0.9.0 ([#87](https://github.com/ScalefreeCOM/turbovault-engine/issues/87)) ([0a42405](https://github.com/ScalefreeCOM/turbovault-engine/commit/0a42405340d6452c698346784e94144b931622c4))
* release v0.1.0 ([9309263](https://github.com/ScalefreeCOM/turbovault-engine/commit/9309263aef6fc67705c45ddd8369dd93f1a9bcc1))

## [0.10.3](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.10.2...turbovault-engine-v0.10.3) (2026-03-19)


### Documentation

* finalizing initial turbovault documentation ([#121](https://github.com/ScalefreeCOM/turbovault-engine/issues/121)) ([144dc86](https://github.com/ScalefreeCOM/turbovault-engine/commit/144dc867107e5f3eda3f5e564999e22f7b9d75bc))

## [0.10.2](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.10.1...turbovault-engine-v0.10.2) (2026-03-18)


### CI/CD

* bump actions/checkout from 4 to 6 ([#116](https://github.com/ScalefreeCOM/turbovault-engine/issues/116)) ([8e5a0c6](https://github.com/ScalefreeCOM/turbovault-engine/commit/8e5a0c6c4fab3187d7275ddb3c53c591ca5df007))
* bump actions/download-artifact from 4 to 8 ([#117](https://github.com/ScalefreeCOM/turbovault-engine/issues/117)) ([e304da7](https://github.com/ScalefreeCOM/turbovault-engine/commit/e304da70b0a72b186e5b540998ebdb6a03ffd54b))
* bump stefanzweifel/git-auto-commit-action from 5 to 7 ([#115](https://github.com/ScalefreeCOM/turbovault-engine/issues/115)) ([34cbf83](https://github.com/ScalefreeCOM/turbovault-engine/commit/34cbf832a645c3f432f952bbfbc47e34d34ec5d6))

## [0.10.1](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.10.0...turbovault-engine-v0.10.1) (2026-03-13)


### CI/CD

* fix gh release upload by adding checkout step ([#113](https://github.com/ScalefreeCOM/turbovault-engine/issues/113)) ([6e9f073](https://github.com/ScalefreeCOM/turbovault-engine/commit/6e9f073ffa3af5497483dc211dea2e6b8c0450de))

## [0.10.0](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.9.0...turbovault-engine-v0.10.0) (2026-03-13)


### Features

* adding package building and preparing pypi publishing ([#112](https://github.com/ScalefreeCOM/turbovault-engine/issues/112)) ([9ae55cf](https://github.com/ScalefreeCOM/turbovault-engine/commit/9ae55cfe871f4537d0cab6b95d462ca6b19eb062))


### Documentation

* generalize data vault version ([#110](https://github.com/ScalefreeCOM/turbovault-engine/issues/110)) ([25bda93](https://github.com/ScalefreeCOM/turbovault-engine/commit/25bda93d28b667e34f89ca9944045c92b98e2bad))


### Code Style

* fix black and ruff formatting ([9ae55cf](https://github.com/ScalefreeCOM/turbovault-engine/commit/9ae55cfe871f4537d0cab6b95d462ca6b19eb062))


### CI/CD

* auto-commit black formatting fixes ([9ae55cf](https://github.com/ScalefreeCOM/turbovault-engine/commit/9ae55cfe871f4537d0cab6b95d462ca6b19eb062))

## [0.9.0](https://github.com/ScalefreeCOM/turbovault-engine/compare/turbovault-engine-v0.8.0...turbovault-engine-v0.9.0) (2026-03-04)


### Features

* adding version cli flag ([#95](https://github.com/ScalefreeCOM/turbovault-engine/issues/95)) ([3a5f22f](https://github.com/ScalefreeCOM/turbovault-engine/commit/3a5f22fe8f542e45d7a7b2589a085b427a92dab6))
* **ci:** logo and colors updated ([#86](https://github.com/ScalefreeCOM/turbovault-engine/issues/86)) ([af64e6f](https://github.com/ScalefreeCOM/turbovault-engine/commit/af64e6fb873a4263def7b4ed06f7300ed094fe05))
* Implement anonymous usage statistics for the CLI with an opt-ou… ([#96](https://github.com/ScalefreeCOM/turbovault-engine/issues/96)) ([0e731d7](https://github.com/ScalefreeCOM/turbovault-engine/commit/0e731d7adc3570a72fea79c3443431cd7c913c8a))
* Implement anonymous usage statistics for the CLI with an opt-out option ([0e731d7](https://github.com/ScalefreeCOM/turbovault-engine/commit/0e731d7adc3570a72fea79c3443431cd7c913c8a))
* **sources:** one yml per source ([#97](https://github.com/ScalefreeCOM/turbovault-engine/issues/97)) ([5dd9c5f](https://github.com/ScalefreeCOM/turbovault-engine/commit/5dd9c5f6498f45fd0b234e11feb62939f89b7c6b))


### Bug Fixes

* Schema Configs are now properly used in dbt_project.yml ([#100](https://github.com/ScalefreeCOM/turbovault-engine/issues/100)) ([e23dc41](https://github.com/ScalefreeCOM/turbovault-engine/commit/e23dc417900e17155e3106f532e5a450679ad66b))
* **schema:** bdv_schema added and all propagated to dbt_project.yml ([e23dc41](https://github.com/ScalefreeCOM/turbovault-engine/commit/e23dc417900e17155e3106f532e5a450679ad66b))


### CI/CD

* bump actions/download-artifact from 7 to 8 ([#98](https://github.com/ScalefreeCOM/turbovault-engine/issues/98)) ([f71a7c9](https://github.com/ScalefreeCOM/turbovault-engine/commit/f71a7c940a530d4adffa68e1f2760276a5c9ab9c))
* bump actions/upload-artifact from 6 to 7 ([#99](https://github.com/ScalefreeCOM/turbovault-engine/issues/99)) ([0a5c6fe](https://github.com/ScalefreeCOM/turbovault-engine/commit/0a5c6febc90b35e34548528eae43e59c466f39be))

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
