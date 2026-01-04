# 🚀 CI/CD Quick Setup Guide

This guide helps you get started with the CI/CD infrastructure for TurboVault Engine.

## ✅ Phase 1 - Foundation (Implemented)

### What's Been Added

- **GitHub Actions CI Pipeline** (`.github/workflows/ci.yml`)
  - Runs on every push to `main` and all pull requests
  - Checks: Black formatting, Ruff linting, mypy type checking (warnings only)
  - Tests: pytest on Python 3.12 and 3.13
  - Build verification: Package building and metadata checks

- **Pre-commit Hooks** (`.pre-commit-config.yaml`)
  - Automatic code formatting with Black
  - Linting with Ruff
  - Type checking with mypy (non-blocking)
  - File checks (trailing whitespace, large files, etc.)

- **Templates**
  - Pull Request template (`.github/PULL_REQUEST_TEMPLATE.md`)
  - Bug report template (`.github/ISSUE_TEMPLATE/bug_report.md`)
  - Feature request template (`.github/ISSUE_TEMPLATE/feature_request.md`)

- **Documentation**
  - Contributing guidelines (`CONTRIBUTING.md`)
  - Changelog (`CHANGELOG.md`)

### Next Steps for You

1. **Install pre-commit hooks (recommended for local development):**
   ```bash
   pip install pre-commit
   pre-commit install
   ```

2. **Commit and push these changes:**
   ```bash
   git add .
   git commit -m "ci: add GitHub Actions workflows and development infrastructure"
   git push origin main
   ```

3. **Verify GitHub Actions:**
   - Go to your GitHub repository
   - Click on the "Actions" tab
   - Watch the CI pipeline run for your commit

4. **Test the pre-commit hooks locally:**
   ```bash
   # Make a test change
   echo "# test" >> backend/tests/test_example.py
   
   # Try to commit (hooks will run)
   git add backend/tests/test_example.py
   git commit -m "test: verify pre-commit hooks"
   
   # Clean up test file
   git reset HEAD backend/tests/test_example.py
   git checkout -- backend/tests/test_example.py
   ```

### How It Works

#### CI Pipeline Flow

```
Push to main or PR
    │
    ├─── Lint Job
    │    ├── Black format check
    │    ├── Ruff linting
    │    └── mypy type check (warns only)
    │
    ├─── Test Job (Python 3.12 & 3.13)
    │    ├── Install dependencies
    │    ├── Run migrations
    │    ├── Run pytest
    │    └── CLI smoke tests
    │
    └─── Build Job
         ├── Build package
         ├── Check metadata
         └── Upload artifacts
```

#### Pre-commit Hook Flow

```
git commit
    │
    ├── Trailing whitespace check
    ├── Large file check
    ├── YAML/TOML validation
    ├── Black formatting (auto-fixes)
    ├── Ruff linting (auto-fixes)
    └── mypy type checking (non-blocking)
    │
    └── If all pass → Commit succeeds
        If any fail → Commit blocked (except mypy)
```

### Branch Protection (Already Configured)

Your `main` branch should have:
- ✅ 1 required approval for PRs
- ⏳ Required status checks (add after first CI run):
  - `lint`
  - `test (3.12)`
  - `test (3.13)`
  - `build`

**To enable status checks:**
1. After your first push, go to: Settings → Branches → main rule
2. Under "Require status checks to pass before merging"
3. Check the boxes for: `lint`, `test`, `build`

## 📋 Common Tasks

### Running Quality Checks Locally

```bash
# Format code
black backend/

# Check formatting (no changes)
black --check backend/

# Lint code
ruff check backend/

# Auto-fix linting issues
ruff check backend/ --fix

# Type check (warnings OK)
mypy backend/engine backend/turbovault

# Run all tests
python -m pytest backend/tests/ -v
```

### Creating a Pull Request

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make your changes
3. Run quality checks locally
4. Commit with conventional commit message: `git commit -m "feat: add feature"`
5. Push: `git push origin feature/my-feature`
6. Create PR on GitHub (template will auto-populate)
7. Address CI feedback and reviewer comments
8. Squash and merge when approved

### Bypassing Pre-commit Hooks (Emergency Only)

```bash
# Use only when absolutely necessary
git commit --no-verify -m "emergency fix"
```

## ✅ Phase 2 - Enhanced CI (Implemented)

### What's Been Added

- **Dependabot** (`.github/dependabot.yml`)
  - Automated Python dependency updates (weekly on Mondays)
  - Automated GitHub Actions updates (weekly on Mondays)
  - Minor/patch updates grouped together
  - Major updates in separate PRs

- **Documentation Issue Template** (`.github/ISSUE_TEMPLATE/documentation.md`)  
  - Structured template for documentation improvement requests
  - Makes it easy to report documentation gaps

### How Dependabot Works

1. **Weekly Checks:** Every Monday at 9:00 AM
2. **Automatic PRs:** Creates pull requests for dependency updates
3. **CI Verification:** All Dependabot PRs run through the full CI pipeline
4. **Labels:** Auto-labels with `dependencies` and ecosystem type

**Managing Dependabot PRs:**
- Review the changelog and CI results
- Merge if CI passes and changes look safe
- For major updates, test locally first
- Comment `@dependabot recreate` to rebuild a PR

**Find Dependabot PRs:**
- Go to Pull Requests tab
- Filter by label: `dependencies`

## ✅ Phase 3 - Docker & Release (Implemented)

### What's Been Added

- **Dockerfile** (Multi-stage build)
  - Optimized for production deployment
  - Non-root user for security
  - Minimal image size (< 500MB)
  - Health checks included

- **docker-compose.yml** (Local Development)
  - Django admin on port 8000
  - Persistent database volume
  - Live code reloading
  - Easy `docker-compose up` workflow

- **Release Workflow** (`.github/workflows/release.yml`)
  - Triggered by version tags (e.g., `v0.1.0`)
  - Runs full test suite before release
  - Builds and publishes Python package
  - Publishes Docker images to GitHub Container Registry (GHCR)
  - Creates GitHub releases with auto-generated notes
  - **PyPI publishing ready** (add `PYPI_API_TOKEN` secret to enable)

- **RELEASING.md Guide**
  - Step-by-step release process
  - PyPI setup instructions
  - Docker image publishing
  - Troubleshooting guide

### Docker Usage

**Local Development:**
```bash
docker-compose up
# Access Django admin at http://localhost:8000/admin
```

**Production:**
```bash
# After first release
docker pull ghcr.io/scalefreec om/turbovault-engine:latest
docker run ghcr.io/scalefreec om/turbovault-engine:latest turbovault --help
```

### Release Process

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Commit and push to `main`
4. Create and push tag: `git tag v0.2.0 && git push origin v0.2.0`
5. Release workflow runs automatically
6. Docker image published to GHCR
7. GitHub release created
8. PyPI release (if `PYPI_API_TOKEN` configured)

**See [RELEASING.md](file:///c:/Users/obause/Documents/repos/turbovault-engine/RELEASING.md) for full details.**

---

## 🚀 Quick Release Guide

### Creating a New Release (Step-by-Step)

**1. Prepare the Release**

```bash
# Make sure you're on main and up to date
git checkout main
git pull origin main

# Ensure all tests pass
python -m pytest backend/tests/ -v
```

**2. Update Version**

Edit `pyproject.toml`:
```toml
[project]
name = "turbovault-engine"
version = "0.2.0"  # ← Change this
```

**3. Update Changelog**

Edit `CHANGELOG.md` - move items from `[Unreleased]` to a new version section:

```markdown
## [Unreleased]

### Added
### Changed
### Fixed

## [0.2.0] - 2026-01-15

### Added
- New feature X
- New feature Y

### Fixed
- Bug Z
```

**4. Commit and Push**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release v0.2.0"
git push origin main
```

**5. Create and Push Tag**

```bash
# Create annotated tag
git tag -a v0.2.0 -m "Release v0.2.0"

# Push tag (this triggers the release!)
git push origin v0.2.0
```

**6. Monitor Release**

1. Go to GitHub → Actions tab
2. Watch "Release" workflow
3. Wait for all jobs to complete (~5-10 minutes)
4. Check:
   - ✅ Tests passed
   - ✅ Package built
   - ✅ Docker image published to GHCR
   - ✅ GitHub release created
   - ⏭️ PyPI (skipped until you add `PYPI_API_TOKEN`)

**7. Verify Release**

```bash
# Test Docker image
docker pull ghcr.io/scalefreec om/turbovault-engine:0.2.0
docker run ghcr.io/scalefreec om/turbovault-engine:0.2.0 turbovault --version

# If PyPI is enabled:
pip install turbovault-engine==0.2.0
turbovault --version
```

### First Release Checklist

For your very first release (`v0.1.0`):

- [ ] Merge all pending PRs to `main`
- [ ] All CI checks passing on `main`
- [ ] Update version to `0.1.0` in `pyproject.toml`
- [ ] Add `## [0.1.0] - YYYY-MM-DD` section to `CHANGELOG.md`
- [ ] Commit: `git commit -m "chore: release v0.1.0"`
- [ ] Create tag: `git tag -a v0.1.0 -m "Initial release"`
- [ ] Push: `git push origin main v0.1.0`
- [ ] Monitor Actions tab for workflow completion
- [ ] Check GitHub Releases page
- [ ] Test Docker image from GHCR
- [ ] (Optional) Add `PYPI_API_TOKEN` secret for PyPI publishing

### Common Release Scenarios

**Patch Release (Bug Fix):**
```bash
# 0.1.0 → 0.1.1
# Update version, changelog, commit, tag, push
git tag -a v0.1.1 -m "Fix critical bug"
```

**Minor Release (New Features):**
```bash
# 0.1.0 → 0.2.0
# Update version, changelog, commit, tag, push
git tag -a v0.2.0 -m "Add new features"
```

**Major Release (Breaking Changes):**
```bash
# 0.2.0 → 1.0.0
# Update version, changelog, commit, tag, push
git tag -a v1.0.0 -m "First stable release"
```

**Pre-release (Testing):**
```bash
# For release candidates, alphas, betas
git tag -a v0.2.0-rc.1 -m "Release candidate 1"
git tag -a v1.0.0-beta.1 -m "Beta 1"
```

### Troubleshooting Releases

**"Tag already exists"**
```bash
# Delete and recreate
git tag -d v0.2.0
git push origin :refs/tags/v0.2.0
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

**"Workflow didn't trigger"**
- Check tag format: must be `v*.*.*` (with the `v` prefix)
- Check Actions tab for errors
- Verify workflow file exists: `.github/workflows/release.yml`

**"Docker push failed"**
- Check if package visibility is public in GitHub settings
- Go to: Settings → Packages → turbovault-engine → Manage visibility

**Full troubleshooting guide:** See [RELEASING.md](file:///c:/Users/obause/Documents/repos/turbovault-engine/RELEASING.md#troubleshooting)

---

## 🔮 Next Phases (Not Implemented Yet)

### Phase 4: Quality Gates
- Increased test coverage (target: 80%+)
- Performance benchmarking
- Documentation linting
- Security scanning

## 🆘 Troubleshooting

### Pre-commit hooks fail on first run

```bash
# Update the hooks
pre-commit autoupdate

# Run manually to see detailed errors
pre-commit run --all-files
```

### CI fails with mypy errors

Don't worry! mypy is configured to warn only and won't block the CI pipeline or PRs.

### Tests fail in CI but pass locally

1. Ensure you've committed all necessary files
2. Check Python version (CI uses 3.12 and 3.13)
3. Check for environment-specific dependencies

## 📚 Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Pre-commit Documentation](https://pre-commit.com/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Keep a Changelog](https://keepachangelog.com/)

---

**Questions?** Check `CONTRIBUTING.md` or open a discussion on GitHub!
