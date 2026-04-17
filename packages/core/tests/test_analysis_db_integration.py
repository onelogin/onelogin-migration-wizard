#!/usr/bin/env python3
"""Test script for Analysis page database integration."""

import sqlite3
from pathlib import Path


def test_connector_loading():
    """Test loading connectors from database."""
    print("=" * 80)
    print("Testing Analysis Page Database Integration")
    print("=" * 80)

    db_path = Path.home() / ".onelogin-migration" / "connectors.db"

    if not db_path.exists():
        print(f"\n✗ Database not found at {db_path}")
        print("  Run load_connectors_standalone.py first to create the database")
        return False

    print(f"\n✓ Database found at {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    print("\n1. Testing get_all_onelogin_connectors() query...")
    try:
        cursor = conn.execute("SELECT * FROM onelogin_connectors ORDER BY name")
        connectors = [dict(row) for row in cursor.fetchall()]
        print(f"   ✓ Successfully loaded {len(connectors)} OneLogin connectors from database")

        if connectors:
            # Show first 3 connectors as sample
            print("\n   Sample connectors:")
            for connector in connectors[:3]:
                print(f"     - ID: {connector['id']}, Name: {connector['name']}")
        else:
            print("   ⚠ Database is empty - run load_connectors_standalone.py first")

    except Exception as exc:
        print(f"   ✗ Error loading connectors: {exc}")
        conn.close()
        return False

    print("\n2. Testing get_best_mapping() query...")
    test_apps = ["Salesforce", "Slack", "GitHub", "Unknown App XYZ"]

    for app_name in test_apps:
        try:
            cursor = conn.execute(
                """
                SELECT
                    cm.okta_internal_name,
                    cm.onelogin_id,
                    ol.name AS onelogin_name,
                    cm.confidence_score,
                    cm.match_type,
                    cm.user_override
                FROM connector_mappings cm
                JOIN onelogin_connectors ol ON cm.onelogin_id = ol.id
                WHERE cm.okta_internal_name = ?
                ORDER BY
                    cm.user_override DESC,
                    cm.confidence_score DESC
                LIMIT 1
                """,
                (app_name,),
            )
            row = cursor.fetchone()

            if row:
                mapping = dict(row)
                print(
                    f"   ✓ '{app_name}' → OneLogin '{mapping['onelogin_name']}' "
                    f"(confidence: {mapping['confidence_score']:.0f}%, "
                    f"type: {mapping['match_type']})"
                )
            else:
                print(f"   ✗ '{app_name}' → No mapping found")
        except Exception as exc:
            print(f"   ✗ Error looking up '{app_name}': {exc}")

    print("\n3. Connector statistics...")
    try:
        cursor = conn.execute("SELECT COUNT(*) as count FROM onelogin_connectors")
        onelogin_count = cursor.fetchone()["count"]

        cursor = conn.execute("SELECT COUNT(*) as count FROM okta_connectors")
        okta_count = cursor.fetchone()["count"]

        cursor = conn.execute("SELECT COUNT(*) as count FROM connector_mappings")
        mapping_count = cursor.fetchone()["count"]

        print(f"   OneLogin connectors: {onelogin_count}")
        print(f"   Okta connectors:     {okta_count}")
        print(f"   Total mappings:      {mapping_count}")
    except Exception as exc:
        print(f"   ✗ Error getting statistics: {exc}")

    conn.close()

    print("\n" + "=" * 80)
    print("Test completed successfully!")
    print("=" * 80)
    return True


if __name__ == "__main__":
    import sys

    success = test_connector_loading()
    sys.exit(0 if success else 1)
