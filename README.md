# OneLogin Migration Wizard

A production-ready Python toolkit for migrating identity data from a source identity provider into OneLogin:

- **Multi-provider**: Pluggable source provider architecture — Okta supported out of the box, straightforward to extend
- **Multi-interface**: CLI for automation, GUI wizard for interactive migrations
- **Safe by default**: Dry-run mode, field validation, resumable migrations with state persistence
- **Concurrent processing**: Thread-safe with automatic rate limiting and backoff
- **Flexible data export**: JSON snapshots or OneLogin bulk CSV format
- **Smart field mapping**: Automatic custom attribute creation and normalization

## Table of Contents

- [Quick Start](#quick-start)
- [Commands](#commands)
- [Configuration](#configuration)
- [Secure Credential Management](#secure-credential-management)
- [GUI Features](#gui-features)
- [Field Mapping](#field-mapping-and-onelogin-validation)
- [Performance](#rate-limits-and-performance)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## Quick Start

### Installation

This project uses a monorepo structure with three packages:
- **core** - Core migration library
- **cli** - Command-line interface
- **gui** - Graphical user interface

1. **Create and activate a virtual environment** (macOS/Linux):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install packages** using the development setup script:
   ```bash
   # Install all packages (recommended for development)
   ./scripts/dev-install.sh

   # Or install individually:
   pip install -e packages/core
   pip install -e packages/cli
   pip install -e packages/gui
   ```

3. **Verify installation**:
   ```bash
   python -m onelogin_migration_cli.app --help
   ```

**Note**: Credentials are stored securely in your system keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service) instead of configuration files. See [Secure Credential Management](#secure-credential-management) for details.

### Quick Migration

```bash
# Set PYTHONPATH for package discovery
export PYTHONPATH=packages/cli/src:packages/core/src

# 1. Store credentials securely (done once)
python -m onelogin_migration_cli.app credentials set source token
python -m onelogin_migration_cli.app credentials set onelogin client_secret

# 2. Test export from source provider (safe, read-only)
python -m onelogin_migration_cli.app plan --config config/migration.yaml

# 3. Preview custom attributes to create
python -m onelogin_migration_cli.app provision-attributes --config config/migration.yaml --dry-run

# 4. Pre-create custom attributes in OneLogin
python -m onelogin_migration_cli.app provision-attributes --config config/migration.yaml

# 5. Run migration (dry-run mode by default)
python -m onelogin_migration_cli.app migrate --config config/migration.yaml

# Or use the GUI wizard
export PYTHONPATH=packages/gui/src:packages/core/src
python -m onelogin_migration_gui.main
```

## Commands

All commands use the CLI module. Set `PYTHONPATH` first:
```bash
export PYTHONPATH=packages/cli/src:packages/core/src
```

### `plan` - Export and Preview

Export data from your source provider without making any changes to OneLogin. Perfect for auditing and planning.

```bash
python -m onelogin_migration_cli.app plan --config config/migration.yaml -v
```

**What it does:**
- Exports users, groups, memberships, and applications from your source provider
- Saves `source_export.json` in the configured export directory
- Creates timestamped snapshots: `{source}_{category}_{timestamp}.json`
- No writes to OneLogin (safe for exploration)

**Options:**
- `-v, --verbose` - Enable debug logging
- `--output PATH` - Custom output path for export

---

### `migrate` - Full Migration

Execute the complete migration workflow with safety controls.

```bash
python -m onelogin_migration_cli.app migrate --config config/migration.yaml -v
```

**What it does:**
1. Exports all data from source provider (if not provided)
2. Cleans up existing OneLogin roles (except defaults)
3. Creates roles (groups), users, and applications in OneLogin
4. Assigns users to roles and roles to applications

**Options:**
- `--dry-run` - Simulate migration without writes (overrides config)
- `--bulk-user-upload` - Generate OneLogin CSV instead of API calls
- `--export PATH` - Use pre-generated source export JSON
- `-v, --verbose` - Enable debug logging

**Safety features:**
- Honors `dry_run` setting from config
- State persistence for resume capability
- Automatic rate limiting and retry logic
- Account owner protection

---

### `gui` - Interactive Wizard

Launch a graphical wizard with step-by-step guidance and real-time progress monitoring.

```bash
python -m onelogin_migration_gui.main --config config/migration.yaml
```

**Features:**
- Connection testing for source provider and OneLogin
- Live settings editor with validation
- Category selection (users, groups, apps, policies)
- Real-time progress bars and log streaming
- Bulk CSV export option

---

### `show-config` - Debug Configuration

Display the current configuration with secrets masked for troubleshooting.

```bash
python -m onelogin_migration_cli.app show-config --config config/migration.yaml
```

---

### `provision-attributes` - Pre-create Custom Attributes

Analyze source provider user profiles and automatically create all necessary custom attributes in OneLogin before migration.

```bash
python -m onelogin_migration_cli.app provision-attributes --config config/migration.yaml
```

**What it does:**
1. Exports users from source provider (or uses existing export)
2. Analyzes all user profile fields across all users
3. Identifies which fields become custom attributes
4. Creates those custom attributes in OneLogin with proper naming

**Use cases:**
- Preview custom attributes before migration
- Pre-provision attributes for bulk CSV import
- Troubleshoot attribute mapping issues
- Verify attribute normalization (camelCase → snake_case)

**Options:**
- `--export PATH` - Use pre-generated source export instead of fetching
- `--dry-run` - Preview attributes without creating them
- `-v, --verbose` - Show detailed attribute analysis

**Example workflow:**
```bash
# Preview what attributes would be created
python -m onelogin_migration_cli.app provision-attributes --config config/migration.yaml --dry-run

# Create the attributes in OneLogin
python -m onelogin_migration_cli.app provision-attributes --config config/migration.yaml

# Use with existing export
python -m onelogin_migration_cli.app plan --config config/migration.yaml --output source_export.json
python -m onelogin_migration_cli.app provision-attributes --config config/migration.yaml --export source_export.json
```

**Output example:**
```
Analyzing 1,247 users for custom attributes...

Discovered 15 custom attributes:
    1. city
    2. country_code
    3. display_name
    4. employee_number
    5. manager_email
    6. second_email
    7. state
    8. street_address
    9. zip_code
   10. cost_center
   ...

Provisioning 15 attributes in OneLogin...
✓ Created 12 new attributes
ℹ 3 attributes already exist
```

## Configuration

### Configuration File

Create `config/migration.yaml` from the template:

```bash
cp config/migration.template.yaml config/migration.yaml
```

```yaml
# Migration behavior
dry_run: true                    # Safe mode - no writes to OneLogin
chunk_size: 200                  # Items per batch
export_directory: artifacts      # Where to save exports
concurrency_enabled: false       # Enable multi-threading
max_workers: 4                   # Worker threads (auto-calculated if omitted)
bulk_user_upload: false          # Generate CSV instead of API calls
pass_app_parameters: true        # Extract and pass app parameters during migration

# Source provider configuration (Okta)
okta:
  domain: your-org.okta.com             # Your Okta domain
  token: YOUR_OKTA_API_TOKEN            # Admin API token
  rate_limit_per_minute: 600            # API rate limit
  page_size: 200                        # Items per page

# OneLogin target configuration
onelogin:
  client_id: YOUR_ONELOGIN_CLIENT_ID        # OAuth client ID
  client_secret: YOUR_ONELOGIN_CLIENT_SECRET # OAuth client secret
  region: us                                 # us or eu
  subdomain: your-company                    # Tenant subdomain
  rate_limit_per_hour: 5000                 # API rate limit

# Optional: Migration categories
categories:
  users: true
  groups: true
  applications: true
  policies: false

# Optional: Application connector mappings
metadata:
  application_connectors:
    "slack":
      "saml": 123456
    "github":
      "openid": 789012
```

### Required Settings

**Source provider (Okta):**
- `domain` - Your source domain (e.g., `company.okta.com`)
- `token` - Admin API token

**OneLogin:**
- `client_id` / `client_secret` - OAuth credentials from OneLogin Admin → Developers → API Credentials
- `region` - `us` or `eu` (determines token endpoint: `https://api.{region}.onelogin.com`)
- `subdomain` - Tenant subdomain (e.g., `company` for `company.onelogin.com`)

### Optional Settings

**Performance:**
- `max_workers` - If omitted, auto-calculated based on rate limits (recommended)
- `concurrency_enabled` - Enable thread-based parallelism

**Output:**
- `export_directory` - Where to save JSON exports and CSVs (default: `artifacts/`)
- `bulk_user_upload` - Generate OneLogin CSV format instead of API calls

**Application Migration:**
- `pass_app_parameters` - Extract and pass app configuration parameters to OneLogin (default: `true`)
  - **SAML apps**: Extracts ACS URL, Entity ID, NameID format, attribute statements, signature algorithm
  - **OIDC/OAuth apps**: Extracts redirect URIs, grant types, response types, scopes, application type
  - **Generic metadata**: URLs, icons, help links, user attribute mappings
  - Only passes parameters when the OneLogin connector supports custom parameters (`allows_new_parameters` flag)
  - Automatically filters out source-specific provider fields that won't work on OneLogin
  - Speeds up migration by pre-populating app configuration

#### Checking Connector Capabilities

To see which OneLogin connectors support custom parameters, query the connector database:

```python
from onelogin_migration_core.db import get_default_connector_db

db = get_default_connector_db()

# Get statistics
stats = db.get_connectors_stats()
print(f"Total connectors: {stats['total']}")
print(f"Support custom params: {stats['with_custom_params']}")

# List connectors that support custom parameters
for connector in db.get_connectors_with_custom_parameters():
    print(f"  - {connector['name']} (ID: {connector['id']})")

# Check a specific connector
connector = db.get_onelogin_connector(123456)
if connector and connector['allows_new_parameters']:
    print(f"{connector['name']} supports custom parameters!")
```

**Note**: The connector database is automatically refreshed from OneLogin API every 24 hours.

**Safety:**
- `dry_run` - Simulates migration without writing to OneLogin (default: `true`)

## Secure Credential Management

### Security Design

Credentials are never stored in files:
- Source provider API tokens stored in **system keyring** (encrypted by OS)
- OneLogin client secrets stored in **system keyring** (encrypted by OS)
- Non-sensitive settings stored in JSON (`~/.onelogin-migration/settings.json`)

### How It Works

**Bundled App (Recommended):**
1. Download and launch the macOS/Windows app
2. Enter credentials in the GUI
3. Credentials automatically save to system keyring
4. On next launch, credentials auto-fill from keyring
5. **Zero configuration files needed!**

**CLI Usage:**
```bash
# Store credentials securely
python -m onelogin_migration_cli.app credentials set source token
python -m onelogin_migration_cli.app credentials set onelogin client_secret

# Verify stored credentials
python -m onelogin_migration_cli.app credentials list

# Test authentication
python -m onelogin_migration_cli.app credentials test source
python -m onelogin_migration_cli.app credentials test onelogin
```

**GUI with Auto-Save:**
- Enter credentials in provider settings pages
- Click "Test Connection" to validate
- Credentials automatically save to keyring on successful validation
- Auto-prefill on next launch

### Security Benefits

| Feature | YAML files | Secure Storage |
|---------|-----------|----------------|
| Storage | Plaintext files | OS-encrypted keyring |
| Backup risk | Credentials in backups | Only public settings backed up |
| Accidental commits | Easy to commit secrets | Impossible to leak credentials |
| Access control | File permissions only | OS authentication required |
| Memory protection | Plain strings | Auto-zeroing SecureString |

### Migrating from YAML Configs

If you have existing YAML configuration files with credentials:

```bash
# Automatically extract and secure credentials
python -m onelogin_migration_cli.app credentials migrate config/migration.yaml

# This will:
# 1. Extract credentials to keyring
# 2. Create sanitized YAML backup
# 3. Overwrite original with safe version
```

### Credential Commands

```bash
# Store credentials
python -m onelogin_migration_cli.app credentials set <service> <key> [--value VALUE]

# Retrieve credentials
python -m onelogin_migration_cli.app credentials get <service> <key> [--reveal]

# List all credentials
python -m onelogin_migration_cli.app credentials list

# Delete credentials
python -m onelogin_migration_cli.app credentials delete <service> <key> [--force]

# Test authentication
python -m onelogin_migration_cli.app credentials test source|onelogin

# Migrate from YAML
python -m onelogin_migration_cli.app credentials migrate <config_path>

# View audit log
python -m onelogin_migration_cli.app credentials audit [--limit N]
```

### Where Credentials Are Stored

**System Keyring Locations:**
- **macOS**: Keychain Access.app (`login` keychain)
- **Windows**: Windows Credential Manager
- **Linux**: Secret Service (GNOME Keyring, KWallet, etc.)

**Non-Sensitive Settings:**
- Location: `~/.onelogin-migration/settings.json`
- Contains: Domain names, rate limits, chunk sizes, etc.
- Safe to: Backup, share with team (no secrets!)

**Audit Logs:**
- Location: `~/.onelogin-migration/audit.log`
- Contains: Credential access events (no actual credential values)

### Advanced Features

**Audit Logging:**
```bash
python -m onelogin_migration_cli.app credentials audit --limit 10
```

**Backend Options:**
```bash
python -m onelogin_migration_cli.app credentials set source token --backend keyring  # Default
python -m onelogin_migration_cli.app credentials set source token --backend vault    # Advanced
```

**Export/Import (Vault Only):**
```bash
python -m onelogin_migration_cli.app credentials export backup/vault.enc
python -m onelogin_migration_cli.app credentials import backup/vault.enc
```

### Security Best Practices

1. Use system keyring (default) — OS-managed encryption
2. Rotate API tokens regularly using `credentials set`
3. Use `credentials test` before migrations
4. Enable audit logging for tracking
5. Delete old YAML files after migrating to secure storage

## GUI Features

The graphical wizard provides a user-friendly interface for migrations with real-time feedback.

### Installation & Launch

```bash
# Install GUI package
pip install -e packages/gui

# Launch GUI
export PYTHONPATH=packages/gui/src:packages/core/src
python -m onelogin_migration_gui.main
```

### Wizard Steps

1. **Welcome** - Introduction and migration overview
2. **Source** - Configure source provider credentials with connection test
3. **Target (OneLogin)** - Configure OneLogin credentials with connection test
4. **Options** - Set migration behavior (dry-run, concurrency, export format)
5. **Objects** - Select categories to migrate (users, groups, apps, policies)
6. **Analysis** - Analyze your source environment with detailed reports
   - View user counts, attributes, and custom fields
   - Review group memberships and hierarchies
   - Examine application configurations and mappings
   - Get OneLogin connector matching recommendations
   - Export analysis results to CSV or XLSX
7. **Summary** - Review all settings before starting
8. **Progress** - Real-time progress bars and log streaming

### Features

**Safety Controls:**
- Nothing runs until you click **Start Migration** on the Summary step
- Dry-run mode enabled by default
- Connection tests must pass before proceeding

**Progress Monitoring:**
- Per-category progress bars (users, groups, applications)
- Live log streaming with color-coded messages
- Export file links for quick access

**Flexible Options:**
- Toggle verbose logging
- Enable/disable multi-threading
- Choose API calls vs. bulk CSV export
- Select specific migration categories

## Field Mapping and OneLogin Validation

### Standard Field Mapping

The toolkit automatically maps source provider profile fields to OneLogin's user schema. For Okta sources:

**Core Identity Fields:**
- `firstName` → `firstname`
- `lastName` → `lastname`
- `email` → `email`
- `login` → `username`

**Contact Information:**
- `primaryPhone` / `phone` / `workPhone` → `phone`
- `mobilePhone` → `mobile_phone`
- `secondEmail` → `second_email` (custom attribute)

**Organization Data:**
- `company` / `organization` → `company`
- `department` → `department`
- `title` → `title`

**Active Directory:**
- `samAccountName` → `samaccountname`
- `userPrincipalName` → `userprincipalname`

**Status:**
- Okta `ACTIVE` → OneLogin `state: 1`
- Okta inactive → OneLogin `state: 0`

### Custom Attributes

**Automatic Normalization:**
The toolkit automatically converts source provider profile fields to OneLogin custom attributes:
- camelCase → snake_case (e.g., `employeeNumber` → `employee_number`)
- Field names truncated to 64 characters
- Invalid characters replaced with underscores
- Leading digits prefixed with underscore

**Auto-Provisioning:**
Custom attributes are automatically created in OneLogin before user import (requires API permissions).

**Excluded Fields:**
Complex data types (arrays, objects) are skipped to prevent validation errors.

### Application Connector Mapping

Applications require OneLogin connector IDs. Configure mappings in `metadata.application_connectors`:

```yaml
metadata:
  application_connectors:
    "slack":
      "saml": 123456  # OneLogin Slack connector ID for SAML
    "github":
      "openid": 789012  # OneLogin GitHub connector for OIDC
```

To find connector IDs:
1. Create the app manually in OneLogin once
2. Note the connector ID from the app details
3. Add mapping to config for future migrations

## Logging and Monitoring

**Verbose Logging:**
```bash
python -m onelogin_migration_cli.app migrate --config config/migration.yaml -v
```

**Log Levels:**
- `INFO` - Migration progress, summary statistics
- `DEBUG` - API requests, field mappings, detailed operations
- `WARNING` - Skipped items, recoverable errors
- `ERROR` - API failures, validation errors with context

## Rate Limits and Performance

### Automatic Rate Limiting

- Token bucket algorithm prevents rate limit violations
- Automatic 429 retry with exponential backoff
- Per-API rate limit configuration (source per-minute, OneLogin per-hour)

**Smart Worker Calculation:**
When `max_workers` is omitted, the toolkit calculates optimal concurrency:
```
source_workers = source_rate_limit_per_minute / 150
onelogin_workers = (onelogin_rate_limit_per_hour / 60) / 30
recommended = min(source_workers, onelogin_workers, 16)
```

### Concurrent Processing

Enable multi-threading for large migrations:

```yaml
concurrency_enabled: true
max_workers: 4  # Or omit for auto-calculation
```

**Thread Safety:**
- All API clients use thread-local sessions
- Progress tracking with mutex locks
- State persistence is atomic

### Bulk Operations

**Bulk CSV Export:**
Generate OneLogin-compatible CSV for manual upload:
```bash
python -m onelogin_migration_cli.app migrate --config config/migration.yaml --bulk-user-upload
```

## Artifacts and Exports

### JSON Exports

**Main Export:**
- `source_export.json` - Complete export with all categories

**Timestamped Snapshots:**
- `{source}_users_{timestamp}.json`
- `{source}_groups_{timestamp}.json`
- `{source}_applications_{timestamp}.json`
- `{source}_memberships_{timestamp}.json`

### CSV Exports

When `--bulk-user-upload` is enabled:
- `bulk_user_upload_{timestamp}.csv` - OneLogin import format
- Custom attributes auto-provisioned via API first

### State Persistence

- `migration_state.json` - Resume capability
- Tracks completed users, groups, apps
- ID mappings for relationships (source ID → OneLogin ID)
- Automatically cleared on successful completion

## Troubleshooting

### Installation Issues

**`ModuleNotFoundError: No module named 'onelogin_migration_cli'`**

The package isn't installed in your virtual environment.

```bash
source .venv/bin/activate
./scripts/dev-install.sh
python -m onelogin_migration_cli.app --help
```

---

### API Errors

**`422 Unprocessable Entity` from OneLogin**

Invalid field names or values in the payload.

1. Check error logs for specific field names
2. Verify custom attributes exist in OneLogin first (`provision-attributes`)
3. Enable verbose logging: `-v` flag

---

**`401 Unauthorized` when assigning roles**

Region mismatch or expired token.

1. Verify `onelogin.region` matches your tenant (`us` or `eu`)
2. Check token endpoint: `https://api.{region}.onelogin.com`
3. Verify OAuth credentials are correct

---

**`429 Too Many Requests`**

Rate limit exceeded (retries automatically).

1. Reduce `max_workers` in config
2. Verify rate limit settings match your tenant
3. Check logs for retry behavior

---

### Migration Issues

**"cannot modify Account owner"**

OneLogin API blocks updates to the tenant owner account. User is skipped automatically — no action required.

---

**Application not migrating (skipped with warning)**

No connector ID mapping found.

Add to `metadata.application_connectors` in config:
```yaml
metadata:
  application_connectors:
    "app name":
      "saml": 123456
```

---

### Performance Issues

**Migration is slow**

1. Enable concurrency:
   ```yaml
   concurrency_enabled: true
   ```
2. Use bulk CSV export for users:
   ```bash
   python -m onelogin_migration_cli.app migrate --config config/migration.yaml --bulk-user-upload
   ```
3. Verify rate limits are set correctly

---

**Out of memory errors**

1. Reduce `page_size` in source config
2. Process categories separately using `categories` config
3. Use bulk CSV mode

## Development

### Setup

**Install all packages for development:**
```bash
./scripts/dev-install.sh
```

### Testing

```bash
# All packages
./scripts/test-all.sh

# Individual packages
cd packages/core && pytest tests/ -v
cd packages/cli && pytest tests/ -v
cd packages/gui && pytest tests/ -v
```

**Coverage:**
```bash
cd packages/core
pytest --cov=onelogin_migration_core --cov-report=html
```

### Code Quality

```bash
./scripts/format-all.sh
./scripts/lint-all.sh
```

### Project Structure

```
.
├── packages/
│   ├── core/                          # Core migration library
│   │   ├── src/onelogin_migration_core/
│   │   │   ├── clients.py            # API clients
│   │   │   ├── config.py             # Configuration
│   │   │   ├── field_mapper.py       # Provider field mapping protocol
│   │   │   ├── manager.py            # Migration orchestration
│   │   │   ├── progress.py           # Progress tracking
│   │   │   ├── credentials.py        # Credential management
│   │   │   └── db/                   # Database management
│   │   └── tests/
│   ├── cli/                           # Command-line interface
│   │   ├── src/onelogin_migration_cli/
│   │   │   ├── app.py                # CLI commands (Typer)
│   │   │   ├── credentials.py        # Credential commands
│   │   │   ├── database.py           # Database commands
│   │   │   └── telemetry.py          # Telemetry commands
│   │   └── tests/
│   └── gui/                           # Graphical interface
│       ├── src/onelogin_migration_gui/
│       │   ├── main.py               # GUI entry point
│       │   ├── steps/                # Wizard steps
│       │   └── dialogs/              # Dialog windows
│       └── tests/
├── scripts/
│   ├── dev-install.sh
│   ├── test-all.sh
│   ├── lint-all.sh
│   └── format-all.sh
├── config/
│   └── migration.template.yaml
└── tools/
    ├── build_app.sh                   # macOS build
    └── build_app.bat                  # Windows build
```

### Building Standalone Executables

**macOS:**
```bash
./tools/build_app.sh
# Output: dist/OneLogin Migration Tool.app
```

**Windows:**
```bash
tools\build_app.bat
# Output: dist\OneLogin Migration Tool.exe
```

**Build Requirements:**
- Python 3.10+ with virtual environment
- All packages installed (`./scripts/dev-install.sh`)
- PyInstaller 6.0+ (installed automatically by build script)

### Release Process

1. Update version in `pyproject.toml`
2. Run full test suite: `./scripts/test-all.sh`
3. Build executables
4. Test the bundled app
5. Tag release: `git tag vX.Y.Z`

## Security and Git Hygiene

### Sensitive Files

**Never commit:**
- YAML files with credentials (use `credentials migrate` to extract them)
- Generated exports with real user data
- Vault backup files (`.enc`)

**Safe to commit:**
- `~/.onelogin-migration/settings.json` (non-sensitive settings only)
- Sanitized YAML configs (with `*_source: keyring` references)

### Credential Management Best Practices

1. Use system keyring (default) — OS-managed encryption
2. Rotate API tokens regularly using `credentials set`
3. Use `credentials test` before migrations
4. Enable audit logging for tracking
5. Delete old YAML files after migrating to secure storage

## License

See [LICENSE](LICENSE) file for details.

## Support

For issues, feature requests, or questions:
1. Check [Troubleshooting](#troubleshooting)
2. Review [existing issues](../../issues)
3. Open a new issue with: command used, sanitized config, error logs, expected vs actual behavior
