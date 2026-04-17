#!/usr/bin/env python3
"""Test the database encryption migration functionality."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from onelogin_migration_core.db.encryption import (
    get_encryption_manager,
    is_encryption_available,
    migrate_database_encryption,
)
from onelogin_migration_core.db.telemetry import get_telemetry_manager


def test_migration():
    """Test end-to-end migration."""
    print("\n" + "=" * 60)
    print("DATABASE ENCRYPTION MIGRATION TEST")
    print("=" * 60 + "\n")

    # Check encryption available
    print("1. Checking encryption availability...")
    if not is_encryption_available():
        print("   ✗ FAILED: Encryption not available")
        print("   Install: pip install cryptography")
        return False
    print("   ✓ Encryption available\n")

    # Check encryption manager initializes
    print("2. Initializing encryption manager...")
    try:
        mgr = get_encryption_manager()
        if not mgr.is_available():
            print("   ✗ FAILED: Manager not available")
            return False
        print("   ✓ Encryption manager initialized\n")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        return False

    # Test encryption/decryption
    print("3. Testing encryption/decryption...")
    try:
        test_data = "test_connector_name_12345"
        encrypted = mgr.encrypt(test_data)
        decrypted = mgr.decrypt(encrypted)

        if decrypted != test_data:
            print("   ✗ FAILED: Data mismatch")
            print(f"      Original:  {test_data}")
            print(f"      Decrypted: {decrypted}")
            return False

        if not encrypted.startswith("enc:"):
            print(f"   ✗ FAILED: Invalid encryption format: {encrypted[:20]}...")
            return False

        print("   ✓ Encryption working")
        print(f"      Original:  {test_data}")
        print(f"      Encrypted: {encrypted[:40]}...")
        print(f"      Decrypted: {decrypted}\n")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        return False

    # Run migration
    print("4. Running database migration...")
    try:
        result = migrate_database_encryption()

        if result["status"] == "error":
            print(f"   ✗ FAILED: {result['message']}")
            return False

        print("   ✓ Migration completed successfully")
        print("\n   Results:")
        print(f"      Records encrypted:           {result['encrypted']}")
        print(f"      Records skipped:             {result['skipped']}")
        print(f"      Total processed:             {result['total']}\n")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False

    # Test telemetry manager uses encryption
    print("5. Testing telemetry manager integration...")
    try:
        tel_mgr = get_telemetry_manager()

        # Test hashing with encryption
        test_identifier = "test_app_connector"
        hashed = tel_mgr._hash_identifier(test_identifier)

        if not hashed.startswith("enc:"):
            print("   ✗ FAILED: Telemetry not using encryption")
            print(f"      Result: {hashed[:40]}...")
            return False

        print("   ✓ Telemetry manager using encryption")
        print(f"      Input:     {test_identifier}")
        print(f"      Encrypted: {hashed[:40]}...\n")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False

    # All tests passed
    print("=" * 60)
    print("✓ ALL TESTS PASSED - MIGRATION SUCCESSFUL")
    print("=" * 60 + "\n")
    return True


if __name__ == "__main__":
    success = test_migration()
    sys.exit(0 if success else 1)
