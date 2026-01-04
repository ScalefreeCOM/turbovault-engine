# Contributing to TurboVault Engine

Thank you for your interest in contributing to TurboVault Engine! This document provides guidelines and instructions for contributing to the project.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Commit Messages](#commit-messages)

## 🤝 Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the community
- Show empathy towards other community members

## 🚀 Getting Started

### Prerequisites

- Python 3.12 or higher
- Git
- pip (Python package manager)

### Development Setup

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/turbovault-engine.git
   cd turbovault-engine
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Run the automated setup script (recommended):**
   
   **Windows (PowerShell):**
   ```powershell
   .\scripts\setup-dev.ps1
   ```
   
   **Linux/Mac:**
   ```bash
   chmod +x scripts/setup-dev.sh
   ./scripts/setup-dev.sh
   ```
   
   This script will:
   - Install all dependencies
   - Set up pre-commit hooks
   - Run initial database migrations
   
   **Or, set up manually:**
   ```bash
   pip install -e ".[dev]"
   pre-commit install
   cd backend && python manage.py migrate && cd ..
   ```

6. **Verify your setup:**
   ```bash
   python -m pytest backend/tests/ -v
   turbovault --help
   ```

## 🤖 Automated Dependency Updates

This project uses **Dependabot** to automatically check for dependency updates:

- **Python dependencies** - Checked weekly on Mondays
- **GitHub Actions** - Checked weekly on Mondays

### How it Works

1. Dependabot creates PRs for dependency updates
2. CI runs automatically on these PRs
3. Review the changelog and test results
4. Merge if everything passes

### Handling Dependabot PRs

**For minor/patch updates:**
- Usually safe to merge if CI passes
- Review the changelog for any breaking changes

**For major updates:**
- Read the migration guide carefully
- Test locally before merging
- May require code changes

To rebuild Dependabot PRs: Comment `@dependabot recreate`

## 🐳 Docker Development (Optional)

You can use Docker for development if you prefer containerized environments:

### Using Docker Compose

```bash
# Start services (Django admin on port 8000)
docker-compose up -d

# View logs
docker-compose logs -f app

# Run commands in container
docker-compose exec app turbovault --help

# Run Django migrations
docker-compose exec app sh -c "cd /app/backend && python manage.py migrate"

# Stop services
docker-compose down

# Stop and remove volumes (fresh start)
docker-compose down -v
```

### Building Docker Image Locally

```bash
# Build the image
docker build -t turbovault-dev .

# Run CLI commands
docker run turbovault-dev turbovault --version

# Run with volume mounts
docker run -v $(pwd)/output:/app/output turbovault-dev turbovault generate --project my_project
```

**Note:** Docker development is optional. Most contributors use the standard Python virtual environment setup.

## 🔄 Development Workflow

### Branching Strategy

We use a simplified Git Flow strategy:

- `main` - Production-ready code, protected branch
- `feature/description` - New features
- `bugfix/description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring

### Creating a New Feature

1. **Create a new branch from `main`:**
   ```bash
   git checkout main
   git pull origin main
   git checkout -b feature/my-new-feature
   ```

2. **Make your changes:**
   - Write code following our [coding standards](#coding-standards)
   - Add tests for new functionality
   - Update documentation as needed

3. **Run tests and checks locally:**
   ```bash
   # Format code
   black backend/

   # Lint code
   ruff check backend/

   # Type check (warnings are OK)
   mypy backend/engine backend/turbovault

   # Run tests
   python -m pytest backend/tests/ -v
   ```

4. **Commit your changes:**
   ```bash
   git add .
   git commit -m "feat: add new feature description"
   ```

5. **Push to your fork:**
   ```bash
   git push origin feature/my-new-feature
   ```

6. **Create a Pull Request** on GitHub

## 📐 Coding Standards

### Python Style

We follow the guidelines defined in `.agent/workflows/coding-guidelines.md`:

- **PEP 8** compliance (enforced by Black and Ruff)
- **Type hints** required for all public functions
- **Line length**: 88 characters (Black default)
- **Import order**: stdlib → third-party → local
- **Naming conventions**:
  - Files/modules: `snake_case`
  - Classes: `PascalCase`
  - Functions/variables: `snake_case`

### Django-Specific

- Keep business logic in **services**, not in models
- Use `transaction.atomic()` for multi-step database operations
- Minimize logic in management commands (call services instead)
- Follow the domain model defined in `docs/02_domain_model.md`

### Code Quality Tools

The project uses:

- **Black** - Code formatting (auto-applied)
- **Ruff** - Linting (must pass)
- **mypy** - Type checking (warnings only, non-blocking)

### Documentation

- Add docstrings to all public functions and classes
- Use type hints instead of documenting types in docstrings
- Update `README.md` for user-facing changes
- Update relevant docs in `docs/` for architectural changes

## 🧪 Testing

### Running Tests

```bash
# Run all tests
python -m pytest backend/tests/ -v

# Run specific test file
python -m pytest backend/tests/test_validators.py -v

# Run with coverage report
python -m pytest backend/tests/ --cov=engine.services.generation
```

### Writing Tests

- Place tests in `backend/tests/`
- Name test files `test_*.py`
- Name test functions `test_*`
- Use pytest fixtures defined in `conftest.py`
- Aim for meaningful test names that describe what is being tested

Example:
```python
def test_hub_validator_requires_hashkey():
    """Test that HubValidator fails when hashkey is missing."""
    # Arrange
    hub = Hub(name="test_hub", hashkey=None)
    
    # Act
    result = HubValidator.validate(hub)
    
    # Assert
    assert result.is_valid is False
    assert "HUB_001" in result.error_codes
```

## 🔀 Pull Request Process

1. **Ensure all checks pass:**
   - ✅ Code is formatted with Black
   - ✅ Ruff linting passes
   - ✅ All tests pass
   - ✅ No merge conflicts with `main`

2. **Fill out the PR template completely:**
   - Clear description of changes
   - Type of change selected
   - Testing details provided
   - Checklist completed

3. **Request review:**
   - At least 1 approval required
   - Address reviewer feedback promptly

4. **Squash and merge:**
   - We prefer squash merging to keep history clean
   - Ensure your PR title is descriptive (it becomes the commit message)

## 📝 Commit Messages

We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

### Format

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation only changes
- `style:` - Code style changes (formatting, no logic change)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks, dependency updates

### Examples

```bash
feat(cli): add new export command for JSON output
fix(generator): resolve template rendering issue for satellites
docs(readme): update installation instructions
test(validators): add tests for link validation rules
```

## 🐛 Reporting Bugs

When reporting bugs, please include:

1. **Description** - Clear description of the bug
2. **Steps to reproduce** - Minimal steps to reproduce the issue
3. **Expected behavior** - What you expected to happen
4. **Actual behavior** - What actually happened
5. **Environment** - Python version, OS, relevant package versions
6. **Logs/Screenshots** - Any relevant error messages or screenshots

## 💡 Requesting Features

When requesting features:

1. **Use case** - Describe the problem you're trying to solve
2. **Proposed solution** - Suggest how you'd like it to work
3. **Alternatives** - Any alternative solutions you've considered
4. **Additional context** - Any other relevant information

## 📞 Getting Help

- **Issues**: Create an issue on GitHub
- **Discussions**: Use GitHub Discussions for questions
- **Documentation**: Check the `docs/` folder

## 🙏 Thank You

Your contributions make TurboVault Engine better for everyone. We appreciate your time and effort!

---

**Questions?** Feel free to open an issue or start a discussion on GitHub.
