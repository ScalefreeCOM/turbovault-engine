#!/usr/bin/env pwsh
# Developer Environment Setup Script for TurboVault Engine (Windows/PowerShell)

Write-Host "🚀 Setting up TurboVault Engine development environment..." -ForegroundColor Cyan
Write-Host ""

# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    Write-Host "✅ Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Python not found. Please install Python 3.12+ first." -ForegroundColor Red
    exit 1
}

# Check if we're in a virtual environment (recommended)
if ($env:VIRTUAL_ENV) {
    Write-Host "✅ Virtual environment active: $env:VIRTUAL_ENV" -ForegroundColor Green
} else {
    Write-Host "⚠️  No virtual environment detected. It's recommended to use one." -ForegroundColor Yellow
    $response = Read-Host "Continue anyway? (y/N)"
    if ($response -ne 'y' -and $response -ne 'Y') {
        Write-Host "Setup cancelled. Create a venv with: python -m venv venv" -ForegroundColor Yellow
        exit 0
    }
}

Write-Host ""
Write-Host "📦 Installing development dependencies..." -ForegroundColor Cyan
python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to upgrade pip" -ForegroundColor Red
    exit 1
}

pip install -e ".[dev]"
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to install dependencies" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Dependencies installed" -ForegroundColor Green
Write-Host ""

# Install pre-commit hooks
Write-Host "🔧 Installing pre-commit hooks..." -ForegroundColor Cyan
pre-commit install
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to install pre-commit hooks" -ForegroundColor Red
    exit 1
}

Write-Host "✅ Pre-commit hooks installed" -ForegroundColor Green
Write-Host ""

# Run Django migrations
Write-Host "🗄️  Running Django migrations..." -ForegroundColor Cyan
Push-Location backend
python manage.py migrate --noinput
$migrateResult = $LASTEXITCODE
Pop-Location

if ($migrateResult -ne 0) {
    Write-Host "⚠️  Migration failed, but setup continues" -ForegroundColor Yellow
} else {
    Write-Host "✅ Database migrated" -ForegroundColor Green
}

Write-Host ""
Write-Host "✨ Development environment setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Run tests:           python -m pytest backend/tests/ -v"
Write-Host "  2. Start Django admin:  turbovault serve"
Write-Host "  3. Format code:         black backend/"
Write-Host "  4. Check linting:       ruff check backend/"
Write-Host ""
Write-Host "Pre-commit hooks are now active! 🎉" -ForegroundColor Green
Write-Host "They will run automatically on every commit." -ForegroundColor Gray
Write-Host ""
