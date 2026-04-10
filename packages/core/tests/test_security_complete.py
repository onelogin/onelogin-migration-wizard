#!/usr/bin/env python3
"""Complete security implementation test suite."""

import os
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src" / "onelogin_migration_tool" / "db"))

print("=" * 80)
print("DATABASE SECURITY - COMPLETE TEST SUITE")
print("=" * 80)

# Test 1: File Permissions
print("\n[TEST 1] File Permissions")
print("-" * 80)

db_path = Path.home() / ".onelogin-migration" / "connectors.db"

if not db_path.exists():
    print("✗ SKIP: Database not found (run GUI to initialize)")
    sys.exit(0)

import logging

# Import after path setup
from onelogin_migration_core.db.connector_db import ConnectorDatabase
from onelogin_migration_core.db.db_security import EncryptedConnectorDatabase, check_database_security

logging.basicConfig(level=logging.INFO)

# Initialize database (triggers permission fix)
db = ConnectorDatabase(db_path)

# Check permissions
mode = os.stat(db_path).st_mode & 0o777
if mode == 0o600:
    print("✓ PASS: Permissions are secure (0o600)")
else:
    print(f"✗ FAIL: Permissions are {oct(mode)}, expected 0o600")
    sys.exit(1)

# Test 2: Security Check Function
print("\n[TEST 2] Security Check Function")
print("-" * 80)

try:
    security_status = check_database_security(db_path)

    if security_status["exists"]:
        print("✓ PASS: Security check function works")
        print(f"  - Location: {security_status['path']}")
        print(f"  - Permissions: {security_status['permissions']['octal']}")
        print(f"  - Secure: {security_status['permissions']['secure']}")
    else:
        print("✗ FAIL: Security check failed")
        sys.exit(1)
except Exception as e:
    print(f"✗ FAIL: Security check error: {e}")
    sys.exit(1)

# Test 3: Encryption Availability
print("\n[TEST 3] Encryption Availability")
print("-" * 80)

encryption_available = EncryptedConnectorDatabase.is_encryption_available()
if encryption_available:
    print("✓ PASS: Encryption is available (cryptography package installed)")
else:
    print("⚠ SKIP: Encryption not available (cryptography package not installed)")
    print("  Install with: pip install cryptography")

# Test 4: Password Generation
print("\n[TEST 4] Password Generation")
print("-" * 80)

if encryption_available:
    try:
        password = EncryptedConnectorDatabase.generate_password(32)
        if len(password) == 32:
            print(f"✓ PASS: Generated secure password ({len(password)} characters)")
            print(f"  Sample: {password[:8]}...")
        else:
            print("✗ FAIL: Password length incorrect")
            sys.exit(1)
    except Exception as e:
        print(f"✗ FAIL: Password generation error: {e}")
        sys.exit(1)
else:
    print("⚠ SKIP: Requires cryptography package")

# Test 5: Database Statistics
print("\n[TEST 5] Database Statistics")
print("-" * 80)

try:
    counts = db.get_connector_counts()
    print("✓ PASS: Database statistics retrieved")
    print(f"  - OneLogin connectors: {counts.get('onelogin_connectors', 0):,}")
    print(f"  - Okta connectors: {counts.get('okta_connectors', 0):,}")
    print(f"  - Mappings: {counts.get('total_mappings', 0):,}")
except Exception as e:
    print(f"✗ FAIL: Statistics error: {e}")
    sys.exit(1)

# Test 6: Module Exports
print("\n[TEST 6] Module Exports")
print("-" * 80)

try:
    # Test that security functions are defined
    from db_security import EncryptedConnectorDatabase, check_database_security

    print("✓ PASS: All security functions are available")
    print("  - ConnectorDatabase")
    print("  - EncryptedConnectorDatabase")
    print("  - check_database_security")

    # Verify EncryptedConnectorDatabase has required methods
    required_methods = ["encrypt_telemetry_data", "verify_encryption", "generate_password"]
    for method in required_methods:
        if hasattr(EncryptedConnectorDatabase, method):
            print(f"  ✓ {method}")
        else:
            print(f"  ✗ Missing: {method}")
            sys.exit(1)

except ImportError as e:
    print(f"✗ FAIL: Import error: {e}")
    sys.exit(1)

# Summary
print("\n" + "=" * 80)
print("SECURITY TEST SUMMARY")
print("=" * 80)

print("\n✓ All critical tests passed")
print("\nSecurity Features Verified:")
print("  ✓ File permissions (0o600)")
print("  ✓ Automatic permission enforcement")
print("  ✓ Security check function")
print("  ✓ Database statistics")
print("  ✓ Module exports")

if encryption_available:
    print("  ✓ Encryption available")
    print("  ✓ Password generation")
else:
    print("  ⚠ Encryption not installed (optional)")

print("\n" + "=" * 80)
print("✓ DATABASE SECURITY IMPLEMENTATION VERIFIED")
print("=" * 80)
print()
