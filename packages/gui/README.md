# OneLogin Migration GUI

Graphical wizard interface for Okta to OneLogin migrations. Provides a step-by-step wizard with real-time feedback, perfect for interactive migrations.

## Features

- **Step-by-Step Wizard** - Guided migration workflow with 7 steps
- **Real-Time Progress** - Live progress bars and log streaming
- **Connection Testing** - Validate API credentials before migrating
- **Field Validation** - Live validation of all configuration inputs
- **Analysis Dialog** - Detailed Okta environment analysis with export capabilities
- **Dark/Light Theme** - Automatic theme switching based on system preferences
- **Resumable** - Save state and resume migrations
- **Safe** - Dry-run mode, confirmation dialogs, nothing runs until you click "Start"

## Installation

### For Development

```bash
cd packages/gui
pip install -e ".[dev,test]"
```

### Dependencies

This package requires `onelogin-migration-core` to be installed:

```bash
pip install -e packages/core
pip install -e packages/gui
```

### macOS Sequoia (Python 3.13) compatibility

Qt 6.9.x (and early 6.8.x builds) currently ship a broken `qcocoa` platform plugin on macOS 15 (Sequoia) when used with Python 3.13, which causes the GUI to abort on startup with `Could not find the Qt platform plugin "cocoa"`. The package is therefore pinned to PySide6 6.8.3. If you previously installed a different build, reinstall the GUI package after upgrading:

```bash
pip install --upgrade --force-reinstall "PySide6==6.8.3" "PySide6-Essentials==6.8.3" "PySide6-Addons==6.8.3"
```

## Usage

### Launching the GUI

Due to current entry point limitations, use module invocation with `PYTHONPATH`:

```bash
# Set PYTHONPATH to include both GUI and core packages
export PYTHONPATH=packages/gui/src:packages/core/src

# Launch GUI
python -m onelogin_migration_gui.main
```

### GUI Workflow

1. **Welcome** - Introduction and migration overview
2. **Source (Okta)** - Enter Okta domain and API token, test connection
3. **Target (OneLogin)** - Enter OneLogin region and credentials, test connection
4. **Options** - Configure dry-run mode, concurrency, export format
5. **Objects** - Select what to migrate (users, groups, apps, policies)
6. **Analysis** - (Optional) Analyze Okta environment before migrating
7. **Summary** - Review all settings before starting
8. **Progress** - Watch real-time progress with detailed logs

### Features

#### Connection Testing
- Test Okta connection before proceeding
- Test OneLogin connection before proceeding
- Visual feedback on success/failure

#### Analysis Dialog
Detailed analysis of your Okta environment:
- User counts and attributes
- Group counts and memberships
- Application counts and types
- Custom attribute analysis
- OneLogin connector matching
- Export to CSV/XLSX

#### Progress Tracking
- Real-time progress bars for each category
- Streaming logs with timestamps
- Abort button to stop migration safely
- Success/error summary

#### Safety Controls
- Dry-run mode enabled by default
- Confirmation dialogs before destructive operations
- Nothing runs until you click "Start Migration"
- Abort anytime during migration

## Package Structure

```
packages/gui/
├── src/onelogin_migration_gui/
│   ├── __init__.py              # Package exports
│   ├── main.py                  # GUI entry point
│   ├── components.py            # Reusable UI components
│   ├── theme_manager.py         # Dark/light theme management
│   ├── helpers.py               # Utility functions
│   ├── steps/                   # Wizard steps
│   │   ├── __init__.py
│   │   ├── base.py             # Base wizard step
│   │   ├── welcome.py          # Welcome step
│   │   ├── source.py           # Okta configuration
│   │   ├── target.py           # OneLogin configuration
│   │   ├── provider.py         # Provider selection
│   │   ├── options.py          # Migration options
│   │   ├── objects.py          # Object selection
│   │   ├── analysis.py         # Analysis step
│   │   ├── summary.py          # Summary review
│   │   └── progress.py         # Progress tracking
│   ├── dialogs/                 # Dialog windows
│   │   ├── __init__.py
│   │   └── analysis_detail/    # Detailed analysis dialog
│   │       ├── dialog.py       # Main dialog
│   │       ├── tables/         # Data tables
│   │       ├── export/         # Export functionality
│   │       └── utils/          # Utilities
│   ├── styles/                  # Style definitions
│   │   ├── __init__.py
│   │   └── button_styles.py    # Button styles
│   └── assets/                  # Images and resources
│       ├── Onelogin_Logotype_black_RGB.png.webp
│       └── Onelogin_Logotype_white_RGB.png.webp
├── tests/
│   ├── test_gui_credentials.py
│   └── test_gui_state.py
├── pyproject.toml               # Package configuration
└── README.md                    # This file
```

## Development

### Setup

```bash
# Install with development dependencies
cd packages/gui
pip install -e ".[dev,test]"
```

### Code Quality

```bash
# Format code
black src/ tests/
isort src/ tests/

# Lint
ruff check src/ tests/

# Fix auto-fixable issues
ruff check --fix src/ tests/
```

### Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test
pytest tests/test_gui_state.py -v

# Run with coverage
pytest --cov=onelogin_migration_gui --cov-report=html
```

### Running from Repository Root

If running from the repository root:

```bash
export PYTHONPATH=packages/gui/src:packages/core/src
python -m onelogin_migration_gui.main
```

## Building Standalone App

Build a standalone application using PyInstaller:

### Prerequisites

```bash
pip install pyinstaller
```

### Build Script

The project includes build scripts for creating standalone executables:

```bash
# macOS/Linux
./tools/build_app.sh

# Windows
tools\build_app.bat
```

**Note:** Build scripts may need updating for the new monorepo structure.

### Manual Build

```bash
# Update PyInstaller spec file paths first
# Then build:
pyinstaller onelogin-migration-tool.spec

# Output is in dist/
```

## UI Components

### ModernButton
Styled buttons with hover effects:
```python
from onelogin_migration_gui.components import ModernButton

button = ModernButton("Click Me", style="primary")
button.clicked.connect(on_click)
```

### ModernCard
Styled containers with shadows:
```python
from onelogin_migration_gui.components import ModernCard

card = ModernCard()
layout = QVBoxLayout(card)
layout.addWidget(QLabel("Content"))
```

### ModernCheckbox
Styled checkboxes:
```python
from onelogin_migration_gui.components import ModernCheckbox

checkbox = ModernCheckbox("Enable feature")
```

## Theme Management

The GUI automatically switches between light and dark themes based on system preferences:

```python
from onelogin_migration_gui.theme_manager import get_theme_manager

theme = get_theme_manager()
colors = theme.get_colors()
primary = theme.get_color("primary")
```

## Configuration

The GUI stores its state in a JSON file for resumability:

```
~/.onelogin-migration/gui_state.json
```

State includes:
- Wizard step position
- Form field values (except credentials)
- Analysis results cache
- Window geometry

## Dependencies

### Core Dependencies
- `onelogin-migration-core==0.2.0` - Core migration library
- `PySide6>=6.6,<6.9` - Qt framework for Python

### Development Dependencies
- `pytest>=7.4.0` - Testing framework
- `pytest-qt>=4.2.0` - Qt testing
- `pytest-cov>=4.1.0` - Coverage reporting
- `black>=23.7.0` - Code formatting
- `ruff>=0.0.285` - Linting

### Build Dependencies
- `pyinstaller>=6.0` - Standalone app builder

## Known Issues

### Entry Point Not Working

The `onelogin-migration-gui` entry point currently doesn't work due to .pth file issues. Use the workaround:

```bash
# Instead of: onelogin-migration-gui
# Use: python -m onelogin_migration_gui.main
export PYTHONPATH=packages/gui/src:packages/core/src
python -m onelogin_migration_gui.main
```

### PySide6 Version Warning

If you see a version warning about PySide6 6.10.0 vs <6.9 requirement, the GUI still works correctly. The version constraint is being updated to accept newer versions.

## Screenshots

### Welcome Step
- Introduction to the migration wizard
- Overview of the migration process

### Source/Target Steps
- Credential input with validation
- Connection testing with visual feedback
- Real-time error messages

### Analysis Step
- Detailed Okta environment analysis
- Exportable data tables
- Connector matching suggestions

### Progress Step
- Real-time progress bars
- Streaming logs with filtering
- Abort button
- Success/error summary

## Version

**Current Version:** 0.2.0

## License

See LICENSE file in repository root.

## Related Packages

- [onelogin-migration-core](../core/) - Core migration library
- [onelogin-migration-cli](../cli/) - Command-line interface
