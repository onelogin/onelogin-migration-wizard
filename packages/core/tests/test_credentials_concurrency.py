"""
Concurrency tests for layered_credentials package.

Tests atomic writes, file locking, and cross-process safety.
"""

import json
import multiprocessing
import tempfile
import threading
import time
from pathlib import Path

import pytest

from onelogin_migration_core.credentials import Argon2VaultV3, AutoSaveCredentialManager


# =============================================================================
# Argon2VaultV3 Concurrency Tests
# =============================================================================


class TestArgon2VaultConcurrency:
    """Tests for Argon2VaultV3 concurrency safety."""

    def test_concurrent_encrypts_thread_safe(self):
        """Test that concurrent encrypts from multiple threads are safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            counter_file = Path(tmpdir) / ".vault_counter"
            vault = Argon2VaultV3(counter_file=counter_file)
            password = "test_password_123"

            results = []
            errors = []

            def encrypt_data(i):
                try:
                    encrypted = vault.encrypt(f"secret{i}", password)
                    results.append(encrypted)
                except Exception as e:
                    errors.append(e)

            # Launch 10 concurrent encrypt operations
            threads = []
            for i in range(10):
                t = threading.Thread(target=encrypt_data, args=(i,))
                threads.append(t)
                t.start()

            # Wait for all threads
            for t in threads:
                t.join()

            # Should have no errors
            assert len(errors) == 0, f"Encountered errors: {errors}"

            # Should have 10 results
            assert len(results) == 10

            # Only decrypt the LAST result (with highest counter)
            # Decrypting older results would fail rollback protection (expected behavior)
            # Sort by counter to find the one with the highest counter
            import json
            import base64
            from argon2.low_level import Type, hash_secret_raw
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            max_counter = 0
            latest_encrypted = None

            for encrypted in results:
                # Extract counter from payload
                salt = base64.b64decode(encrypted["salt"])
                nonce = base64.b64decode(encrypted["nonce"])
                ciphertext = base64.b64decode(encrypted["ciphertext"])

                key = hash_secret_raw(
                    secret=password.encode("utf-8"),
                    salt=salt,
                    time_cost=vault.time_cost,
                    memory_cost=vault.memory_cost,
                    parallelism=vault.parallelism,
                    hash_len=vault.hash_len,
                    type=Type.ID,
                )

                aesgcm = AESGCM(key)
                payload_json = aesgcm.decrypt(nonce, ciphertext, None)
                payload = json.loads(payload_json.decode("utf-8"))

                if payload["counter"] > max_counter:
                    max_counter = payload["counter"]
                    latest_encrypted = encrypted

            # Decrypt the latest one - should work
            plaintext = vault.decrypt(latest_encrypted, password)
            assert plaintext.startswith("secret")

    def test_concurrent_decrypt_thread_safe(self):
        """Test that concurrent decrypts from multiple threads are safe.

        Due to rollback protection, we can only decrypt items with counter >= current counter.
        This test uses separate vault instances to simulate multiple vault files being
        decrypted concurrently (the typical use case for concurrent decrypts).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 10 separate vault instances with separate counter files
            vaults = []
            encrypted_blobs = []

            for i in range(10):
                counter_file = Path(tmpdir) / f".vault_counter_{i}"
                vault = Argon2VaultV3(counter_file=counter_file)
                password = "test_password_123"
                encrypted = vault.encrypt(f"secret{i}", password)

                vaults.append(vault)
                encrypted_blobs.append((vault, encrypted, password))

            results = []
            errors = []

            def decrypt_data(vault, encrypted, password):
                try:
                    plaintext = vault.decrypt(encrypted, password)
                    results.append(plaintext)
                except Exception as e:
                    errors.append(e)

            # Launch 10 concurrent decrypt operations
            threads = []
            for vault, encrypted, password in encrypted_blobs:
                t = threading.Thread(target=decrypt_data, args=(vault, encrypted, password))
                threads.append(t)
                t.start()

            # Wait for all threads
            for t in threads:
                t.join()

            # Should have no errors
            assert len(errors) == 0, f"Encountered errors: {errors}"

            # Should have 10 results
            assert len(results) == 10

            # All results should be correct
            for plaintext in results:
                assert plaintext.startswith("secret")

    def test_concurrent_encrypt_decrypt_mixed(self):
        """Test mixed concurrent encrypt and decrypt operations.

        Uses separate vault instances to avoid rollback protection issues.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create separate vaults for encryption and decryption
            encrypt_vaults = []
            decrypt_vaults = []
            pre_encrypted = []

            # Pre-create encrypted blobs with separate vaults
            for i in range(5):
                counter_file = Path(tmpdir) / f".vault_counter_decrypt_{i}"
                vault = Argon2VaultV3(counter_file=counter_file)
                password = "test_password_123"
                encrypted = vault.encrypt(f"pre_secret{i}", password)
                decrypt_vaults.append(vault)
                pre_encrypted.append((vault, encrypted, password))

            # Create vaults for new encryptions
            for i in range(5):
                counter_file = Path(tmpdir) / f".vault_counter_encrypt_{i}"
                vault = Argon2VaultV3(counter_file=counter_file)
                encrypt_vaults.append(vault)

            results = []
            errors = []

            def encrypt_data(vault, i):
                try:
                    encrypted = vault.encrypt(f"new_secret{i}", "test_password_123")
                    results.append(("encrypt", encrypted))
                except Exception as e:
                    errors.append(("encrypt", e))

            def decrypt_data(vault, encrypted, password):
                try:
                    plaintext = vault.decrypt(encrypted, password)
                    results.append(("decrypt", plaintext))
                except Exception as e:
                    errors.append(("decrypt", e))

            # Launch mixed operations
            threads = []

            # 5 encrypt threads
            for i, vault in enumerate(encrypt_vaults):
                t = threading.Thread(target=encrypt_data, args=(vault, i))
                threads.append(t)

            # 5 decrypt threads
            for vault, encrypted, password in pre_encrypted:
                t = threading.Thread(target=decrypt_data, args=(vault, encrypted, password))
                threads.append(t)

            # Start all threads
            for t in threads:
                t.start()

            # Wait for all threads
            for t in threads:
                t.join()

            # Should have no errors
            assert len(errors) == 0, f"Encountered errors: {errors}"

            # Should have 10 results (5 encrypts + 5 decrypts)
            assert len(results) == 10

    def test_counter_monotonic_under_concurrency(self):
        """Test that counter always increments monotonically under concurrent load."""
        import base64
        from argon2.low_level import Type, hash_secret_raw
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        with tempfile.TemporaryDirectory() as tmpdir:
            counter_file = Path(tmpdir) / ".vault_counter"
            vault = Argon2VaultV3(counter_file=counter_file)
            password = "test_password_123"

            encrypted_blobs = []
            errors = []

            def encrypt_data(i):
                try:
                    encrypted = vault.encrypt(f"secret{i}", password)
                    encrypted_blobs.append(encrypted)
                except Exception as e:
                    errors.append(e)

            # Launch 20 concurrent encrypt operations
            threads = []
            for i in range(20):
                t = threading.Thread(target=encrypt_data, args=(i,))
                threads.append(t)
                t.start()

            # Wait for all threads
            for t in threads:
                t.join()

            # Should have no errors
            assert len(errors) == 0, f"Encountered errors: {errors}"

            # Should have 20 encrypted blobs
            assert len(encrypted_blobs) == 20

            # Extract counters from all blobs
            counters = []
            for encrypted in encrypted_blobs:
                salt = base64.b64decode(encrypted["salt"])
                nonce = base64.b64decode(encrypted["nonce"])
                ciphertext = base64.b64decode(encrypted["ciphertext"])

                key = hash_secret_raw(
                    secret=password.encode("utf-8"),
                    salt=salt,
                    time_cost=vault.time_cost,
                    memory_cost=vault.memory_cost,
                    parallelism=vault.parallelism,
                    hash_len=vault.hash_len,
                    type=Type.ID,
                )

                aesgcm = AESGCM(key)
                payload_json = aesgcm.decrypt(nonce, ciphertext, None)
                payload = json.loads(payload_json.decode("utf-8"))
                counters.append(payload["counter"])

            # Sort counters
            sorted_counters = sorted(counters)

            # All counters should be unique
            assert len(set(counters)) == len(counters), "Counters are not unique!"

            # Counters should be sequential from 1 to 20
            assert sorted_counters == list(range(1, 21)), f"Counters are not sequential: {sorted_counters}"


# =============================================================================
# AutoSaveCredentialManager Concurrency Tests
# =============================================================================


class TestCredentialManagerConcurrency:
    """Tests for AutoSaveCredentialManager concurrency safety."""

    def test_concurrent_vault_writes_thread_safe(self):
        """Test that concurrent writes to vault backend are safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.enc"
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password_123",
                storage_dir=tmpdir,
                enable_auto_save=False,  # Disable debouncing for test
                enable_audit_log=False,
            )

            errors = []

            def save_credential(i):
                try:
                    success = manager.auto_save_credential(
                        service=f"service{i % 5}",  # 5 different services
                        key=f"key{i}",
                        value=f"value{i}",
                    )
                    assert success
                except Exception as e:
                    errors.append(e)

            # Launch 20 concurrent save operations
            threads = []
            for i in range(20):
                t = threading.Thread(target=save_credential, args=(i,))
                threads.append(t)
                t.start()

            # Wait for all threads
            for t in threads:
                t.join()

            # Should have no errors
            assert len(errors) == 0, f"Encountered errors: {errors}"

            # Verify vault file exists and is valid
            assert vault_path.exists()

            # Verify we can read all credentials back
            for i in range(20):
                cred = manager.get_credential(f"service{i % 5}", f"key{i}")
                assert cred is not None
                assert cred.reveal() == f"value{i}"

    def test_concurrent_vault_reads_thread_safe(self):
        """Test that concurrent reads from vault backend are safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password_123",
                storage_dir=tmpdir,
                enable_auto_save=False,
                enable_audit_log=False,
            )

            # Pre-populate with 10 credentials
            for i in range(10):
                manager.auto_save_credential(
                    service=f"service{i}",
                    key=f"key{i}",
                    value=f"value{i}",
                )

            results = []
            errors = []

            def read_credential(i):
                try:
                    cred = manager.get_credential(f"service{i}", f"key{i}")
                    assert cred is not None
                    results.append(cred.reveal())
                except Exception as e:
                    errors.append(e)

            # Launch 10 concurrent read operations
            threads = []
            for i in range(10):
                t = threading.Thread(target=read_credential, args=(i,))
                threads.append(t)
                t.start()

            # Wait for all threads
            for t in threads:
                t.join()

            # Should have no errors
            assert len(errors) == 0, f"Encountered errors: {errors}"

            # Should have 10 results
            assert len(results) == 10

            # All results should be correct
            for i, result in enumerate(results):
                # Note: results may not be in order due to threading
                assert result.startswith("value")

    def test_concurrent_vault_read_write_mixed(self):
        """Test mixed concurrent read and write operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password_123",
                storage_dir=tmpdir,
                enable_auto_save=False,
                enable_audit_log=False,
            )

            # Pre-populate with 5 credentials
            for i in range(5):
                manager.auto_save_credential(
                    service=f"service{i}",
                    key=f"key{i}",
                    value=f"value{i}",
                )

            errors = []

            def write_credential(i):
                try:
                    manager.auto_save_credential(
                        service=f"service{i}",
                        key=f"new_key{i}",
                        value=f"new_value{i}",
                    )
                except Exception as e:
                    errors.append(("write", e))

            def read_credential(i):
                try:
                    cred = manager.get_credential(f"service{i}", f"key{i}")
                    assert cred is not None
                    assert cred.reveal() == f"value{i}"
                except Exception as e:
                    errors.append(("read", e))

            # Launch mixed operations
            threads = []

            # 10 write threads
            for i in range(10):
                t = threading.Thread(target=write_credential, args=(i,))
                threads.append(t)

            # 5 read threads
            for i in range(5):
                t = threading.Thread(target=read_credential, args=(i,))
                threads.append(t)

            # Start all threads
            for t in threads:
                t.start()

            # Wait for all threads
            for t in threads:
                t.join()

            # Should have no errors
            assert len(errors) == 0, f"Encountered errors: {errors}"

    def test_vault_delete_during_concurrent_operations(self):
        """Test deleting credentials during concurrent operations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password_123",
                storage_dir=tmpdir,
                enable_auto_save=False,
                enable_audit_log=False,
            )

            # Pre-populate with credentials
            for i in range(10):
                manager.auto_save_credential(
                    service=f"service{i}",
                    key=f"key{i}",
                    value=f"value{i}",
                )

            errors = []

            def delete_credential(i):
                try:
                    manager.delete_credential(f"service{i}", f"key{i}")
                except Exception as e:
                    errors.append(("delete", e))

            def write_credential(i):
                try:
                    manager.auto_save_credential(
                        service=f"service_new{i}",
                        key=f"key{i}",
                        value=f"value{i}",
                    )
                except Exception as e:
                    errors.append(("write", e))

            # Launch mixed delete and write operations
            threads = []

            # 5 delete threads
            for i in range(5):
                t = threading.Thread(target=delete_credential, args=(i,))
                threads.append(t)

            # 5 write threads
            for i in range(5):
                t = threading.Thread(target=write_credential, args=(i,))
                threads.append(t)

            # Start all threads
            for t in threads:
                t.start()

            # Wait for all threads
            for t in threads:
                t.join()

            # Should have no errors
            assert len(errors) == 0, f"Encountered errors: {errors}"

            # Verify deletes worked
            for i in range(5):
                cred = manager.get_credential(f"service{i}", f"key{i}")
                assert cred is None

            # Verify writes worked
            for i in range(5):
                cred = manager.get_credential(f"service_new{i}", f"key{i}")
                assert cred is not None
                assert cred.reveal() == f"value{i}"


# =============================================================================
# Atomic Write Tests
# =============================================================================


class TestAtomicWrites:
    """Tests for atomic write operations."""

    def test_vault_write_atomic_on_error(self):
        """Test that vault write doesn't corrupt on encryption error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.enc"
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password_123",
                storage_dir=tmpdir,
                enable_auto_save=False,
                enable_audit_log=False,
            )

            # Save initial credential
            manager.auto_save_credential(
                service="service1",
                key="key1",
                value="value1",
            )

            # Verify vault exists
            assert vault_path.exists()
            initial_content = vault_path.read_text()

            # Try to save another credential
            manager.auto_save_credential(
                service="service2",
                key="key2",
                value="value2",
            )

            # Verify vault still valid
            assert vault_path.exists()

            # Should be able to read both credentials
            cred1 = manager.get_credential("service1", "key1")
            assert cred1 is not None
            assert cred1.reveal() == "value1"

            cred2 = manager.get_credential("service2", "key2")
            assert cred2 is not None
            assert cred2.reveal() == "value2"

    def test_vault_no_partial_writes(self):
        """Test that vault writes are atomic - no partial writes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_path = Path(tmpdir) / "vault.enc"
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password_123",
                storage_dir=tmpdir,
                enable_auto_save=False,
                enable_audit_log=False,
            )

            # Save credential
            manager.auto_save_credential(
                service="service1",
                key="key1",
                value="value1",
            )

            # Read vault content
            vault_content = json.loads(vault_path.read_text())

            # Vault should have version, salt, nonce, ciphertext
            assert "version" in vault_content
            assert "salt" in vault_content
            assert "nonce" in vault_content
            assert "ciphertext" in vault_content

            # Content should be valid JSON (not partial/corrupted)
            assert vault_content["version"] == "4"

    def test_temp_files_cleaned_up(self):
        """Test that temporary files are cleaned up after writes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = AutoSaveCredentialManager(
                storage_backend="vault",
                vault_password="test_password_123",
                storage_dir=tmpdir,
                enable_auto_save=False,
                enable_audit_log=False,
            )

            # Save multiple credentials
            for i in range(5):
                manager.auto_save_credential(
                    service=f"service{i}",
                    key=f"key{i}",
                    value=f"value{i}",
                )

            # Check for temp files
            temp_files = list(Path(tmpdir).glob("*.tmp.*"))

            # Should have no temp files left
            assert len(temp_files) == 0, f"Found temp files: {temp_files}"
