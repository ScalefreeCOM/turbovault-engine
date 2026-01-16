# Quick Release Checklist

TurboVault Engine uses **Release Please** for automated releases. This checklist is for the simplified automated workflow.

## 🤖 Automated Workflow (Primary)

### Making Changes

- [ ] Create feature branch: `git checkout -b feat/my-feature`
- [ ] Make changes
- [ ] Commit with conventional commits:
  - `feat:` for features
  - `fix:` for bug fixes
  - `docs:` for documentation
  - `chore:` for maintenance
- [ ] Push and create PR
- [ ] Merge PR to `main`

### When Release PR Appears

Release Please automatically creates a PR titled `chore: release vX.Y.Z`:

- [ ] Review the Release PR:
  - [ ] Version number looks correct
  - [ ] Changelog entries are accurate
  - [ ] All changes are included
- [ ] Merge the Release PR

### After Merge

Automatically happens:
- [ ] ✅ GitHub release created
- [ ] ✅ Docker image published to GHCR
- [ ] ⏭️ PyPI package (if `PYPI_API_TOKEN` configured)

## 🎯 Verification

### GitHub Release

- [ ] Go to: https://github.com/ScalefreeCOM/turbovault-engine/releases
- [ ] Verify latest release exists
- [ ] Check release notes

### Docker Image

```bash
docker pull ghcr.io/scalefreec om/turbovault-engine:latest
docker run ghcr.io/scalefreec om/turbovault-engine:latest turbovault --version
```

- [ ] Image pulls successfully
- [ ] Version is correct

### PyPI (If Enabled)

```bash
pip install --upgrade turbovault-engine
turbovault --version
```

- [ ] Package installs
- [ ] Version is correct

---

## 💡 Tips

**Force a specific version:**
Add label to Release PR: `release-as: 1.0.0`

**Trigger release without changes:**
```bash
git commit --allow-empty -m "chore: trigger release"
git push origin main
```

**Update Release PR:**
Just close it - Release Please will create a new one with latest changes

---

## 📚 Conventional Commit Examples

```bash
git commit -m "feat: add JSON export command"
git commit -m "fix: resolve template rendering bug"
git commit -m "docs: update README with Docker instructions"
git commit -m "feat!: change CLI argument format" # Breaking change
```

---

## 🆘 Troubleshooting

**No Release PR created?**
- Check commits have conventional commit format
- Verify commits are on `main`
- Check Actions → Release Please workflow

**Release PR shows wrong version?**
- Add label: `release-as: X.Y.Z`
- Or close PR and let it recreate

---

**Manual Release Process (Deprecated):**
See [RELEASING.md](RELEASING.md) for the legacy manual process (kept for reference).


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
