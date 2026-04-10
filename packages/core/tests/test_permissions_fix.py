#!/usr/bin/env python3
"""Test script to verify database permission fixes."""

import os
from pathlib import Path

# Test the permission fix
db_path = Path.home() / ".onelogin-migration" / "connectors.db"

print("=" * 60)
print("Database Permission Test")
print("=" * 60)

# Check before
if db_path.exists():
    before_perms = oct(os.stat(db_path).st_mode & 0o777)
    print(f"\nBefore: {db_path}")
    print(f"  Permissions: {before_perms}")
else:
    print(f"\nDatabase not found: {db_path}")
    exit(1)

# Import and initialize database (this will fix permissions)
import sys

sys.path.insert(0, str(Path(__file__).parent / "src" / "onelogin_migration_tool" / "db"))

import logging

from onelogin_migration_core.db.connector_db import ConnectorDatabase

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize database (triggers permission fix)
print("\nInitializing ConnectorDatabase...")
db = ConnectorDatabase(db_path)

# Check after
after_perms = oct(os.stat(db_path).st_mode & 0o777)
print(f"\nAfter: {db_path}")
print(f"  Permissions: {after_perms}")

# Verify permissions are secure
expected_mode = 0o600
actual_mode = os.stat(db_path).st_mode & 0o777

if actual_mode == expected_mode:
    print(f"\n✓ SUCCESS: Permissions correctly set to {oct(expected_mode)}")
    print("  - Owner: read/write")
    print("  - Group: no access")
    print("  - Others: no access")
else:
    print(f"\n✗ FAILURE: Expected {oct(expected_mode)}, got {oct(actual_mode)}")
    exit(1)

print("\n" + "=" * 60)
print("Permission fix verified successfully!")
print("=" * 60)
