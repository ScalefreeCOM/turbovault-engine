#!/usr/bin/env bash
# Developer Environment Setup Script for TurboVault Engine (Linux/Mac)

set -e  # Exit on error

echo "🚀 Setting up TurboVault Engine development environment..."
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found. Please install Python 3.12+ first."
    exit 1
fi

PYTHON_VERSION=$(python3 --version)
echo "✅ Python found: $PYTHON_VERSION"

# Check if we're in a virtual environment (recommended)
if [[ -n "$VIRTUAL_ENV" ]]; then
    echo "✅ Virtual environment active: $VIRTUAL_ENV"
else
    echo "⚠️  No virtual environment detected. It's recommended to use one."
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Setup cancelled. Create a venv with: python3 -m venv venv"
        exit 0
    fi
fi

echo ""
echo "📦 Installing development dependencies..."
python3 -m pip install --upgrade pip
pip install -e ".[dev]"
echo "✅ Dependencies installed"
echo ""

# Install pre-commit hooks
echo "🔧 Installing pre-commit hooks..."
pre-commit install
echo "✅ Pre-commit hooks installed"
echo ""

# Run Django migrations
echo "🗄️  Running Django migrations..."
cd backend
if python3 manage.py migrate --noinput; then
    echo "✅ Database migrated"
else
    echo "⚠️  Migration failed, but setup continues"
fi
cd ..

echo ""
echo "✨ Development environment setup complete!"
echo ""
echo "Next steps:"
echo "  1. Run tests:           python3 -m pytest backend/tests/ -v"
echo "  2. Start Django admin:  turbovault serve"
echo "  3. Format code:         black backend/"
echo "  4. Check linting:       ruff check backend/"
echo ""
echo "Pre-commit hooks are now active! 🎉"
echo "They will run automatically on every commit."
echo ""
