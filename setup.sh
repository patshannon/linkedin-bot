#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# setup.sh — Create venv, install dependencies, and activate
#
# Usage:
#   source setup.sh        (creates venv + activates in current shell)
#   ./setup.sh             (creates venv but activation won't persist)
# ──────────────────────────────────────────────────────────────────

set -e

VENV_DIR=".venv"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment in $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
else
    echo "✅ Virtual environment already exists at $VENV_DIR"
fi

# Activate the virtual environment
echo "🔌 Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip --quiet

# Install dependencies
echo "📥 Installing dependencies from requirements.txt..."
pip install -r requirements.txt --quiet

# Install Playwright browsers
echo "🌐 Installing Playwright Chromium browser..."
python -m playwright install chromium

echo ""
echo "══════════════════════════════════════════════════════"
echo "  ✅ Setup complete!"
echo "  Python: $(python --version)"
echo "  Venv:   $VIRTUAL_ENV"
echo ""
echo "  Run the scraper:   python scraper.py"
echo "  Run the matcher:   python matcher.py"
echo "══════════════════════════════════════════════════════"
