#!/usr/bin/env python3
"""Build catalog database for distribution.

This script creates the read-only catalog database (catalog.db) that will be
bundled in the executable. It copies connector catalogs and mappings from the
existing database.

Usage:
    python scripts/build_catalog_db.py [--source PATH] [--output PATH]
"""

import argparse
import sqlite3
import sys
from pathlib import Path


def build_catalog_database(source_db: Path, output_db: Path, force: bool = False):
    """Build read-only catalog database from source database.

    Args:
        source_db: Path to source database (connectors.db)
        output_db: Path to output catalog database
        force: Overwrite existing output database

    Returns:
        True if successful, False otherwise
    """
    # Validate source
    if not source_db.exists():
        print(f"Error: Source database not found: {source_db}", file=sys.stderr)
        return False

    # Check output
    if output_db.exists() and not force:
        print(f"Error: Output database already exists: {output_db}", file=sys.stderr)
        print("Use --force to overwrite", file=sys.stderr)
        return False

    print(f"Building catalog database...")
    print(f"  Source: {source_db}")
    print(f"  Output: {output_db}")
    print()

    # Ensure output directory exists
    output_db.parent.mkdir(parents=True, exist_ok=True)

    # Connect to both databases
    try:
        source_conn = sqlite3.connect(source_db)
        dest_conn = sqlite3.connect(output_db)
    except sqlite3.Error as e:
        print(f"Error connecting to database: {e}", file=sys.stderr)
        return False

    try:
        # Load and execute catalog schema
        schema_path = Path(__file__).parent.parent / "src" / "onelogin_migration_tool" / "db" / "catalog_schema.sql"
        if not schema_path.exists():
            print(f"Error: Schema file not found: {schema_path}", file=sys.stderr)
            return False

        print("Creating schema...")
        schema_sql = schema_path.read_text()
        dest_conn.executescript(schema_sql)
        print("  ✓ Schema created\n")

        # Tables to copy
        tables = [
            ('onelogin_connectors', 'OneLogin connectors'),
            ('okta_connectors', 'Okta connectors'),
            ('connector_mappings', 'Connector mappings')
        ]

        total_rows = 0

        for table_name, description in tables:
            print(f"Copying {description}...")

            try:
                # Get all rows from source
                cursor = source_conn.execute(f"SELECT * FROM {table_name}")
                rows = cursor.fetchall()

                if not rows:
                    print(f"  ⚠ Warning: No data found in {table_name}")
                    continue

                # Get column names
                columns = [desc[0] for desc in cursor.description]
                placeholders = ','.join(['?' for _ in columns])
                columns_str = ','.join(columns)

                # Insert into destination
                dest_conn.executemany(
                    f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})",
                    rows
                )

                # Verify count
                count = dest_conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                print(f"  ✓ Copied {count:,} rows")
                total_rows += count

            except sqlite3.Error as e:
                print(f"  ✗ Error copying {table_name}: {e}", file=sys.stderr)
                return False

        print()

        # Insert catalog version metadata
        print("Adding catalog metadata...")
        onelogin_count = dest_conn.execute("SELECT COUNT(*) FROM onelogin_connectors").fetchone()[0]
        okta_count = dest_conn.execute("SELECT COUNT(*) FROM okta_connectors").fetchone()[0]
        mapping_count = dest_conn.execute("SELECT COUNT(*) FROM connector_mappings").fetchone()[0]

        dest_conn.execute("""
            INSERT OR REPLACE INTO catalog_version
            (version, onelogin_count, okta_count, mapping_count, description)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "0.1.4",
            onelogin_count,
            okta_count,
            mapping_count,
            "Initial catalog for PyInstaller distribution"
        ))

        # Commit and close
        dest_conn.commit()
        print("  ✓ Metadata added\n")

        # Get file size
        file_size = output_db.stat().st_size / 1024 / 1024

        print("="* 60)
        print("✓ CATALOG DATABASE BUILD COMPLETE")
        print("="* 60)
        print(f"Location: {output_db}")
        print(f"Size:     {file_size:.2f} MB")
        print(f"Rows:     {total_rows:,} total")
        print(f"  - OneLogin connectors: {onelogin_count:,}")
        print(f"  - Okta connectors:     {okta_count:,}")
        print(f"  - Connector mappings:  {mapping_count:,}")
        print()

        # Make read-only
        output_db.chmod(0o444)
        print("✓ Catalog database is now read-only (0o444)")
        print()

        return True

    except Exception as e:
        print(f"\nError during build: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False

    finally:
        source_conn.close()
        dest_conn.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Build catalog database for distribution"
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.home() / ".onelogin-migration" / "connectors.db",
        help="Source database path (default: ~/.onelogin-migration/connectors.db)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent.parent / "src" / "onelogin_migration_tool" / "resources" / "catalog.db",
        help="Output catalog database path"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output database"
    )

    args = parser.parse_args()

    success = build_catalog_database(
        source_db=args.source,
        output_db=args.output,
        force=args.force
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
