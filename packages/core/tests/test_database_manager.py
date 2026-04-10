#!/usr/bin/env python3
"""Test DatabaseManager with split catalog/user architecture."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from onelogin_migration_core.db import get_database_manager


def test_database_manager():
    """Test DatabaseManager functionality."""
    print("\n" + "=" * 60)
    print("DATABASE MANAGER TEST")
    print("=" * 60 + "\n")

    try:
        # Get database manager
        print("1. Initializing DatabaseManager...")
        db = get_database_manager()
        print(f"   ✓ Catalog database: {db.catalog_path}")
        print(f"   ✓ User database:    {db.user_path}\n")

        # Test catalog queries
        print("2. Testing catalog queries...")

        # Query OneLogin connectors
        onelogin_count = db.catalog_conn.execute(
            "SELECT COUNT(*) FROM onelogin_connectors"
        ).fetchone()[0]
        print(f"   ✓ OneLogin connectors: {onelogin_count:,}")

        # Query Okta connectors
        okta_count = db.catalog_conn.execute("SELECT COUNT(*) FROM okta_connectors").fetchone()[0]
        print(f"   ✓ Okta connectors:     {okta_count:,}")

        # Query mappings
        mapping_count = db.catalog_conn.execute(
            "SELECT COUNT(*) FROM connector_mappings"
        ).fetchone()[0]
        print(f"   ✓ Connector mappings:  {mapping_count:,}\n")

        # Test specific queries
        print("3. Testing DatabaseManager methods...")

        # Search OneLogin connectors
        results = db.search_onelogin_connectors("salesforce", limit=3)
        print(f"   ✓ Search 'salesforce': Found {len(results)} results")
        for row in results:
            print(f"      - {row['name']}")

        # Get mapping
        mapping = db.get_connector_mapping("salesforce")
        if mapping:
            print("\n   ✓ Mapping for 'salesforce':")
            print(f"      OneLogin: {mapping.get('onelogin_name')}")
            print(f"      Confidence: {mapping.get('confidence_score')}%")
            print(f"      Match type: {mapping.get('match_type')}")

        print()

        # Test user database
        print("4. Testing user database...")
        user_count = db.user_conn.execute("SELECT COUNT(*) FROM connector_telemetry").fetchone()[0]
        print(f"   ✓ Telemetry events: {user_count:,}\n")

        # Test user override
        print("5. Testing user override...")
        db.save_user_override("salesforce", 123, "Test override")
        override = db.get_user_override("salesforce")
        if override:
            print("   ✓ Override saved and retrieved")
            print(f"      OneLogin ID: {override['preferred_onelogin_id']}")
            print(f"      Notes: {override['notes']}")
            # Clean up
            db.delete_user_override("salesforce")
            print("   ✓ Override deleted\n")

        # All tests passed
        print("=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60 + "\n")

        print("Summary:")
        print(f"  • Catalog database: {db.catalog_path.stat().st_size / 1024 / 1024:.2f} MB")
        print(f"  • User database:    {db.user_path.stat().st_size / 1024:.2f} KB")
        print(f"  • Total connectors: {onelogin_count + okta_count:,}")
        print(f"  • Total mappings:   {mapping_count:,}")
        print()

        return True

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        # Clean up
        if "db" in locals():
            db.close()


if __name__ == "__main__":
    success = test_database_manager()
    sys.exit(0 if success else 1)
