# Migration Core Modules

This package contains the modular components for the Okta to OneLogin migration tool. The original monolithic `migration.py` file (1350 lines) has been refactored into focused modules for better maintainability.

## Module Overview

### constants.py (~75 lines)
Shared constants and field definitions:
- `DEFAULT_APPLICATION_CONNECTORS` - Application connector mappings
- `KNOWN_STANDARD_FIELDS` - Fields that map to standard OneLogin fields
- `EXPLICIT_CUSTOM_FIELDS` - Fields that become custom attributes

### transformers.py (~320 lines)
Field transformation and normalization:
- `FieldTransformer` class with static methods:
  - `transform_user()` - Transform Okta user to OneLogin format
  - `transform_group()` - Transform Okta group to OneLogin role
  - `transform_application()` - Transform Okta app to OneLogin app
  - `normalize_custom_attribute_name()` - Normalize custom attribute names
  - `clean_payload()` - Remove None/empty values

### custom_attributes.py (~140 lines)
Custom attribute discovery and provisioning:
- `CustomAttributeManager` class with static methods:
  - `discover_custom_attributes()` - Analyze users and discover custom attributes
  - `provision_custom_attributes()` - Create custom attributes in OneLogin

### state_manager.py (~165 lines)
State persistence for resumable migrations:
- `StateManager` class:
  - `load_state()` / `save_state_locked()` - Persist migration state
  - `is_completed()` / `mark_completed()` - Track completed items
  - `update_lookup()` / `get_lookup_ids()` - Manage ID mappings
  - `record_export_path()` / `get_export_path()` - Track export location

### csv_generator.py (~115 lines)
Bulk user upload CSV generation:
- `BulkUserCSVGenerator` class with static methods:
  - `load_template_headers()` - Load CSV headers from template
  - `write_csv()` - Generate bulk upload CSV file
  - `ensure_custom_attributes()` - Ensure custom attributes exist for CSV

### exporters.py (~100 lines)
Okta data export utilities:
- `OktaExporter` class with static methods:
  - `export_from_okta()` - Collect data from Okta
  - `save_export()` - Persist export to disk (with per-category snapshots)
  - `load_export()` - Load export from disk

### importers.py (~390 lines)
OneLogin data import utilities:
- `OneLoginImporter` class:
  - `import_into_onelogin()` - Orchestrate the full import process
  - `_prepare_one_login_roles()` - Clean up existing roles
  - `_process_memberships()` - Bulk assign users to roles
  - `_process_items()` - Process items with optional threading
  - Supports concurrent processing for better performance

### __init__.py
Public API exports - exposes all classes and constants for easy importing.

## Benefits of the Refactoring

1. **Better Organization**: Each module has a single, focused responsibility
2. **Easier Testing**: Smaller modules are easier to test in isolation
3. **Improved Maintainability**: Changes are localized to specific modules
4. **Reusability**: Components can be used independently
5. **Better Documentation**: Each module can be documented separately
6. **Reduced Complexity**: ~1350 lines split into 7 focused modules (~200 lines each)

## Backward Compatibility

The original `migration.py` file remains unchanged to maintain 100% backward compatibility. All existing code that imports `MigrationManager` continues to work without modifications.

## Future Work

The next phase would involve updating `migration.py` to delegate to these modules, completing the refactoring while maintaining the same public API.

## Usage

You can import from the core package:

```python
from onelogin_migration_tool.core import (
    FieldTransformer,
    CustomAttributeManager,
    StateManager,
    BulkUserCSVGenerator,
    OktaExporter,
    OneLoginImporter,
)

# Transform a user
user_payload = FieldTransformer.transform_user(okta_user)

# Discover custom attributes
attributes = CustomAttributeManager.discover_custom_attributes(users)

# Manage state
state = StateManager(Path("migration_state.json"))
state.load_state()
```

Or continue using the high-level `MigrationManager` from `migration.py`:

```python
from onelogin_migration_tool import MigrationManager

manager = MigrationManager(settings)
export = manager.export_from_okta()
manager.import_into_onelogin(export)
```
