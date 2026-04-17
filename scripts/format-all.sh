#!/bin/bash
set -e

echo "🎨 Formatting all packages (PEP 8)..."
echo ""

for pkg in core cli gui; do
    echo "Formatting $pkg..."
    cd packages/$pkg

    isort src/ tests/
    black src/ tests/
    ruff check --fix src/ tests/ || true

    cd ../..
done

echo ""
echo "✅ All packages formatted!"
echo ""
echo "Run './scripts/lint-all.sh' to verify."
