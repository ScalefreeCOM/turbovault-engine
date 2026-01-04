# Quick Release Checklist

Use this checklist when creating a new release. For detailed documentation, see [RELEASING.md](RELEASING.md).

## Pre-Release

- [ ] All tests passing on `main` branch
- [ ] All PRs merged that should be in this release
- [ ] No critical open bugs

## Release Steps

### 1. Update Version

- [ ] Edit `pyproject.toml`, change version number:
  ```toml
  version = "0.2.0"  # Update this line
  ```

### 2. Update Changelog

- [ ] Edit `CHANGELOG.md`
- [ ] Move items from `[Unreleased]` to new version section
- [ ] Add release date
  ```markdown
  ## [0.2.0] - 2026-01-15
  
  ### Added
  - Feature X
  
  ### Fixed
  - Bug Y
  ```

### 3. Commit Changes

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release v0.2.0"
git push origin main
```

- [ ] Changes committed
- [ ] Pushed to `main`

### 4. Create Tag

```bash
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

- [ ] Tag created locally
- [ ] Tag pushed to GitHub

### 5. Monitor Workflow

Go to: https://github.com/ScalefreeCOM/turbovault-engine/actions

Wait for "Release" workflow to complete:

- [ ] ✅ Run Tests
- [ ] ✅ Build Python Package
- [ ] ✅ Build and Push Docker Image
- [ ] ✅ Create GitHub Release
- [ ] ⏭️ Publish to PyPI (skipped if `PYPI_API_TOKEN` not set)

## Post-Release Verification

### GitHub Release

- [ ] Go to: https://github.com/ScalefreeCOM/turbovault-engine/releases
- [ ] Verify release `v0.2.0` exists
- [ ] Check release notes are correct
- [ ] Verify wheel and source files are attached

### Docker Image

```bash
docker pull ghcr.io/scalefreec om/turbovault-engine:0.2.0
docker run ghcr.io/scalefreec om/turbovault-engine:0.2.0 turbovault --version
```

- [ ] Docker image pulls successfully
- [ ] Version number is correct

### PyPI (If Enabled)

```bash
pip install --upgrade turbovault-engine==0.2.0
turbovault --version
```

- [ ] Package installs from PyPI
- [ ] Version number is correct

## Troubleshooting

**Workflow not triggered?**
- Check tag format starts with `v`: `v0.2.0` ✅, `0.2.0` ❌

**Tag already exists?**
```bash
git tag -d v0.2.0                    # Delete local
git push origin :refs/tags/v0.2.0   # Delete remote
# Then recreate
```

**Tests failing?**
- Check Actions tab for details
- Fix issues and create a new tag (e.g., `v0.2.1`)

---

## Quick Commands

```bash
# Full release in one go (after updating version & changelog)
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release v0.2.0"
git push origin main
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

## First-Time Setup

### Enable PyPI Publishing (Optional)

1. Create PyPI account: https://pypi.org/account/register/
2. Generate API token: https://pypi.org/manage/account/token/
3. Add to GitHub secrets:
   - Go to: Settings → Secrets → Actions
   - Name: `PYPI_API_TOKEN`
   - Value: `pypi-...` (your token)

Once added, next release will automatically publish to PyPI!

---

**Need more details?** See [RELEASING.md](RELEASING.md) for comprehensive documentation.
