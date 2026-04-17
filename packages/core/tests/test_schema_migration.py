#!/usr/bin/env python3
"""Test database schema migration with new telemetry and refresh tables."""

import sqlite3
from pathlib import Path


def main():
    db_path = Path.home() / ".onelogin-migration" / "connectors.db"
    schema_path = Path("src/onelogin_migration_tool/db/schema.sql")

    print("=" * 80)
    print("DATABASE SCHEMA MIGRATION TEST")
    print("=" * 80)
    print(f"Database: {db_path}")
    print(f"Schema:   {schema_path}")
    print()

    # Read schema
    if not schema_path.exists():
        print(f"ERROR: Schema file not found: {schema_path}")
        return 1

    schema_sql = schema_path.read_text()
    print(f"Schema loaded: {len(schema_sql)} characters")
    print()

    # Connect to database
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    print("Applying schema updates...")
    try:
        conn.executescript(schema_sql)
        conn.commit()
        print("✅ Schema applied successfully")
    except Exception as e:
        print(f"❌ Schema application failed: {e}")
        return 1

    print()
    print("=" * 80)
    print("VERIFYING NEW TABLES")
    print("=" * 80)

    # Check for new tables
    new_tables = [
        "connector_refresh_log",
        "telemetry_settings",
        "connector_telemetry",
        "error_telemetry",
        "migration_scenario_telemetry",
    ]

    for table in new_tables:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"✅ {table:35} - {count:4} records")

    print()
    print("=" * 80)
    print("VERIFYING NEW VIEWS")
    print("=" * 80)

    new_views = [
        "last_refresh",
        "connector_telemetry_summary",
        "error_pattern_summary",
        "scenario_effectiveness",
    ]

    for view in new_views:
        try:
            cursor = conn.execute(f"SELECT * FROM {view} LIMIT 1")
            print(f"✅ {view:35} - accessible")
        except Exception as e:
            print(f"❌ {view:35} - error: {e}")

    print()
    print("=" * 80)
    print("TESTING TELEMETRY CONSENT RECORDING")
    print("=" * 80)

    # Test consent recording
    import uuid
    from datetime import datetime

    installation_id = str(uuid.uuid4())
    try:
        conn.execute(
            """
            INSERT INTO telemetry_settings
            (enabled, user_consent_date, anonymized, installation_id)
            VALUES (1, ?, 1, ?)
        """,
            (datetime.now().isoformat(), installation_id),
        )
        conn.commit()
        print(f"✅ Consent recorded (ID: {installation_id[:8]}...)")
    except Exception as e:
        print(f"⚠️  Consent already recorded or error: {e}")

    # Verify consent
    cursor = conn.execute(
        """
        SELECT enabled, user_consent_date, installation_id
        FROM telemetry_settings
        WHERE enabled = 1
    """
    )
    row = cursor.fetchone()
    if row:
        print("✅ Consent verified:")
        print(f"   - Enabled: {row['enabled']}")
        print(f"   - Date: {row['user_consent_date']}")
        print(f"   - ID: {row['installation_id'][:8]}...")
    else:
        print("❌ No consent found")

    print()
    print("=" * 80)
    print("DATABASE STATISTICS")
    print("=" * 80)

    # Get all table counts
    cursor = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """
    )
    tables = [row["name"] for row in cursor.fetchall()]

    for table in tables:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"  {table:35} {count:6} records")

    conn.close()

    print()
    print("=" * 80)
    print("✅ MIGRATION TEST COMPLETE")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
