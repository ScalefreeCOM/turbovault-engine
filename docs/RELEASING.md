# Automated Release Workflow Guide

TurboVault Engine uses **Release Please** for fully automated releases. No manual version bumping or tagging required!

## 🤖 How It Works

1. **Make changes** using conventional commits
2. **Merge PRs** to `main`
3. **Release Please bot** creates a "Release PR" automatically
4. **Review and merge** the Release PR
5. **Release happens automatically** - that's it!

## 📝 Conventional Commits

Use these prefixes in your commit messages:

- `feat:` - New feature (→ minor version bump: 0.1.0 → 0.2.0)
- `fix:` - Bug fix (→ patch version bump: 0.1.0 → 0.1.1)
- `docs:` - Documentation only
- `style:` - Code formatting
- `refactor:` - Code refactoring
- `perf:` - Performance improvements
- `test:` - Adding tests
- `chore:` - Maintenance tasks
- `ci:` - CI/CD changes

**Breaking changes:** Add `!` after type or `BREAKING CHANGE:` in footer (→ major version bump: 0.1.0 → 1.0.0)

## 🚀 Quick Release Guide

### Normal Workflow

```bash
# 1. Create feature branch
git checkout -b feat/my-feature

# 2. Make changes and commit with conventional commits
git commit -m "feat: add new export format"
git commit -m "fix: resolve validation bug"

# 3. Push and create PR
git push origin feat/my-feature
# Create PR on GitHub

# 4. Merge PR to main
# That's it! Release Please monitors main branch
```

### Release PR Appears

After merging PRs, **Release Please automatically**:
- Creates a "Release PR" (title: `chore: release X.Y.Z`)
- Updates version in `pyproject.toml`
- Updates `CHANGELOG.md`
- Shows all changes since last release

**When you're ready to release:**
1. Review the Release PR
2. Merge it
3. **Automatic release + Docker publish + PyPI (if enabled)**

## 📊 Example Flow

```
Day 1:
PR: feat: add JSON export        → Merge to main
PR: fix: template rendering      → Merge to main

Day 2:
Release Please creates PR: "chore: release 0.2.0"
├── pyproject.toml: version = "0.2.0"
├── CHANGELOG.md: 
│   ## [0.2.0]
│   ### Features
│   - add JSON export
│   ### Bug Fixes
│   - template rendering

You: Review and merge the release PR

GitHub: ✅ Creates release v0.2.0
GitHub: ✅ Builds and publishes Docker image
GitHub: ✅ Publishes to PyPI (if token configured)
```

## ⚙️ What Gets Automated

✅ **Version Bumping**
- Analyzes commit messages
- Follows semantic versioning
- Updates `pyproject.toml` automatically

✅ **Changelog Generation**
- Extracts from conventional commits
- Organizes by type (Features, Bug Fixes, etc.)
- Maintains `CHANGELOG.md`

✅ **GitHub Release**
- Creates release on merge
- Includes changelog excerpt
- Attaches build artifacts

✅ **Publishing**
- Docker image to GHCR
- Python package to PyPI (if enabled)

## 🎯 Release PR Workflow

### 1. Release PR Created (Automatic)

After you merge feature PRs, Release Please opens a PR titled:
```
chore: release v0.2.0
```

### 2. Review the Release PR

Check:
- [ ] Version number is correct
- [ ] Changelog entries are accurate
- [ ] All intended changes are included
- [ ] No unwanted changes

### 3. Merge the Release PR

- Merge when ready to release
- Release happens immediately after merge
- Monitor Actions tab for workflow progress

### 4. Release Published

Automatically:
- GitHub release created
- Docker image published to ghcr.io
- PyPI package published (if token set)

## 🔧 Advanced Usage

### Force a Specific Version

Add label to Release PR:
- `release-as: major` - Force major version (1.0.0 → 2.0.0)
- `release-as: minor` - Force minor version (1.0.0 → 1.1.0)
- `release-as: patch` - Force patch version (1.0.0 → 1.0.1)
- `release-as: 1.5.0` - Force specific version

### Skip Release

Add `Release-As: 0.0.0` to commit message or PR body to skip release creation.

### Pre-releases

Not directly supported by Release Please, but you can:
1. Create pre-release manually on GitHub
2. Or use tags: `v1.0.0-beta.1`

## 🆘 Troubleshooting

**"Release PR not created?"**
- Check commits use conventional commit format
- Ensure commits are on `main` branch
- Check Actions tab for Release Please workflow

**"Release PR shows wrong version?"**
- Add label `release-as: X.Y.Z` to force version
- Or close PR, Release Please will recreate

**"Want to release now but no PR?"**
- Make a trivial change: `git commit --allow-empty -m "chore: trigger release"`
- Push to main
- Release PR will appear

**"Need to update Release PR?"**
- Close the Release PR
- Release Please will create a new one with latest changes

## 📚 Migration from Manual Process

If you have existing tags (from manual process):
1. ✅ Release Please respects existing tags
2. ✅ Starts versioning from last tag
3. ✅ No conflicts with previous releases

## 🎓 Best Practices

1. **Write descriptive commit messages**
   ```
   Good: feat: add Docker export command with compression support
   Bad:  feat: updates
   ```

2. **One feature per commit**
   - Makes changelog clearer
   - Easier to understand releases

3. **Review Release PR carefully**
   - Verify changelog makes sense
   - Check version bump is appropriate

4. **Release regularly**
   - Don't let Release PR accumulate too many changes
   - Weekly or bi-weekly releases work well

## 🔗 Resources

- [Release Please Docs](https://github.com/google-github-actions/release-please-action)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Semantic Versioning](https://semver.org/)

---

**Questions?** Open an issue or discussion on GitHub.
