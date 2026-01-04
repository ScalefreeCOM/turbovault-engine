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

## 🔮 Next Phases (Not Implemented Yet)

### Phase 2: Enhanced CI
- Code coverage reporting
- Dependabot for automated updates
- Security scanning

### Phase 3: Docker & Release
- Dockerfile for containerization
- docker-compose for local development
- Release workflow for PyPI publishing
- Automated GitHub releases

### Phase 4: Quality Gates
- Increased test coverage (target: 80%+)
- Performance benchmarking
- Documentation linting

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
