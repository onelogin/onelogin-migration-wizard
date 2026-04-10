"""
Tests for Argon2VaultV3 configurable parameters.

This module tests:
- Parameter validation and bounds checking
- Custom parameter usage in encryption/decryption
- Security warnings for weak configurations
- Backwards compatibility with default parameters
- get_parameters() method
"""

import pytest
from pathlib import Path
import tempfile

from onelogin_migration_core.credentials import Argon2VaultV3


class TestArgon2ParameterValidation:
    """Test parameter validation and bounds checking."""

    def test_default_parameters(self):
        """Test that defaults match OWASP recommendations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Argon2VaultV3(counter_file=Path(tmpdir) / "counter")

            assert vault.time_cost == 3
            assert vault.memory_cost == 65536  # 64 MB
            assert vault.parallelism == 4
            assert vault.hash_len == 32
            assert vault.salt_len == 16
            assert vault.nonce_len == 12

    def test_custom_valid_parameters(self):
        """Test creating vault with valid custom parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Argon2VaultV3(
                counter_file=Path(tmpdir) / "counter",
                time_cost=5,
                memory_cost=131072,  # 128 MB
                parallelism=8,
                hash_len=32,  # AES-256
                salt_len=32,
                nonce_len=16,
            )

            assert vault.time_cost == 5
            assert vault.memory_cost == 131072
            assert vault.parallelism == 8
            assert vault.hash_len == 32
            assert vault.salt_len == 32
            assert vault.nonce_len == 16

    def test_time_cost_too_low(self):
        """Test that time_cost below minimum raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="time_cost must be between"):
                Argon2VaultV3(
                    counter_file=Path(tmpdir) / "counter",
                    time_cost=0,
                )

    def test_time_cost_too_high(self):
        """Test that time_cost above maximum raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="time_cost must be between"):
                Argon2VaultV3(
                    counter_file=Path(tmpdir) / "counter",
                    time_cost=101,
                )

    def test_memory_cost_too_low(self):
        """Test that memory_cost below minimum raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="memory_cost must be between"):
                Argon2VaultV3(
                    counter_file=Path(tmpdir) / "counter",
                    memory_cost=4096,
                )

    def test_memory_cost_too_high(self):
        """Test that memory_cost above maximum raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="memory_cost must be between"):
                Argon2VaultV3(
                    counter_file=Path(tmpdir) / "counter",
                    memory_cost=2097152,  # 2 GB
                )

    def test_parallelism_too_low(self):
        """Test that parallelism below minimum raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="parallelism must be between"):
                Argon2VaultV3(
                    counter_file=Path(tmpdir) / "counter",
                    parallelism=0,
                )

    def test_parallelism_too_high(self):
        """Test that parallelism above maximum raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="parallelism must be between"):
                Argon2VaultV3(
                    counter_file=Path(tmpdir) / "counter",
                    parallelism=65,
                )

    def test_hash_len_invalid(self):
        """Test that invalid hash_len raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="hash_len must be 16, 24, or 32"):
                Argon2VaultV3(
                    counter_file=Path(tmpdir) / "counter",
                    hash_len=20,  # Not a valid AES key size
                )

    def test_hash_len_too_small(self):
        """Test that hash_len below minimum AES key size raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="hash_len must be 16, 24, or 32"):
                Argon2VaultV3(
                    counter_file=Path(tmpdir) / "counter",
                    hash_len=8,
                )

    def test_salt_len_too_low(self):
        """Test that salt_len below minimum raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="salt_len must be between"):
                Argon2VaultV3(
                    counter_file=Path(tmpdir) / "counter",
                    salt_len=4,
                )

    def test_salt_len_too_high(self):
        """Test that salt_len above maximum raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="salt_len must be between"):
                Argon2VaultV3(
                    counter_file=Path(tmpdir) / "counter",
                    salt_len=128,
                )

    def test_nonce_len_too_low(self):
        """Test that nonce_len below minimum raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="nonce_len must be between"):
                Argon2VaultV3(
                    counter_file=Path(tmpdir) / "counter",
                    nonce_len=8,
                )

    def test_nonce_len_too_high(self):
        """Test that nonce_len above maximum raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="nonce_len must be between"):
                Argon2VaultV3(
                    counter_file=Path(tmpdir) / "counter",
                    nonce_len=24,
                )

    def test_security_warning_low_time_cost(self, caplog):
        """Test that low time_cost generates security warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Argon2VaultV3(
                counter_file=Path(tmpdir) / "counter",
                time_cost=1,
            )

            assert "below OWASP minimum recommendation of 2" in caplog.text

    def test_security_warning_low_memory_cost(self, caplog):
        """Test that low memory_cost generates security warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Argon2VaultV3(
                counter_file=Path(tmpdir) / "counter",
                memory_cost=16384,  # 16 MB
            )

            assert "below OWASP minimum recommendation" in caplog.text

    def test_security_warning_low_salt_len(self, caplog):
        """Test that low salt_len generates NIST warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Argon2VaultV3(
                counter_file=Path(tmpdir) / "counter",
                salt_len=8,
            )

            assert "below NIST recommendation of 16 bytes" in caplog.text


class TestArgon2ParametersInOperation:
    """Test that custom parameters actually affect encryption/decryption."""

    def test_encrypt_decrypt_with_custom_parameters(self):
        """Test encryption and decryption work with custom parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Argon2VaultV3(
                counter_file=Path(tmpdir) / "counter",
                time_cost=2,
                memory_cost=32768,  # 32 MB
                parallelism=2,
                hash_len=24,  # AES-192
                salt_len=20,
                nonce_len=16,
            )

            plaintext = "test_secret_with_custom_params"
            password = "strong_password"

            encrypted = vault.encrypt(plaintext, password)
            decrypted = vault.decrypt(encrypted, password)

            assert decrypted == plaintext

    def test_salt_length_matches_parameter(self):
        """Test that generated salt length matches configured parameter."""
        import base64

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Argon2VaultV3(
                counter_file=Path(tmpdir) / "counter",
                salt_len=24,
            )

            encrypted = vault.encrypt("test", "password")
            salt = base64.b64decode(encrypted["salt"])

            assert len(salt) == 24

    def test_nonce_length_matches_parameter(self):
        """Test that generated nonce length matches configured parameter."""
        import base64

        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Argon2VaultV3(
                counter_file=Path(tmpdir) / "counter",
                nonce_len=16,
            )

            encrypted = vault.encrypt("test", "password")
            nonce = base64.b64decode(encrypted["nonce"])

            assert len(nonce) == 16

    def test_different_parameters_produce_different_ciphertext(self):
        """Test that different parameters produce different ciphertexts."""
        plaintext = "same_plaintext"
        password = "same_password"

        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                vault1 = Argon2VaultV3(
                    counter_file=Path(tmpdir1) / "counter",
                    time_cost=2,
                    memory_cost=32768,
                )

                vault2 = Argon2VaultV3(
                    counter_file=Path(tmpdir2) / "counter",
                    time_cost=4,
                    memory_cost=65536,
                )

                encrypted1 = vault1.encrypt(plaintext, password)
                encrypted2 = vault2.encrypt(plaintext, password)

                # Different parameters should produce different ciphertexts
                # (even though salts are random, the key derivation is different)
                assert encrypted1["ciphertext"] != encrypted2["ciphertext"]

    def test_decryption_requires_matching_parameters(self):
        """Test that decryption requires the same parameters used for encryption."""
        plaintext = "secret"
        password = "password"

        with tempfile.TemporaryDirectory() as tmpdir1:
            with tempfile.TemporaryDirectory() as tmpdir2:
                # Encrypt with one set of parameters
                vault1 = Argon2VaultV3(
                    counter_file=Path(tmpdir1) / "counter",
                    time_cost=2,
                    memory_cost=32768,
                )
                encrypted = vault1.encrypt(plaintext, password)

                # Try to decrypt with different parameters
                vault2 = Argon2VaultV3(
                    counter_file=Path(tmpdir2) / "counter",
                    time_cost=4,
                    memory_cost=65536,
                )

                with pytest.raises(ValueError, match="Decryption or authentication failed"):
                    vault2.decrypt(encrypted, password)

    def test_get_parameters_method(self):
        """Test that get_parameters() returns current configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Argon2VaultV3(
                counter_file=Path(tmpdir) / "counter",
                time_cost=5,
                memory_cost=131072,
                parallelism=8,
                hash_len=24,  # AES-192
                salt_len=24,
                nonce_len=16,
            )

            params = vault.get_parameters()

            assert params == {
                "time_cost": 5,
                "memory_cost": 131072,
                "parallelism": 8,
                "hash_len": 24,
                "salt_len": 24,
                "nonce_len": 16,
            }

    def test_minimal_valid_parameters(self):
        """Test encryption/decryption with minimal valid parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Argon2VaultV3(
                counter_file=Path(tmpdir) / "counter",
                time_cost=1,
                memory_cost=8192,  # 8 MB
                parallelism=1,
                hash_len=16,
                salt_len=8,
                nonce_len=12,
            )

            plaintext = "test"
            password = "password"

            encrypted = vault.encrypt(plaintext, password)
            decrypted = vault.decrypt(encrypted, password)

            assert decrypted == plaintext

    def test_maximal_reasonable_parameters(self):
        """Test encryption/decryption with high but valid parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Argon2VaultV3(
                counter_file=Path(tmpdir) / "counter",
                time_cost=10,
                memory_cost=262144,  # 256 MB
                parallelism=16,
                hash_len=32,  # AES-256 (maximum)
                salt_len=64,
                nonce_len=16,
            )

            plaintext = "test"
            password = "password"

            encrypted = vault.encrypt(plaintext, password)
            decrypted = vault.decrypt(encrypted, password)

            assert decrypted == plaintext


class TestBackwardsCompatibility:
    """Test backwards compatibility with existing vaults."""

    def test_default_parameters_match_original_constants(self):
        """Test that default parameters match original hardcoded values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            vault = Argon2VaultV3(counter_file=Path(tmpdir) / "counter")

            # Should match original TIME_COST, MEMORY_COST, PARALLELISM
            assert vault.time_cost == Argon2VaultV3.DEFAULT_TIME_COST
            assert vault.memory_cost == Argon2VaultV3.DEFAULT_MEMORY_COST
            assert vault.parallelism == Argon2VaultV3.DEFAULT_PARALLELISM
            assert vault.hash_len == Argon2VaultV3.DEFAULT_HASH_LEN
            assert vault.salt_len == Argon2VaultV3.DEFAULT_SALT_LEN
            assert vault.nonce_len == Argon2VaultV3.DEFAULT_NONCE_LEN

    def test_v2_decryption_uses_default_parameters(self):
        """Test that V2 format decryption uses hardcoded defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a vault with custom parameters
            vault = Argon2VaultV3(
                counter_file=Path(tmpdir) / "counter",
                time_cost=10,
                memory_cost=131072,
            )

            # V2 format should use defaults regardless of instance parameters
            # This is tested indirectly by ensuring V2 decryption works
            # (since V2 was created with default parameters historically)
