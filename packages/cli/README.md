# OneLogin Migration CLI

Command-line interface for Okta to OneLogin migrations. Provides automation-friendly tools for running migrations, managing credentials, and database operations.

## Features

- **Migration Commands** - `plan`, `migrate`, `provision-attributes`
- **Credential Management** - Secure storage using system keyring
- **Database Commands** - Initialize, verify, and manage migration database
- **Telemetry** - View and manage anonymized usage analytics
- **Rich Output** - Colored terminal output with progress bars
- **Automation Ready** - Exit codes, JSON output, scriptable

## Installation

### For Development

```bash
cd packages/cli
pip install -e ".[dev,test]"
```

### Dependencies

This package requires `onelogin-migration-core` to be installed:

```bash
pip install -e packages/core
pip install -e packages/cli
```

## Usage

### Setting Up Environment

Due to current entry point limitations, use module invocation with `PYTHONPATH`:

```bash
# Set PYTHONPATH to include both CLI and core packages
export PYTHONPATH=packages/cli/src:packages/core/src

# Now run CLI commands
python -m onelogin_migration_cli.app --help
```

### Migration Commands

#### Plan - Export and Analyze

Export data from Okta without making changes to OneLogin:

```bash
python -m onelogin_migration_cli.app plan --config config/migration.yaml -v
```

**Options:**
- `--config PATH` - Path to migration config YAML
- `-v, --verbose` - Enable debug logging
- `--output PATH` - Custom output path for export

#### Migrate - Full Migration

Execute the complete migration workflow:

```bash
python -m onelogin_migration_cli.app migrate --config config/migration.yaml -v
```

**Options:**
- `--config PATH` - Path to migration config YAML
- `--dry-run` - Simulate migration without writes
- `--bulk-user-upload` - Generate OneLogin CSV instead of API calls
- `--export PATH` - Use pre-generated Okta export JSON
- `-v, --verbose` - Enable debug logging

#### Provision Attributes - Pre-create Custom Attributes

Create custom attributes in OneLogin before migration:

```bash
# Preview attributes
python -m onelogin_migration_cli.app provision-attributes \
    --config config/migration.yaml --dry-run

# Create attributes
python -m onelogin_migration_cli.app provision-attributes \
    --config config/migration.yaml
```

### Credential Management

Securely store and manage API credentials:

```bash
# Set Okta credentials
python -m onelogin_migration_cli.app credentials set-okta

# Set OneLogin credentials
python -m onelogin_migration_cli.app credentials set-onelogin

# Test credentials
python -m onelogin_migration_cli.app credentials test

# View stored credentials (masked)
python -m onelogin_migration_cli.app credentials show

# Clear credentials
python -m onelogin_migration_cli.app credentials clear
```

### Database Commands

Manage the migration database:

```bash
# Initialize database
python -m onelogin_migration_cli.app db init

# Verify database integrity
python -m onelogin_migration_cli.app db verify

# Check security
python -m onelogin_migration_cli.app db check-security

# Repair permissions
python -m onelogin_migration_cli.app db fix-permissions
```

### Telemetry

View and manage anonymized usage analytics:

```bash
# Show telemetry data
python -m onelogin_migration_cli.app telemetry show

# Clear telemetry
python -m onelogin_migration_cli.app telemetry clear

# Show specific migration
python -m onelogin_migration_cli.app telemetry show --migration-id abc123
```

### Configuration

View current configuration:

```bash
python -m onelogin_migration_cli.app show-config --config config/migration.yaml
```

## Configuration File

Create a `migration.yaml` file (see `config/migration.template.yaml`):

```yaml
okta:
  domain: "example.okta.com"
  # api_token stored in keyring

onelogin:
  region: "us"  # or "eu"
  # client_id and client_secret stored in keyring

migration:
  dry_run: true
  export_directory: "artifacts"
  categories:
    - users
    - groups
    - apps
  concurrency:
    max_workers: 5
    rate_limit: 10
```

## Package Structure

```
packages/cli/
├── src/onelogin_migration_cli/
│   ├── __init__.py          # Package info
│   ├── app.py               # Main CLI app (Typer)
│   ├── credentials.py       # Credential commands
│   ├── database.py          # Database commands
│   └── telemetry.py         # Telemetry commands
├── tests/
│   ├── test_cli_entrypoint.py
│   ├── test_clients.py
│   └── test_credentials_cli.py
├── pyproject.toml           # Package configuration
└── README.md                # This file
```

## Development

### Setup

```bash
# Install with development dependencies
cd packages/cli
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
pytest tests/test_cli_entrypoint.py -v

# Run with coverage
pytest --cov=onelogin_migration_cli --cov-report=html
```

### Running from Repository Root

If running from the repository root:

```bash
export PYTHONPATH=packages/cli/src:packages/core/src
python -m onelogin_migration_cli.app --help
```

## Command Reference

### Global Options

All commands support:
- `--help` - Show help message
- `-v, --verbose` - Enable verbose logging

### Exit Codes

- `0` - Success
- `1` - General error
- `2` - Configuration error
- `3` - API error
- `4` - Validation error

## Examples

### Complete Migration Workflow

```bash
# Set PYTHONPATH
export PYTHONPATH=packages/cli/src:packages/core/src

# 1. Store credentials
python -m onelogin_migration_cli.app credentials set-okta
python -m onelogin_migration_cli.app credentials set-onelogin

# 2. Test credentials
python -m onelogin_migration_cli.app credentials test

# 3. Export and analyze
python -m onelogin_migration_cli.app plan --config config/migration.yaml -v

# 4. Preview custom attributes
python -m onelogin_migration_cli.app provision-attributes \
    --config config/migration.yaml --dry-run

# 5. Create custom attributes
python -m onelogin_migration_cli.app provision-attributes \
    --config config/migration.yaml

# 6. Run migration (dry-run first)
python -m onelogin_migration_cli.app migrate \
    --config config/migration.yaml --dry-run -v

# 7. Run actual migration
python -m onelogin_migration_cli.app migrate \
    --config config/migration.yaml -v
```

### Automation Script

```bash
#!/bin/bash
set -e

export PYTHONPATH=packages/cli/src:packages/core/src
CLI="python -m onelogin_migration_cli.app"

echo "Running Okta export..."
$CLI plan --config prod.yaml

echo "Provisioning custom attributes..."
$CLI provision-attributes --config prod.yaml

echo "Running migration..."
$CLI migrate --config prod.yaml

echo "Migration complete!"
```

## Dependencies

### Core Dependencies
- `onelogin-migration-core==0.2.0` - Core migration library
- `typer>=0.9` - CLI framework
- `rich>=13.7` - Rich terminal output

### Development Dependencies
- `pytest>=7.4.0` - Testing framework
- `pytest-cov>=4.1.0` - Coverage reporting
- `pytest-mock>=3.11.1` - Mocking
- `black>=23.7.0` - Code formatting
- `ruff>=0.0.285` - Linting

## Known Issues

### Entry Point Not Working

The `onelogin-migration` entry point currently doesn't work due to .pth file issues. Use the workaround:

```bash
# Instead of: onelogin-migration plan
# Use: python -m onelogin_migration_cli.app plan
export PYTHONPATH=packages/cli/src:packages/core/src
python -m onelogin_migration_cli.app plan --config config.yaml
```

## Version

**Current Version:** 0.2.0

## License

See LICENSE file in repository root.

## Related Packages

- [onelogin-migration-core](../core/) - Core migration library
- [onelogin-migration-gui](../gui/) - Graphical user interface
