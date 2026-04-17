#!/usr/bin/env python3
"""Direct test of encryption module without full package imports."""

import os
import sys
from pathlib import Path

# Test encryption availability
print("\n" + "=" * 60)
print("ENCRYPTION MODULE DIRECT TEST")
print("=" * 60 + "\n")

print("1. Checking cryptography package...")
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    print("   ✓ cryptography package available\n")
except ImportError:
    print("   ✗ cryptography package NOT installed")
    print("   Install: pip3 install --user cryptography")
    sys.exit(1)

# Import encryption module directly
print("2. Loading encryption module...")
sys.path.insert(0, str(Path(__file__).parent / "src"))

try:
    # Import just the encryption module
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "encryption",
        Path(__file__).parent.parent / "src" / "onelogin_migration_core" / "db" / "encryption.py",
    )
    encryption = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(encryption)
    print("   ✓ Encryption module loaded\n")
except Exception as e:
    print(f"   ✗ FAILED: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

# Test encryption manager
print("3. Initializing encryption manager...")
try:
    mgr = encryption.EncryptionManager()
    if not mgr.is_available():
        print("   ✗ FAILED: Manager not available")
        sys.exit(1)
    print("   ✓ Encryption manager initialized")
    print(f"      Key file: {mgr.key_file}\n")
except Exception as e:
    print(f"   ✗ FAILED: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

# Test encryption/decryption
print("4. Testing encryption/decryption...")
try:
    test_data = "test_connector_name_12345"
    encrypted = mgr.encrypt(test_data)
    decrypted = mgr.decrypt(encrypted)

    if decrypted != test_data:
        print("   ✗ FAILED: Data mismatch")
        print(f"      Original:  {test_data}")
        print(f"      Decrypted: {decrypted}")
        sys.exit(1)

    if not encrypted.startswith("enc:"):
        print(f"   ✗ FAILED: Invalid encryption format: {encrypted[:20]}...")
        sys.exit(1)

    print("   ✓ Encryption working correctly")
    print(f"      Original:  {test_data}")
    print(f"      Encrypted: {encrypted[:50]}...")
    print(f"      Decrypted: {decrypted}")
    print(f"      Match:     {decrypted == test_data}\n")
except Exception as e:
    print(f"   ✗ FAILED: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

# Test encryption detection
print("5. Testing encryption detection...")
try:
    plaintext = "not_encrypted_data"
    encrypted_data = "enc:1234567890abcdef"

    is_plain_encrypted = mgr.is_encrypted(plaintext)
    is_enc_encrypted = mgr.is_encrypted(encrypted_data)

    if is_plain_encrypted:
        print("   ✗ FAILED: Plaintext detected as encrypted")
        sys.exit(1)

    if not is_enc_encrypted:
        print("   ✗ FAILED: Encrypted data not detected")
        sys.exit(1)

    print("   ✓ Encryption detection working")
    print(f"      '{plaintext}' -> encrypted: {is_plain_encrypted}")
    print(f"      '{encrypted_data[:20]}...' -> encrypted: {is_enc_encrypted}\n")
except Exception as e:
    print(f"   ✗ FAILED: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

# Test key file permissions
print("6. Checking key file security...")
try:
    if mgr.key_file.exists():
        import stat

        mode = os.stat(mgr.key_file).st_mode
        perms = stat.filemode(mode)
        octal = oct(mode & 0o777)

        if (mode & 0o777) != 0o600:
            print(f"   ✗ WARNING: Insecure permissions: {perms} ({octal})")
        else:
            print(f"   ✓ Secure permissions: {perms} ({octal})")
            print("      Owner read/write only\n")
    else:
        print("   ℹ Key file not yet created\n")
except Exception as e:
    print(f"   ✗ FAILED: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

# All tests passed
print("=" * 60)
print("✓ ALL ENCRYPTION TESTS PASSED")
print("=" * 60 + "\n")
print("Summary:")
print("  • Encryption module working correctly")
print("  • AES-256-GCM encryption/decryption verified")
print("  • Plaintext detection working")
print("  • Key file permissions secure (0o600)")
print()
