# OneLogin Migration Core

Core migration engine for Okta to OneLogin migrations. This package provides the foundational library used by both the CLI and GUI interfaces.

## Features

- **API Clients** - Okta and OneLogin REST API wrappers with rate limiting
- **Migration Manager** - Orchestrates the complete migration workflow
- **Configuration** - YAML-based settings with validation
- **Credential Management** - Secure storage powered by the standalone `layered-credentials` package (keyring, Argon2 vault, audit logging)
- **Progress Tracking** - Real-time migration progress monitoring
- **State Management** - Resumable migrations with state persistence
- **Database** - SQLite-based connector catalog and telemetry
- **Security** - Database encryption, atomic writes, secure file permissions

## Installation

### For Development

```bash
cd packages/core
pip install -e ".[dev,test]"
```

### For Use in Other Projects

```bash
pip install -e packages/core
```

## Usage

### Basic Migration

```python
from onelogin_migration_core import MigrationManager, MigrationSettings

# Load settings from YAML
settings = MigrationSettings.from_file("config/migration.yaml")

# Create manager and run migration
manager = MigrationManager(settings)
export_data = manager.export_from_okta()
result = manager.import_into_onelogin(export_data)
```

### Using API Clients

```python
from onelogin_migration_core.clients import OktaClient, OneLoginClient
from onelogin_migration_core.config import OktaApiSettings, OneLoginApiSettings

# Okta client
okta_settings = OktaApiSettings(
    domain="example.okta.com",
    api_token="your-okta-token"
)
okta = OktaClient(okta_settings)
users = okta.get_all_users()

# OneLogin client
onelogin_settings = OneLoginApiSettings(
    region="us",
    client_id="your-client-id",
    client_secret="your-client-secret"
)
onelogin = OneLoginClient(onelogin_settings)
roles = onelogin.get_all_roles()
```

### Credential Management

```python
from onelogin_migration_core.credentials import (
    store_okta_credentials,
    store_onelogin_credentials,
    get_okta_credentials,
    get_onelogin_credentials
)

# Store credentials securely in system keyring
store_okta_credentials(domain="example.okta.com", token="your-token")
store_onelogin_credentials(
    region="us",
    client_id="your-id",
    client_secret="your-secret"
)

# Retrieve credentials
okta_creds = get_okta_credentials()
onelogin_creds = get_onelogin_credentials()
```

### Progress Tracking

```python
from onelogin_migration_core.progress import MigrationProgress

progress = MigrationProgress()

# Update progress
progress.update(
    phase="export",
    category="users",
    current=50,
    total=100,
    message="Exporting users..."
)

# Get snapshot
snapshot = progress.get_snapshot()
print(f"Overall: {snapshot.overall_percent}%")
```

## Package Structure

```
packages/core/
├── src/onelogin_migration_core/
│   ├── __init__.py              # Public API exports
│   ├── clients.py               # Okta/OneLogin API clients
│   ├── config.py                # Configuration models
│   ├── config_parser.py         # YAML config parser
│   ├── credentials.py           # Secure credential storage
│   ├── manager.py               # Migration orchestration
│   ├── progress.py              # Progress tracking
│   ├── state_manager.py         # State persistence
│   ├── secure_settings.py       # Secure configuration handling
│   ├── constants.py             # Shared constants
│   ├── custom_attributes.py     # Custom attribute provisioning
│   ├── csv_generator.py         # Bulk CSV generation
│   ├── exporters.py             # Data exporters
│   ├── importers.py             # Data importers
│   ├── transformers.py          # Data transformations
│   ├── db/                      # Database management
│   │   ├── __init__.py
│   │   ├── database_manager.py  # User data database
│   │   ├── connector_db.py      # Connector catalog
│   │   ├── db_security.py       # Database encryption
│   │   ├── encryption.py        # Encryption utilities
│   │   ├── telemetry.py         # Telemetry tracking
│   │   ├── connector_refresh.py # Catalog updates
│   │   └── load_connectors.py   # Connector loading
│   └── resources/               # Bundled resources
│       ├── catalog.db           # OneLogin connector catalog
│       └── user_data.db         # User data template
├── tests/                       # Test suite
│   ├── test_clients.py
│   ├── test_config.py
│   ├── test_migration.py
│   ├── test_progress.py
│   └── ...
├── pyproject.toml               # Package configuration
└── README.md                    # This file
```

## Development

### Setup

```bash
# Install with development dependencies
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

# Run specific test file
pytest tests/test_migration.py -v

# Run with coverage
pytest --cov=onelogin_migration_core --cov-report=html
```

### Running from Repository Root

If running tests or scripts from the repository root:

```bash
cd ../../  # Go to repo root
PYTHONPATH=packages/core/src pytest packages/core/tests/
```

## API Reference

### Public Exports

The package exports the following from `onelogin_migration_core`:

**Classes:**
- `MigrationManager` - Main migration orchestrator
- `MigrationSettings` - Configuration container
- `OktaClient` - Okta API client
- `OneLoginClient` - OneLogin API client
- `MigrationProgress` - Progress tracker
- `ProgressSnapshot` - Progress snapshot data

**Constants:**
- `__version__` - Package version (0.2.0)

## Dependencies

### Core Dependencies
- `requests>=2.31` - HTTP client
- `PyYAML>=6.0` - YAML parsing
- `pydantic>=2.0.0` - Data validation
- `argon2-cffi>=23.1.0` - Password hashing
- `cryptography>=42.0.0` - Encryption
- `keyring>=25.0.0` - Secure credential storage

### Development Dependencies
- `pytest>=7.4.0` - Testing framework
- `pytest-cov>=4.1.0` - Coverage reporting
- `pytest-mock>=3.11.1` - Mocking
- `black>=23.7.0` - Code formatting
- `ruff>=0.0.285` - Linting
- `isort>=5.12.0` - Import sorting

## Version

**Current Version:** 0.2.0

## License

See LICENSE file in repository root.

## Related Packages

- [onelogin-migration-cli](../cli/) - Command-line interface
- [onelogin-migration-gui](../gui/) - Graphical user interface
