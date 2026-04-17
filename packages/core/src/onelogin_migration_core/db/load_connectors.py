#!/usr/bin/env python3
"""Load connector data from JSON files into SQLite database.

This script loads:
1. OneLogin connectors from onelogin_api_connectors.json
2. Okta connectors from okta_oin_catalog.json
3. Connector mappings from connector_mapping.json

Usage:
    python -m onelogin_migration_tool.db.load_connectors [data_directory]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

try:
    from .connector_db import ConnectorDatabase, get_default_connector_db
except ImportError:
    # Running as script
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from .db.connector_db import ConnectorDatabase, get_default_connector_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
LOGGER = logging.getLogger(__name__)


def load_onelogin_connectors(db: ConnectorDatabase, json_path: Path) -> int:
    """Load OneLogin connectors from JSON file.

    Args:
        db: ConnectorDatabase instance
        json_path: Path to onelogin_api_connectors.json

    Returns:
        Number of connectors loaded
    """
    LOGGER.info("Loading OneLogin connectors from %s", json_path)

    with open(json_path) as f:
        connectors = json.load(f)

    if not isinstance(connectors, list):
        raise ValueError("Expected JSON array of connectors")

    count = db.insert_onelogin_connectors_bulk(connectors)
    LOGGER.info("Loaded %d OneLogin connectors", count)
    return count


def load_okta_connectors(db: ConnectorDatabase, json_path: Path) -> int:
    """Load Okta connectors from JSON file.

    The Okta OIN catalog has a nested structure. We need to extract the apps.

    Args:
        db: ConnectorDatabase instance
        json_path: Path to okta_oin_catalog.json

    Returns:
        Number of connectors loaded
    """
    LOGGER.info("Loading Okta connectors from %s", json_path)

    with open(json_path) as f:
        data = json.load(f)

    # Extract apps from the catalog structure
    # The structure might be different, so we'll handle various formats
    apps = []

    if isinstance(data, list):
        # Direct array of apps
        apps = data
    elif isinstance(data, dict):
        # Check various common keys
        for key in ["apps", "applications", "integrations", "_embedded", "data"]:
            if key in data:
                potential_apps = data[key]
                if isinstance(potential_apps, list):
                    apps = potential_apps
                    break
                elif isinstance(potential_apps, dict):
                    # Check for nested structure
                    for nested_key in ["apps", "applications", "integrations"]:
                        if nested_key in potential_apps:
                            apps = potential_apps[nested_key]
                            if isinstance(apps, list):
                                break

    if not apps:
        LOGGER.warning("Could not find apps in Okta catalog. Trying to parse as direct array...")
        # Maybe it's just a flat structure - try to use it directly
        if isinstance(data, list):
            apps = data

    LOGGER.info("Found %d potential Okta connectors to load", len(apps))

    count = db.insert_okta_connectors_bulk(apps)
    LOGGER.info("Loaded %d Okta connectors", count)
    return count


def load_connector_mappings(db: ConnectorDatabase, json_path: Path) -> int:
    """Load connector mappings from JSON file.

    Args:
        db: ConnectorDatabase instance
        json_path: Path to connector_mapping.json

    Returns:
        Number of mappings loaded
    """
    LOGGER.info("Loading connector mappings from %s", json_path)

    with open(json_path) as f:
        data = json.load(f)

    # Extract mappings array
    mappings = []
    if isinstance(data, list):
        mappings = data
    elif isinstance(data, dict) and "mapping" in data:
        mappings = data["mapping"]
    else:
        raise ValueError("Could not find mappings in JSON file")

    count = db.insert_connector_mappings_bulk(mappings)
    LOGGER.info("Loaded %d connector mappings", count)
    return count


def load_all_connectors(data_dir: Path, db: Optional[ConnectorDatabase] = None) -> dict[str, int]:
    """Load all connector data from a directory.

    Args:
        data_dir: Directory containing JSON files
        db: ConnectorDatabase instance (or None to use default)

    Returns:
        Dictionary with counts of loaded items
    """
    if db is None:
        db = get_default_connector_db()

    # Initialize schema
    LOGGER.info("Initializing database schema...")
    db.initialize_schema()

    results = {
        "onelogin_connectors": 0,
        "okta_connectors": 0,
        "mappings": 0,
    }

    # Load OneLogin connectors
    onelogin_path = data_dir / "onelogin_api_connectors.json"
    if onelogin_path.exists():
        results["onelogin_connectors"] = load_onelogin_connectors(db, onelogin_path)
    else:
        LOGGER.warning("OneLogin connectors file not found: %s", onelogin_path)

    # Load Okta connectors
    okta_path = data_dir / "okta_oin_catalog.json"
    if okta_path.exists():
        results["okta_connectors"] = load_okta_connectors(db, okta_path)
    else:
        LOGGER.warning("Okta connectors file not found: %s", okta_path)

    # Load connector mappings
    mapping_path = data_dir / "connector_mapping.json"
    if mapping_path.exists():
        results["mappings"] = load_connector_mappings(db, mapping_path)
    else:
        LOGGER.warning("Connector mappings file not found: %s", mapping_path)

    # Print statistics
    LOGGER.info("=" * 60)
    LOGGER.info("LOAD COMPLETE")
    LOGGER.info("=" * 60)
    LOGGER.info("OneLogin connectors loaded: %d", results["onelogin_connectors"])
    LOGGER.info("Okta connectors loaded:     %d", results["okta_connectors"])
    LOGGER.info("Connector mappings loaded:  %d", results["mappings"])

    # Get database statistics
    stats = db.get_connector_counts()
    LOGGER.info("=" * 60)
    LOGGER.info("DATABASE STATISTICS")
    LOGGER.info("=" * 60)
    for key, value in stats.items():
        LOGGER.info("%s: %d", key.replace("_", " ").title(), value)

    mapping_stats = db.get_mapping_statistics()
    if mapping_stats:
        LOGGER.info("=" * 60)
        LOGGER.info("MAPPING BREAKDOWN")
        LOGGER.info("=" * 60)
        for stat in mapping_stats:
            LOGGER.info(
                "%s / %s: %d mappings (avg confidence: %.1f%%)",
                stat["match_type"],
                stat["source"],
                stat["count"],
                stat["avg_confidence"],
            )

    return results


def main() -> int:
    """Main entry point for connector loading script."""
    parser = argparse.ArgumentParser(
        description="Load connector data from JSON files into SQLite database"
    )
    parser.add_argument(
        "data_dir",
        type=Path,
        nargs="?",
        default=Path.home() / "Downloads" / "ol_okta_connectors_analysis",
        help="Directory containing connector JSON files (default: ~/Downloads/ol_okta_connectors_analysis)",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        help="Path to database file (default: ~/.onelogin-migration/connectors.db)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reload even if database already exists",
    )

    args = parser.parse_args()

    if not args.data_dir.exists():
        LOGGER.error("Data directory does not exist: %s", args.data_dir)
        return 1

    # Check if DB already exists
    db = ConnectorDatabase(args.db_path) if args.db_path else get_default_connector_db()

    if db.db_path.exists() and not args.force:
        LOGGER.warning("Database already exists: %s", db.db_path)
        response = input("Reload data? This will replace existing data. [y/N]: ")
        if response.lower() not in ("y", "yes"):
            LOGGER.info("Aborted by user")
            return 0

    try:
        load_all_connectors(args.data_dir, db)
        LOGGER.info("Database ready at: %s", db.db_path)
        return 0
    except Exception as e:
        LOGGER.error("Failed to load connectors: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
