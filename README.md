# Okta to OneLogin Migration Toolkit

A production-ready Python toolkit for migrating identity data from Okta to OneLogin with enterprise-grade features:

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

# 1. Test export from Okta (safe, read-only)
python -m onelogin_migration_cli.app plan --config config/migration.yaml

# 2. Preview custom attributes to create
python -m onelogin_migration_cli.app provision-attributes --config config/migration.yaml --dry-run

# 3. Pre-create custom attributes in OneLogin
python -m onelogin_migration_cli.app provision-attributes --config config/migration.yaml

# 4. Run migration (dry-run mode by default)
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

Export data from Okta without making any changes to OneLogin. Perfect for auditing and planning.

```bash
python -m onelogin_migration_cli.app plan --config config/migration.yaml -v
```

**What it does:**
- Exports users, groups, memberships, and applications from Okta
- Saves `okta_export.json` in the configured export directory
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
1. Exports all data from Okta (if not provided)
2. Cleans up existing OneLogin roles (except defaults)
3. Creates roles (groups), users, and applications in OneLogin
4. Assigns users to roles and roles to applications

**Options:**
- `--dry-run` - Simulate migration without writes (overrides config)
- `--bulk-user-upload` - Generate OneLogin CSV instead of API calls
- `--export PATH` - Use pre-generated Okta export JSON
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
onelogin-migration-tool gui --config config/migration.yaml
```

**Features:**
- Connection testing for Okta and OneLogin
- Live settings editor with validation
- Category selection (users, groups, apps, policies)
- Real-time progress bars and log streaming
- Bulk CSV export option

---

### `show-config` - Debug Configuration

Display the current configuration with secrets masked for troubleshooting.

```bash
onelogin-migration-tool show-config --config config/migration.yaml
```

---

### `provision-attributes` - Pre-create Custom Attributes

Analyze Okta user profiles and automatically create all necessary custom attributes in OneLogin before migration.

```bash
onelogin-migration-tool provision-attributes --config config/migration.yaml
```

**What it does:**
1. Exports users from Okta (or uses existing export)
2. Analyzes all user profile fields across all users
3. Identifies which fields become custom attributes
4. Creates those custom attributes in OneLogin with proper naming

**Use cases:**
- Preview custom attributes before migration
- Pre-provision attributes for bulk CSV import
- Troubleshoot attribute mapping issues
- Verify attribute normalization (camelCase → snake_case)

**Options:**
- `--export PATH` - Use pre-generated Okta export instead of fetching
- `--dry-run` - Preview attributes without creating them
- `-v, --verbose` - Show detailed attribute analysis

**Example workflow:**
```bash
# Preview what attributes would be created
onelogin-migration-tool provision-attributes --config config/migration.yaml --dry-run

# Create the attributes in OneLogin
onelogin-migration-tool provision-attributes --config config/migration.yaml

# Use with existing export
onelogin-migration-tool plan --config config/migration.yaml --output okta_export.json
onelogin-migration-tool provision-attributes --config config/migration.yaml --export okta_export.json
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

```yaml
# Migration behavior
dry_run: true                    # Safe mode - no writes to OneLogin
chunk_size: 200                  # Items per batch
export_directory: artifacts      # Where to save exports
concurrency_enabled: false       # Enable multi-threading
max_workers: 4                   # Worker threads (auto-calculated if omitted)
bulk_user_upload: false         # Generate CSV instead of API calls
pass_app_parameters: true        # Extract and pass app parameters during migration

# Okta source configuration
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

**Okta:**
- `domain` - Your Okta domain (e.g., `company.okta.com`)
- `token` - Admin API token from Okta Admin Console → Security → API

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
- `pass_app_parameters` - Extract and pass app configuration parameters from Okta to OneLogin (default: `true`)
  - **SAML apps**: Extracts ACS URL, Entity ID, NameID format, attribute statements, signature algorithm
  - **OIDC/OAuth apps**: Extracts redirect URIs, grant types, response types, scopes, application type
  - **Generic metadata**: URLs, icons, help links, user attribute mappings
  - Only passes parameters when the OneLogin connector supports custom parameters (`allows_new_parameters` flag)
  - Automatically filters out Okta-specific provider fields that won't work on OneLogin
  - Speeds up migration by pre-populating app configuration

#### Checking Connector Capabilities

To see which OneLogin connectors support custom parameters, you can query the connector database:

```python
from onelogin_migration_core.db import get_default_connector_db

# Get connector database
db = get_default_connector_db()

# Get statistics
stats = db.get_connectors_stats()
print(f"Total connectors: {stats['total']}")
print(f"Support custom params: {stats['with_custom_params']}")
print(f"No custom params: {stats['without_custom_params']}")

# List all connectors that support custom parameters
custom_param_connectors = db.get_connectors_with_custom_parameters()
for connector in custom_param_connectors:
    print(f"  - {connector['name']} (ID: {connector['id']})")

# Check specific connector
connector = db.get_onelogin_connector(123456)  # Replace with connector ID
if connector:
    if connector['allows_new_parameters']:
        print(f"{connector['name']} supports custom parameters!")
    else:
        print(f"{connector['name']} does NOT support custom parameters")
```

**Note**: The connector database is automatically refreshed from OneLogin API every 24 hours. The `allows_new_parameters` field comes directly from OneLogin's API and indicates whether apps created with that connector can define custom parameters.

**Safety:**
- `dry_run` - Simulates migration without writing to OneLogin (default: `true`)

## Secure Credential Management

### 🔒 Maximum Security Design

The toolkit uses enterprise-grade credential management:

**Credentials are NEVER stored in files:**
- ✅ Okta API tokens stored in **system keyring** (encrypted by OS)
- ✅ OneLogin client secrets stored in **system keyring** (encrypted by OS)
- ✅ Non-sensitive settings stored in JSON (`~/.onelogin-migration/settings.json`)
- ❌ No YAML files with plaintext credentials

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
onelogin-migration-tool credentials set okta token
onelogin-migration-tool credentials set onelogin client_secret

# Verify stored credentials
onelogin-migration-tool credentials list

# Test authentication
onelogin-migration-tool credentials test okta
onelogin-migration-tool credentials test onelogin
```

**GUI with Auto-Save:**
- Enter credentials in provider settings pages
- Click "Test Connection" to validate
- Credentials automatically save to keyring on successful validation
- Auto-prefill on next launch

### Security Benefits

| Feature | Old (YAML) | New (Secure Storage) |
|---------|-----------|---------------------|
| Storage | Plaintext files | OS-encrypted keyring |
| Backup risk | Credentials in backups | Only public settings backed up |
| Accidental commits | Easy to commit secrets | Impossible to leak credentials |
| Access control | File permissions only | OS authentication required |
| Memory protection | Plain strings | Auto-zeroing SecureString |

### Migrating from YAML Configs

If you have existing YAML configuration files with credentials:

**Option 1: CLI Migration (Recommended)**
```bash
# Automatically extract and secure credentials
onelogin-migration-tool credentials migrate config/migration.yaml

# This will:
# 1. Extract credentials to keyring
# 2. Create sanitized YAML backup
# 3. Overwrite original with safe version
```

**Option 2: Manual Re-entry**
1. Open GUI: `onelogin-migration-tool gui`
2. Enter credentials in provider pages
3. Click "Test Connection" (auto-saves on success)
4. Delete old YAML file: `rm config/migration.yaml`

### Credential Commands

```bash
# Store credentials
onelogin-migration-tool credentials set <service> <key> [--value VALUE]

# Retrieve credentials
onelogin-migration-tool credentials get <service> <key> [--reveal]

# List all credentials
onelogin-migration-tool credentials list

# Delete credentials
onelogin-migration-tool credentials delete <service> <key> [--force]

# Test authentication
onelogin-migration-tool credentials test okta|onelogin

# Migrate from YAML
onelogin-migration-tool credentials migrate <config_path>

# View audit log
onelogin-migration-tool credentials audit [--limit N]

# Validate sanitized config
onelogin-migration-tool credentials validate <config_path>
```

### Where Credentials Are Stored

**System Keyring Locations:**
- **macOS**: Keychain Access.app (`login` keychain)
- **Windows**: Windows Credential Manager
- **Linux**: Secret Service (GNOME Keyring, KWallet, etc.)

**Non-Sensitive Settings:**
- Location: `~/.onelogin-migration/settings.json`
- Contains: Domain names, rate limits, chunk sizes, etc.
- Safe to: Backup, share with team, commit to git (no secrets!)

**Audit Logs:**
- Location: `~/.onelogin-migration/audit.log`
- Contains: Credential access events (NO actual credential values)
- Useful for: Security auditing, troubleshooting

### Advanced Features

**Audit Logging:**
Every credential operation is logged (without exposing secrets):
```bash
onelogin-migration-tool credentials audit --limit 10
```

Output:
```
Recent credential events (last 10):
2025-01-15 10:23:45 - STORED: okta/token
2025-01-15 10:24:12 - RETRIEVED: okta/token
2025-01-15 10:25:01 - RETRIEVED: onelogin/client_secret
2025-01-15 10:30:15 - DELETED: test_service/test_key
```

**Backend Options:**
```bash
# Use different storage backends
onelogin-migration-tool credentials set okta token --backend keyring  # Default
onelogin-migration-tool credentials set okta token --backend memory   # Testing only
onelogin-migration-tool credentials set okta token --backend vault    # Advanced users
```

**Export/Import (Vault Only):**
```bash
# Export encrypted vault for backup
onelogin-migration-tool credentials export backup/vault.enc

# Import vault from backup
onelogin-migration-tool credentials import backup/vault.enc
```

### Security Best Practices

1. **Use System Keyring** (default) - Most secure, OS-managed encryption
2. **Never use memory backend in production** - Credentials don't persist
3. **Enable audit logging** - Track credential access
4. **Rotate credentials regularly** - Update API tokens periodically
5. **Use test command** - Verify credentials before migration
6. **Delete old YAML files** - After migrating to secure storage

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

The GUI provides a step-by-step wizard that guides you through the migration process:

1. **Welcome** - Introduction and migration overview
2. **Source (Okta)** - Configure Okta credentials with connection test
3. **Target (OneLogin)** - Configure OneLogin credentials with connection test
4. **Options** - Set migration behavior (dry-run, concurrency, export format)
5. **Objects** - Select categories to migrate (users, groups, apps, policies)
6. **Analysis** - Analyze your Okta environment with detailed reports
   - View user counts, attributes, and custom fields
   - Review group memberships and hierarchies
   - Examine application configurations and mappings
   - Get OneLogin connector matching recommendations
   - Export analysis results to CSV or XLSX
7. **Summary** - Review all settings before starting
8. **Progress** - Real-time progress bars and log streaming

### Features

**Settings Dialog:**
- Live validation of all configuration fields
- Connection testing for both Okta and OneLogin
- Directory picker for export location
- Apply changes without restarting

**Safety Controls:**
- Nothing runs until you click **Start Migration** on the Summary step
- Dry-run mode enabled by default
- Connection tests must pass before proceeding
- Confirmation prompts for destructive operations

**Progress Monitoring:**
- Per-category progress bars (users, groups, applications)
- Live log streaming with color-coded messages
- Export file links for quick access
- Bulk CSV download (if enabled)

**Flexible Options:**
- Toggle verbose logging
- Enable/disable multi-threading
- Choose API calls vs. bulk CSV export
- Select specific migration categories

## Field Mapping and OneLogin Validation

### Standard Field Mapping

The toolkit automatically maps Okta profile fields to OneLogin's user schema:

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
The toolkit automatically converts Okta profile fields to OneLogin custom attributes:
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

### Console Logging

**Standard Output:**
```bash
onelogin-migration-tool migrate --config config/migration.yaml
```

**Verbose Logging:**
```bash
onelogin-migration-tool migrate --config config/migration.yaml -v
```

**Log Levels:**
- `INFO` - Migration progress, summary statistics
- `DEBUG` - API requests, field mappings, detailed operations
- `WARNING` - Skipped items, recoverable errors
- `ERROR` - API failures, validation errors with context

**Rich Formatting:**
- Color-coded log levels
- Progress indicators
- Structured error messages with HTTP status, URL, and response details

## Rate Limits and Performance

### Automatic Rate Limiting

**Built-in Protection:**
- Token bucket algorithm prevents rate limit violations
- Automatic 429 retry with exponential backoff
- Per-API rate limit configuration (Okta per-minute, OneLogin per-hour)

**Smart Worker Calculation:**
When `max_workers` is omitted, the toolkit calculates optimal concurrency:
```
okta_workers = okta_rate_limit_per_minute / 150
onelogin_workers = (onelogin_rate_limit_per_hour / 60) / 30
recommended = min(okta_workers, onelogin_workers, 16)
```

The toolkit clamps `max_workers` to recommended values to prevent thrashing.

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

**User Assignment to Roles:**
- Batched in chunks of 50 users per API call
- Significantly faster than individual assignments

**Bulk CSV Export:**
Generate OneLogin-compatible CSV for manual upload:
```bash
onelogin-migration-tool migrate --config config/migration.yaml --bulk-user-upload
```

## Artifacts and Exports

### JSON Exports

**Main Export:**
- `okta_export.json` - Complete export with all categories

**Timestamped Snapshots:**
- `{source}_users_{timestamp}.json`
- `{source}_groups_{timestamp}.json`
- `{source}_applications_{timestamp}.json`
- `{source}_memberships_{timestamp}.json`

### CSV Exports

**Bulk User Upload:**
When `--bulk-user-upload` is enabled:
- `bulk_user_upload_{timestamp}.csv` - OneLogin import format
- Custom attributes auto-provisioned via API first
- Template from `templates/user-upload-template.csv`

### State Persistence

**Migration State:**
- `migration_state.json` - Resume capability
- Tracks completed users, groups, apps
- ID mappings for relationships (Okta ID → OneLogin ID)
- Automatically cleared on successful completion

## Troubleshooting

### Installation Issues

**`ModuleNotFoundError: No module named 'onelogin_migration_tool'`**

The package isn't properly installed in your virtual environment.

**Solution:**
```bash
# Ensure venv is active
source .venv/bin/activate

# Clean reinstall
pip uninstall -y okta-to-onelogin
pip install .

# Verify installation
python -c "import onelogin_migration_tool; print(onelogin_migration_tool.__file__)"
onelogin-migration-tool --help
```

**Command works, then stops working**

Editable installs (`pip install -e .`) can become stale after code changes.

**Solution:**
```bash
pip uninstall -y okta-to-onelogin
pip install .  # Regular install is more reliable
```

---

### API Errors

**`422 Unprocessable Entity` from OneLogin**

Invalid field names or values in the payload.

**Solution:**
1. Check error logs for specific field names
2. Verify custom attributes exist in OneLogin first
3. Enable verbose logging: `-v` flag

**Common causes:**
- Custom attributes not provisioned in OneLogin
- Invalid enum values (e.g., invalid locale code)
- Empty required fields

---

**`401 Unauthorized` when assigning roles**

Region mismatch or expired token.

**Solution:**
1. Verify `onelogin.region` matches your tenant (`us` or `eu`)
2. Check token endpoint: `https://api.{region}.onelogin.com`
3. Verify OAuth credentials are correct

---

**`429 Too Many Requests`**

Rate limit exceeded (should retry automatically).

**Solution:**
1. Reduce `max_workers` in config
2. Verify rate limit settings match your tenant
3. Check logs for retry behavior
4. Consider using bulk CSV export instead

---

### Migration Issues

**"cannot modify Account owner"**

OneLogin API blocks updates to the tenant owner account.

**Behavior:**
- User is skipped automatically with a warning
- Other users continue processing normally
- No action required

---

**GUI shows YAML editor instead of form**

Old package version installed.

**Solution:**
```bash
pip uninstall -y okta-to-onelogin
pip install .[gui]
```

---

**Application not migrating (skipped with warning)**

No connector ID mapping found.

**Solution:**
1. Find the connector ID in OneLogin Admin
2. Add to `metadata.application_connectors` in config:
   ```yaml
   metadata:
     application_connectors:
       "app name":
         "saml": 123456
   ```

---

### Performance Issues

**Migration is slow**

**Solutions:**
1. Enable concurrency:
   ```yaml
   concurrency_enabled: true
   ```
2. Use bulk CSV export for users:
   ```bash
   onelogin-migration-tool migrate --bulk-user-upload
   ```
3. Verify rate limits are set correctly
4. Check network latency to APIs

---

**Out of memory errors**

Large exports may consume significant memory.

**Solutions:**
1. Reduce `page_size` in Okta config
2. Process categories separately using `categories` config
3. Increase system memory or use bulk CSV mode

## Development

### Setup

This project uses a **monorepo structure** with three independent packages.

**Install all packages for development:**
```bash
./scripts/dev-install.sh
```

**Or install individually:**
```bash
pip install -e packages/core
pip install -e packages/cli
pip install -e packages/gui
```

### Testing

Run tests for all packages:
```bash
./scripts/test-all.sh
```

**Or test individual packages:**
```bash
# Core package tests
cd packages/core && pytest tests/ -v

# CLI package tests
cd packages/cli && pytest tests/ -v

# GUI package tests
cd packages/gui && pytest tests/ -v
```

**Coverage:**
```bash
cd packages/core
pytest --cov=onelogin_migration_core --cov-report=html
```

### Code Quality

```bash
# Format all packages
./scripts/format-all.sh

# Lint all packages
./scripts/lint-all.sh
```

### Project Structure

```
.
├── packages/                           # Monorepo packages
│   ├── core/                          # Core migration library
│   │   ├── src/onelogin_migration_core/
│   │   │   ├── clients.py            # API clients
│   │   │   ├── config.py             # Configuration
│   │   │   ├── manager.py            # Migration logic
│   │   │   ├── progress.py           # Progress tracking
│   │   │   ├── credentials.py        # Credential management
│   │   │   └── db/                   # Database management
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── README.md
│   ├── cli/                           # Command-line interface
│   │   ├── src/onelogin_migration_cli/
│   │   │   ├── app.py                # CLI commands (Typer)
│   │   │   ├── credentials.py        # Credential commands
│   │   │   ├── database.py           # Database commands
│   │   │   └── telemetry.py          # Telemetry commands
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── README.md
│   └── gui/                           # Graphical interface
│       ├── src/onelogin_migration_gui/
│       │   ├── main.py               # GUI entry point
│       │   ├── components.py         # UI components
│       │   ├── steps/                # Wizard steps
│       │   └── dialogs/              # Dialog windows
│       ├── tests/
│       ├── pyproject.toml
│       └── README.md
├── scripts/                           # Development scripts
│   ├── dev-install.sh                # Install all packages
│   ├── test-all.sh                   # Run all tests
│   ├── lint-all.sh                   # Lint all packages
│   └── format-all.sh                 # Format all packages
├── config/
│   └── migration.template.yaml
├── templates/
│   └── user-upload-template.csv
├── artifacts/                         # Generated exports (gitignored)
├── pyproject.toml          # Package metadata
└── README.md
```

### Contributing

1. Create a feature branch
2. Make changes with tests
3. Run test suite
4. Update documentation
5. Submit pull request

### Building Standalone Executables

The project includes PyInstaller configuration to bundle the application for distribution on macOS and Windows.

**macOS:**
```bash
# Build the app bundle
./tools/build_app.sh

# Output: dist/OneLogin Migration Tool.app
# To run: open 'dist/OneLogin Migration Tool.app'
```

**Windows:**
```bash
# Build the executable
tools\build_app.bat

# Output: dist\OneLogin Migration Tool.exe
```

**What's Included:**
- All Python dependencies bundled
- System keyring integration for secure credentials
- GUI wizard with analysis tools
- No Python installation required on target system
- ~150-200MB final size

**Build Requirements:**
- Python 3.10+ with virtual environment
- All packages installed (`./scripts/dev-install.sh`)
- PyInstaller 6.0+ (installed automatically by build script)

**Advanced Options:**

*Create macOS DMG for distribution:*
```bash
hdiutil create -volname "OneLogin Migration Tool" \
  -srcfolder "dist/OneLogin Migration Tool.app" \
  -ov -format UDZO \
  "dist/OneLogin-Migration-Tool.dmg"
```

*Code sign macOS app (requires Developer ID):*
```bash
codesign --deep --force --verify --verbose \
  --sign "Developer ID Application: Your Name" \
  "dist/OneLogin Migration Tool.app"
```

*Create Windows installer (requires Inno Setup):*
1. Download [Inno Setup](https://jrsoftware.org/isinfo.php)
2. Create an `.iss` installer script
3. Point it to `dist\OneLogin Migration Tool.exe`

**Platform-Specific Notes:**

*macOS:*
- App bundle includes proper icon (`.icns`)
- Signed with ad-hoc signature by default
- Supports Apple Silicon (ARM64) and Intel (x86_64)
- Minimum OS: macOS 10.13+

*Windows:*
- Executable includes icon (`.ico`)
- Runs without console window
- Compatible with Windows 10+

### Release Process

1. Update version in `pyproject.toml`
2. Update CHANGELOG (if exists)
3. Run full test suite
4. Build executables: `./tools/build_app.sh` (Mac) or `tools\build_app.bat` (Windows)
5. Test the bundled app
6. Create installers (DMG, MSI, etc.)
7. Tag release: `git tag v0.1.x`

## Security and Git Hygiene

### Secure Credential Storage

**v0.2.0+ uses system keyring:**
- ✅ Credentials stored in OS-encrypted keyring (macOS Keychain, Windows Credential Manager, Linux Secret Service)
- ✅ Non-sensitive settings in `~/.onelogin-migration/settings.json` (safe to backup/share)
- ✅ Audit logs in `~/.onelogin-migration/audit.log` (no secrets logged)
- ❌ No YAML files with plaintext credentials

See [Secure Credential Management](#secure-credential-management) for details.

### Sensitive Files

**Never commit:**
- Legacy YAML files with credentials (migrate with `credentials migrate` command)
- Generated exports with real data
- Vault backup files (`.enc` files)

**Safe to commit:**
- `~/.onelogin-migration/settings.json` (non-sensitive settings only)
- Sanitized YAML configs (with `*_source: keyring` references)

### .gitignore

Ensure these patterns are excluded:
```gitignore
# Virtual environment
.venv/
venv/

# Generated artifacts
artifacts/
*.json
*.csv

# Legacy configuration with secrets (pre-v0.2.0)
config/migration.yaml

# Vault backups
*.enc

# Python cache
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
```

### Credential Management Best Practices

**v0.2.0+ (Secure Storage):**
1. ✅ Use system keyring (default) - OS-managed encryption
2. ✅ Rotate API tokens regularly using `credentials set` command
3. ✅ Use `credentials test` before migrations
4. ✅ Enable audit logging for tracking
5. ✅ Delete old YAML files after migration

**Legacy (pre-v0.2.0):**
1. Migrate to secure storage: `onelogin-migration-tool credentials migrate config/migration.yaml`
2. Use environment variables for CI/CD
3. Never commit YAML files with credentials

## License

See [LICENSE](LICENSE) file for details.

## Support

For issues, feature requests, or questions:
1. Check [Troubleshooting](#troubleshooting) section
2. Review [existing issues](../../issues)
3. Open a new issue with:
   - Command used
   - Config (sanitized)
   - Error logs
   - Expected vs actual behavior
