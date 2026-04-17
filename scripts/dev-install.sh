#!/bin/bash
set -e

echo "🔧 OneLogin Migration Toolkit - Development Setup"
echo "=================================================="

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "❌ Error: Could not find a Python interpreter (tried \$PYTHON_BIN, python3, python)"
    exit 1
fi
PYTHON_BIN="$(command -v "$PYTHON_BIN")"
case "$PYTHON_BIN" in
    /*) ;;
    *)
        PYTHON_BIN="$(pwd)/$PYTHON_BIN"
        ;;
esac

# Check we're in project root
if [ ! -d "packages/core" ]; then
    echo "❌ Error: Run this script from the project root"
    exit 1
fi

# Install in order (core first, others depend on it)
echo ""
echo "1/3 Installing core..."
cd packages/core && "$PYTHON_BIN" -m pip install -q -e ".[test,dev]" && cd ../..

echo "2/3 Installing CLI..."
cd packages/cli && "$PYTHON_BIN" -m pip install -q -e ".[test,dev]" && cd ../..

echo "3/3 Installing GUI..."
cd packages/gui && "$PYTHON_BIN" -m pip install -q -e ".[dev,test]" && cd ../..

# Ensure editable packages stay importable on Python 3.13+ (macOS hides .pth files)
"$PYTHON_BIN" - <<'PY'
import os
import stat
import sysconfig
from pathlib import Path

root = Path.cwd()
site_packages = Path(sysconfig.get_paths()["purelib"])


def clear_hidden_flag(path: Path) -> None:
    hidden_flag = getattr(stat, "UF_HIDDEN", None)
    if not hidden_flag:
        return
    chflags = getattr(os, "chflags", None)
    if not chflags:
        return
    try:
        flags = os.stat(path).st_flags
    except (FileNotFoundError, OSError):
        return
    if not flags & hidden_flag:
        return
    try:
        chflags(path, flags & ~hidden_flag)
    except (PermissionError, OSError):
        pass
paths = {
    "onelogin_migration_core_dev.pth": root / "packages/core/src",
    "onelogin_migration_cli_dev.pth": root / "packages/cli/src",
    "onelogin_migration_gui_dev.pth": root / "packages/gui/src",
}

written = []
for filename, target in paths.items():
    if not target.exists():
        continue
    path = site_packages / filename
    path.write_text(str(target.resolve()) + "\n")
    clear_hidden_flag(path)
    written.append(path)

usercustomize_path = site_packages / "usercustomize.py"
marker = "# OneLogin dev-install path helper"
snippet = "\n".join(
    [
        marker,
        "import sys",
        "from pathlib import Path",
        "",
        "def _find_repo_root():",
        "    for candidate in Path(__file__).resolve().parents:",
        "        if (candidate / 'packages' / 'core' / 'src').exists():",
        "            return candidate",
        "    return None",
        "",
        "def _add_path(path: Path) -> None:",
        "    path_str = str(path)",
        "    if path.exists() and path_str not in sys.path:",
        "        sys.path.insert(0, path_str)",
        "",
        "_REPO_ROOT = _find_repo_root()",
        "if _REPO_ROOT:",
        "    for parts in [",
        "        ('packages', 'core', 'src'),",
        "        ('packages', 'cli', 'src'),",
        "        ('packages', 'gui', 'src'),",
        "    ]:",
        "        _add_path(_REPO_ROOT.joinpath(*parts))",
        "",
    ]
)

if usercustomize_path.exists():
    existing = usercustomize_path.read_text()
else:
    existing = ""

if marker not in existing:
    if existing.strip():
        content = f"{existing.rstrip()}\n\n{snippet}\n"
    else:
        content = f"{snippet}\n"
    usercustomize_path.write_text(content)
    clear_hidden_flag(usercustomize_path)
    usercustomize_written = True
else:
    usercustomize_written = False

helper_pth = site_packages / "zz_onelogin_macos_unhide.pth"
sitecustomize_src = root / "sitecustomize.py"
helper_written = False
if sitecustomize_src.exists():
    helper_code = f"import runpy as _runpy; _runpy.run_path({repr(str(sitecustomize_src.resolve()))}); del _runpy\n"
    try:
        helper_pth.write_text(helper_code, encoding="utf-8")
        clear_hidden_flag(helper_pth)
        helper_written = True
    except OSError:
        helper_written = False

symlink_targets = {
    "onelogin_migration_core": root / "packages/core/src/onelogin_migration_core",
    "onelogin_migration_cli": root / "packages/cli/src/onelogin_migration_cli",
    "onelogin_migration_gui": root / "packages/gui/src/onelogin_migration_gui",
}
symlinks_created = []
for name, target in symlink_targets.items():
    link_path = site_packages / name
    if not target.exists():
        continue
    if link_path.exists() or link_path.is_symlink():
        continue
    try:
        os.symlink(target, link_path)
        symlinks_created.append(link_path)
    except OSError:
        pass

if written:
    clear_hidden_flag(site_packages)
    print("\nDetected editable installs; added helper .pth files to keep them on sys.path:")
    for path in written:
        print(f"  - {path}")

if usercustomize_written:
    print("\nEnsured usercustomize.py injects package src folders onto sys.path.")
elif usercustomize_path.exists():
    print("\nusercustomize.py already contains the OneLogin dev-install helper.")

if helper_written:
    print("\nAdded zz_onelogin_macos_unhide.pth to proactively remove macOS hidden flags.")
elif helper_pth.exists():
    print("\nzz_onelogin_macos_unhide.pth already present; skipped rewiring.")

if symlinks_created:
    print("\nCreated symlinks in site-packages to keep editable packages importable:")
    for path in symlinks_created:
        print(f"  - {path} -> {os.readlink(path)}")
PY

echo ""
echo "✅ Development environment ready!"
echo ""
echo "Verify:"
echo "  $PYTHON_BIN -c 'import onelogin_migration_core; print(\"Core:\", onelogin_migration_core.__version__)'"
echo "  $PYTHON_BIN -c 'import onelogin_migration_cli; print(\"CLI:\", onelogin_migration_cli.__version__)'"
echo "  $PYTHON_BIN -c 'import onelogin_migration_gui; print(\"GUI:\", onelogin_migration_gui.__version__)'"
