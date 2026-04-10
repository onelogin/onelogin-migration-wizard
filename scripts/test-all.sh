#!/bin/bash
set -e

echo "🧪 Running all tests..."
echo ""

FAILED=0

echo "Testing core..."
cd packages/core
if pytest tests/ -v; then
    echo "✅ Core tests passed"
else
    echo "❌ Core tests failed"
    FAILED=1
fi
cd ../..

echo ""
echo "Testing CLI..."
cd packages/cli
if pytest tests/ -v; then
    echo "✅ CLI tests passed"
else
    echo "❌ CLI tests failed"
    FAILED=1
fi
cd ../..

echo ""
echo "Testing GUI..."
cd packages/gui
if pytest tests/ -v; then
    echo "✅ GUI tests passed"
else
    echo "❌ GUI tests failed"
    FAILED=1
fi
cd ../..

echo ""
if [ $FAILED -eq 0 ]; then
    echo "✅ All tests passed!"
    exit 0
else
    echo "❌ Some tests failed"
    exit 1
fi
