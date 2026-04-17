#!/bin/bash
set -e

echo "🔍 Linting all packages (PEP 8)..."
echo ""

FAILED=0

for pkg in core cli gui; do
    echo "Linting $pkg..."
    cd packages/$pkg

    echo "  - isort (import sorting)"
    if ! isort --check-only src/ tests/; then
        echo "    ❌ isort check failed"
        FAILED=1
    fi

    echo "  - black (code formatting)"
    if ! black --check src/ tests/; then
        echo "    ❌ black check failed"
        FAILED=1
    fi

    echo "  - ruff (linting)"
    if ! ruff check src/ tests/; then
        echo "    ❌ ruff check failed"
        FAILED=1
    fi

    cd ../..
    echo ""
done

if [ $FAILED -eq 0 ]; then
    echo "✅ All packages are PEP 8 compliant!"
    exit 0
else
    echo "❌ Some linting checks failed"
    echo ""
    echo "To fix automatically, run: ./scripts/format-all.sh"
    exit 1
fi
