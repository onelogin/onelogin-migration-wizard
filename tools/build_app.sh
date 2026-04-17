#!/bin/bash
# Build script for creating standalone executables
# Usage: ./build_app.sh

set -e

echo "======================================"
echo "OneLogin Migration Tool - App Builder"
echo "======================================"
echo ""

# Detect and use virtual environment
if [ -n "$VIRTUAL_ENV" ]; then
    echo "Using virtual environment: $VIRTUAL_ENV"
    PYTHON="$VIRTUAL_ENV/bin/python"
    PIP="$VIRTUAL_ENV/bin/pip"
elif [ -d ".venv" ]; then
    echo "Activating virtual environment: .venv"
    source .venv/bin/activate
    PYTHON="python"
    PIP="pip"
else
    echo "⚠️  Warning: No virtual environment detected. Using system Python."
    PYTHON="python3"
    PIP="pip3"
fi

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    PLATFORM="macOS"
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    PLATFORM="Windows"
else
    PLATFORM="Linux"
fi

echo "Platform detected: $PLATFORM"
echo ""

# Check if PyInstaller is installed
if ! command -v pyinstaller &> /dev/null; then
    echo "PyInstaller not found. Installing..."
    $PIP install pyinstaller
fi

# Install dependencies from monorepo packages
echo "Installing dependencies..."
echo "  1/4 Installing layered credentials package..."
$PIP install -q -e packages/layered_credentials
echo "  2/4 Installing core package..."
$PIP install -q -e packages/core
echo "  3/4 Installing CLI package..."
$PIP install -q -e packages/cli
echo "  4/4 Installing GUI package (with dev dependencies)..."
$PIP install -q -e "packages/gui[dev]"

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build dist "*.spec~"

# Build the application
echo "Building application..."
pyinstaller onelogin-migration-tool.spec

echo ""
echo "======================================"
echo "Build complete!"
echo "======================================"

if [[ "$PLATFORM" == "macOS" ]]; then
    echo ""
    echo "macOS App Bundle created:"
    echo "  dist/OneLogin Migration Tool.app"
    echo ""
    echo "To run: open 'dist/OneLogin Migration Tool.app'"
    echo ""
    echo "To sign for distribution (requires Apple Developer certificate):"
    echo "  codesign --deep --force --verify --verbose --sign 'Developer ID Application: Your Name' 'dist/OneLogin Migration Tool.app'"
    echo ""
    echo "To create a DMG:"
    echo "  hdiutil create -volname 'OneLogin Migration Tool' -srcfolder 'dist/OneLogin Migration Tool.app' -ov -format UDZO 'dist/OneLogin-Migration-Tool.dmg'"
elif [[ "$PLATFORM" == "Windows" ]]; then
    echo ""
    echo "Windows executable created:"
    echo "  dist/OneLogin Migration Tool.exe"
    echo ""
    echo "To create an installer, use Inno Setup or NSIS with the generated files."
else
    echo ""
    echo "Executable created in: dist/"
fi

echo ""
