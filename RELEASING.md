# Releasing TurboVault Engine

This document describes the release process for TurboVault Engine.

## 📋 Release Checklist

### Pre-Release

- [ ] All tests passing on `main`
- [ ] CHANGELOG.md updated with changes for this version
- [ ] Version number updated in `pyproject.toml`
- [ ] Documentation updated (if needed)
- [ ] No open critical bugs

### Release Process

1. **Update Version Number**
   
   Edit `pyproject.toml`:
   ```toml
   [project]
   name = "turbovault-engine"
   version = "0.2.0"  # Update this
   ```

2. **Update CHANGELOG.md**
   
   Move items from `[Unreleased]` to a new version section:
   ```markdown
   ## [0.2.0] - 2026-01-15
   
   ### Added
   - New feature X
   - New feature Y
   
   ### Fixed
   - Bug fix Z
   ```

3. **Commit Changes**
   ```bash
   git add pyproject.toml CHANGELOG.md
   git commit -m "chore: bump version to 0.2.0"
   git push origin main
   ```

4. **Create and Push Tag**
   ```bash
   # Create annotated tag
   git tag -a v0.2.0 -m "Release v0.2.0"
   
   # Push tag to trigger release
   git push origin v0.2.0
   ```

5. **Monitor Release Workflow**
   
   - Go to Actions tab on GitHub
   - Watch "Release" workflow
   - Verify all jobs complete successfully:
     - ✅ Run Tests
     - ✅ Build Python Package
     - ✅ Build and Push Docker Image
     - ✅ Create GitHub Release
     - ⏭️  Publish to PyPI (skips if PYPI_API_TOKEN not set)

### Post-Release

- [ ] Verify GitHub Release created
- [ ] Verify Docker image published to ghcr.io
- [ ] Test installation: `pip install turbovault-engine==0.2.0` (if PyPI enabled)
- [ ] Test Docker image: `docker pull ghcr.io/scalefreec om/turbovault-engine:0.2.0`
- [ ] Announce release (if applicable)

---

## 🐍 PyPI Publishing (Optional Setup)

PyPI publishing is disabled by default. To enable:

### One-Time Setup

1. **Create PyPI Account**
   - Register at https://pypi.org/account/register/
   - Verify your email

2. **Generate API Token**
   - Go to https://pypi.org/manage/account/token/
   - Create a new token with scope "Entire account"
   - Copy the token (starts with `pypi-`)

3. **Add Token to GitHub Secrets**
   - Go to repository Settings → Secrets and variables → Actions
   - Click "New repository secret"
   - Name: `PYPI_API_TOKEN`
   - Value: Paste your PyPI token
   - Save

4. **Verify Setup** (Optional - Use TestPyPI First)
   
   Before publishing to real PyPI, test with TestPyPI:
   - Register at https://test.pypi.org/
   - Generate token
   - Add as `TEST_PYPI_API_TOKEN` secret
   - Modify release workflow temporarily to use TestPyPI

Once the `PYPI_API_TOKEN` secret exists, the release workflow will automatically publish to PyPI.

---

## 🐳 Docker Images

Docker images are automatically published to GitHub Container Registry (ghcr.io) on every release.

### Image Tags

Each release creates multiple tags:
- `ghcr.io/scalefreec om/turbovault-engine:0.2.0` (exact version)
- `ghcr.io/scalefreec om/turbovault-engine:0.2` (minor version)
- `ghcr.io/scalefreec om/turbovault-engine:0` (major version)
- `ghcr.io/scalefreec om/turbovault-engine:latest` (latest release)

### Testing Docker Images

```bash
# Pull the image
docker pull ghcr.io/scalefreec om/turbovault-engine:latest

# Test CLI
docker run ghcr.io/scalefreec om/turbovault-engine:latest turbovault --version

# Test Django admin
docker run -p 8000:8000 ghcr.io/scalefreec om/turbovault-engine:latest turbovault serve
```

---

## 🔄 Version Numbering

We follow [Semantic Versioning](https://semver.org/):

- `MAJOR.MINOR.PATCH` (e.g., `1.2.3`)
  - **MAJOR**: Breaking changes
  - **MINOR**: New features (backward compatible)
  - **PATCH**: Bug fixes (backward compatible)

### Pre-Release Versions

For testing:
- `1.0.0-alpha.1` - Alpha release
- `1.0.0-beta.1` - Beta release
- `1.0.0-rc.1` - Release candidate

Tag format: `v1.0.0-rc.1`

---

## 🚨 Hotfix Releases

For urgent fixes on a released version:

1. Create hotfix branch from tag:
   ```bash
   git checkout -b hotfix/0.2.1 v0.2.0
   ```

2. Make the fix and commit

3. Update version to `0.2.1` in `pyproject.toml`

4. Update CHANGELOG.md

5. Merge to main:
   ```bash
   git checkout main
   git merge hotfix/0.2.1
   ```

6. Tag and push:
   ```bash
   git tag -a v0.2.1 -m "Hotfix v0.2.1"
   git push origin main v0.2.1
   ```

---

## ⏪ Rolling Back a Release

If a release has critical issues:

### On PyPI
- **Cannot delete** PyPI releases
- Publish a new patch version with the fix
- Mark the bad version as "yanked" on PyPI (prevents new installations)

### On GitHub
- Delete the GitHub release (Settings → Releases → Delete)
- Delete the tag:
  ```bash
  git tag -d v0.2.0
  git push origin :refs/tags/v0.2.0
  ```

### Docker Images
- Delete package versions from GHCR (Packages → Settings → Delete version)

---

## 🤖 Future: Automated Versioning

Currently using manual version bumping. Future enhancements:

- **Release Please**: Automated version bumping based on conventional commits
- **Changelog Generation**: Automatic CHANGELOG updates
- **PR-based Releases**: Create releases via pull requests

---

## 📞 Troubleshooting

### Release Workflow Fails

**Tests fail:**
- Check Actions tab for detailed logs
- Run tests locally: `python -m pytest backend/tests/ -v`
- Fix issues and push to main before creating tag

**Docker build fails:**
- Test locally: `docker build -t test .`
- Check Dockerfile syntax
- Verify all files are included (not in .dockerignore)

**PyPI publish fails:**
- Verify `PYPI_API_TOKEN` secret exists
- Check token hasn't expired
- Ensure version doesn't already exist on PyPI

**GitHub release fails:**
- Check GITHUB_TOKEN has `contents: write` permission
- Verify tag format matches `v*.*.*`

### Tag Already Exists

If you need to recreate a tag:
```bash
# Delete local tag
git tag -d v0.2.0

# Delete remote tag
git push origin :refs/tags/v0.2.0

# Recreate tag
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

---

## 📊 Release Metrics

Track these for each release:
- Time from tag to release completion
- Number of downloads (PyPI)
- Docker image pulls (GHCR)
- Issues closed in this release
- Breaking changes (if any)

---

**Questions?** Open an issue or discussion on GitHub.
