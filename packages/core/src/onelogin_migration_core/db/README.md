# Connector Database Module

This module provides SQLite-backed storage for Okta and OneLogin connector catalogs, intelligent mappings between platforms, and migration telemetry.

## Overview

### Why a Database?

The connector mapping problem is complex:
- **8,152 Okta connectors** (from undocumented internal API)
- **8,426 OneLogin connectors** (from official API)
- **Only ~27% exact match rate** between platforms
- Need for fuzzy matching, user overrides, and learning from corrections

A database provides:
- **Fast lookups** for connector mappings during migration
- **Queryable intelligence** with confidence scores
- **User override tracking** to improve future mappings
- **Telemetry storage** for analytics and improvement

### Architecture

```
~/.onelogin-migration/
└── connectors.db          # SQLite database (single file, no server needed)
```

## Database Schema

### Core Tables

**`onelogin_connectors`** - OneLogin connector catalog
- Loaded from OneLogin API (`/api/2/connectors`)
- 8,426 connectors with metadata (name, ID, icon, auth methods)

**`okta_connectors`** - Okta connector catalog
- Loaded from Okta's internal OIN (Okta Integration Network) API
- 8,152 connectors with metadata (name, category, features)

**`connector_mappings`** - Intelligent mappings between platforms
- 2,170 mappings (1,976 exact, 194 fuzzy)
- Confidence scores (0-100%)
- Match types: exact, fuzzy, manual, user_override
- Source tracking: automated, user_corrected, verified

### Supporting Tables

**`user_connector_overrides`** - User's preferred mappings
- Override automated mappings when needed
- Track user corrections for future improvement

**`migration_runs`** - Track each migration execution
- Telemetry: counts, timing, success rates
- Links to detailed events

**`migration_events`** - Detailed migration event log
- Track connector matches/mismatches
- Error logging
- User acceptance tracking

### Views

**`best_connector_mappings`** - Best mapping for each Okta connector
- Automatically selects highest confidence mapping
- Prioritizes user overrides
- Factors in usage success rate

**`mapping_statistics`** - Aggregate statistics
- Breakdown by match type and source
- Confidence averages
- Usage and success counts

## Usage

### Loading Connector Data

```bash
# From project root
python3 load_connectors_standalone.py
```

This loads:
1. OneLogin connectors from `onelogin_api_connectors.json`
2. Okta connectors from `okta_oin_catalog.json`
3. Connector mappings from `connector_mapping.json`

### Querying the Database

#### Using the Python API

```python
from onelogin_migration_tool.db import get_default_connector_db

# Initialize database
db = get_default_connector_db()

# Find best mapping for an Okta connector
mapping = db.get_best_mapping("slack")
if mapping:
    print(f"Okta: {mapping['okta_display_name']}")
    print(f"OneLogin: {mapping['onelogin_name']} (ID: {mapping['onelogin_id']})")
    print(f"Confidence: {mapping['confidence_score']}%")

# Get all possible mappings (for user selection)
all_mappings = db.get_all_mappings("salesforce")
for m in all_mappings:
    print(f"{m['onelogin_name']} - {m['confidence_score']}%")

# Set user override
db.set_user_override(
    okta_internal_name="salesforce",
    onelogin_id=5,  # Salesforce connector ID
    notes="User prefers SAML 2.0 connector"
)

# Search connectors
onelogin_results = db.search_onelogin_connectors("%slack%")
okta_results = db.search_okta_connectors("%salesforce%")
```

#### Using SQL Directly

```python
import sqlite3
from pathlib import Path

conn = sqlite3.connect(str(Path.home() / ".onelogin-migration" / "connectors.db"))
conn.row_factory = sqlite3.Row

# Find unmapped Okta connectors
cursor = conn.execute("""
    SELECT oc.display_name
    FROM okta_connectors oc
    LEFT JOIN connector_mappings cm ON oc.internal_name = cm.okta_internal_name
    WHERE cm.id IS NULL
    ORDER BY oc.display_name
""")

for row in cursor:
    print(row['display_name'])
```

#### Using the sqlite3 CLI

```bash
sqlite3 ~/.onelogin-migration/connectors.db

# Find high-confidence fuzzy matches
SELECT okta_display_name, onelogin_name, confidence_score
FROM connector_mappings
WHERE match_type = 'fuzzy' AND confidence_score > 90
ORDER BY confidence_score DESC;

# Get mapping statistics
SELECT * FROM mapping_statistics;

# Find all Salesforce variants
SELECT * FROM onelogin_connectors WHERE name LIKE '%Salesforce%';
```

### Example Queries

See [query_connectors.py](../../../query_connectors.py) for working examples:

```bash
python3 query_connectors.py
```

## Data Files

The connector data is loaded from JSON files in `~/Downloads/ol_okta_connectors_analysis/`:

### `onelogin_api_connectors.json`
```json
[
  {
    "id": 77999,
    "name": "Slack",
    "icon_url": "https://cdn01.onelogin.com/...",
    "allows_new_parameters": true,
    "auth_method": 2
  }
]
```

### `okta_oin_catalog.json`
```json
[
  {
    "name": "slack",
    "label": "Slack",
    "category": "COMMUNICATION",
    "signOnModes": ["SAML_2_0", "OPENID_CONNECT"],
    "status": "ACTIVE"
  }
]
```

### `connector_mapping.json`
```json
{
  "statistics": { ... },
  "mapping": [
    {
      "oktaInternalName": "slack",
      "oktaName": "Slack",
      "oneloginId": 77999,
      "oneloginName": "Slack",
      "matchType": "exact",
      "normalizedName": "slack"
    }
  ]
}
```

## Statistics

Current database contents:

- **OneLogin Connectors:** 8,426
- **Okta Connectors:** 8,152
- **Total Mappings:** 2,170
  - Exact matches: 1,976 (100% confidence)
  - Fuzzy matches: 194 (average 83.9% confidence)
- **Unmapped Okta connectors:** ~6,000
- **Unmapped OneLogin connectors:** ~6,200

## Security

The database contains **non-sensitive data only**:
- Connector catalogs (public information)
- Mapping intelligence
- Migration telemetry

**Credentials are NEVER stored in the database.** They remain in the system keyring via [secure_settings.py](../secure_settings.py).

File permissions: `0600` (user read/write only)

## Future Enhancements

### Phase 1: Learning System (Next)
- Track user mapping decisions during migration
- Update confidence scores based on acceptance rates
- Identify patterns in user corrections

### Phase 2: Community Intelligence
- Export anonymized mapping improvements
- Share verified mappings with other users
- Crowdsourced connector verification

### Phase 3: Advanced Analytics
- Migration success rate analysis
- Common error pattern detection
- Performance optimization insights

## API Reference

### ConnectorDatabase Class

**`__init__(db_path: Optional[Path] = None)`**
- Initialize database connection
- Default path: `~/.onelogin-migration/connectors.db`

**`initialize_schema() -> None`**
- Create database schema from schema.sql
- Safe to call multiple times (idempotent)

**`get_best_mapping(okta_internal_name: str) -> Optional[Dict]`**
- Get highest confidence mapping for Okta connector
- Returns user override if available
- Otherwise returns best automated mapping

**`get_all_mappings(okta_internal_name: str) -> List[Dict]`**
- Get all mappings for Okta connector
- Ordered by confidence score (descending)
- Useful for presenting user with choices

**`set_user_override(okta_internal_name: str, onelogin_id: int, notes: str) -> None`**
- Record user's preferred connector mapping
- Future lookups will return this override

**`search_onelogin_connectors(name_pattern: str) -> List[Dict]`**
- Search OneLogin connectors by name (SQL LIKE pattern)
- Returns connector details

**`search_okta_connectors(name_pattern: str) -> List[Dict]`**
- Search Okta connectors by name
- Returns connector details

**`get_connector_counts() -> Dict[str, int]`**
- Get counts of connectors and mappings
- Useful for statistics display

**`get_mapping_statistics() -> List[Dict]`**
- Get aggregated mapping statistics
- Grouped by match_type and source

## Files

- **`schema.sql`** - Database schema definition
- **`connector_db.py`** - Main database access layer
- **`load_connectors.py`** - Data loading script (module version)
- **`__init__.py`** - Module exports

## See Also

- [load_connectors_standalone.py](../../../load_connectors_standalone.py) - Standalone loader script
- [query_connectors.py](../../../query_connectors.py) - Example queries
- [secure_settings.py](../secure_settings.py) - Credential management (keyring)
