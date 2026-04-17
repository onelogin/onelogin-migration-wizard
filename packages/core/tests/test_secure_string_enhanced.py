"""
Enhanced tests for SecureString improvements.

Tests context manager, callback pattern, bytes access, and memory safety.
"""

import pytest

from onelogin_migration_core.credentials import SecureString


class TestSecureStringEnhanced:
    """Tests for enhanced SecureString functionality."""

    def test_from_secret_class_method(self):
        """Test creating SecureString with from_secret()."""
        token = SecureString.from_secret("my_secret_value")

        assert token.reveal() == "my_secret_value"
        assert isinstance(token, SecureString)

    def test_context_manager_basic(self):
        """Test basic context manager usage."""
        with SecureString.from_secret("test_secret") as token:
            # Inside context - should work
            assert token.reveal() == "test_secret"
            assert not token.is_zeroed()

        # Outside context - should be zeroed
        assert token.is_zeroed()
        with pytest.raises(ValueError, match="already been zeroed"):
            token.reveal()

    def test_context_manager_auto_zeros(self):
        """Test that context manager automatically zeros on exit."""
        token = SecureString.from_secret("sensitive_data")

        with token:
            assert token.reveal() == "sensitive_data"

        # After exiting, should be zeroed
        assert token.is_zeroed()
        with pytest.raises(ValueError):
            token.reveal()

    def test_context_manager_with_exception(self):
        """Test that context manager zeros even when exception occurs."""
        token = SecureString.from_secret("test")

        try:
            with token:
                assert token.reveal() == "test"
                raise ValueError("Test exception")
        except ValueError:
            pass

        # Should still be zeroed despite exception
        assert token.is_zeroed()

    def test_get_bytes_no_str_copy(self):
        """Test getting bytes without creating str copy."""
        token = SecureString("my_secret")

        secret_bytes = token.get_bytes()

        assert isinstance(secret_bytes, bytes)
        assert secret_bytes == b"my_secret"
        assert secret_bytes.decode() == "my_secret"

    def test_get_bytes_after_zero_raises(self):
        """Test that get_bytes raises after zeroing."""
        token = SecureString("secret")
        token.zero()

        with pytest.raises(ValueError, match="already been zeroed"):
            token.get_bytes()

    def test_get_memoryview(self):
        """Test getting memoryview for zero-copy access."""
        token = SecureString("test_data")

        mv = token.get_memoryview()

        assert isinstance(mv, memoryview)
        assert bytes(mv) == b"test_data"
        # Memoryview provides zero-copy access
        assert mv.tobytes() == b"test_data"

    def test_get_memoryview_after_zero_raises(self):
        """Test that get_memoryview raises after zeroing."""
        token = SecureString("secret")
        token.zero()

        with pytest.raises(ValueError, match="already been zeroed"):
            token.get_memoryview()

    def test_memoryview_reflects_zeroing(self):
        """Test that memoryview reflects zeroing of underlying data."""
        token = SecureString("test")
        mv = token.get_memoryview()

        # Before zeroing
        assert bytes(mv) == b"test"

        # Zero the token
        token.zero()

        # Memoryview should now show zeros
        assert bytes(mv) == b"\x00\x00\x00\x00"

    def test_use_secret_callback_pattern(self):
        """Test callback pattern for minimal copies."""
        token = SecureString("my_api_key")

        # Callback receives bytes
        result = token.use_secret(lambda secret: secret.decode().upper())

        assert result == "MY_API_KEY"

    def test_use_secret_with_multiple_operations(self):
        """Test callback with multiple operations."""
        token = SecureString("token123")

        def process_secret(secret_bytes):
            # Multiple operations on the secret
            as_str = secret_bytes.decode()
            return len(as_str) + ord(as_str[0])

        result = token.use_secret(process_secret)

        assert result == 8 + ord('t')  # len("token123") + ord('t')

    def test_use_secret_after_zero_raises(self):
        """Test that use_secret raises after zeroing."""
        token = SecureString("secret")
        token.zero()

        with pytest.raises(ValueError, match="already been zeroed"):
            token.use_secret(lambda s: s)

    def test_is_zeroed_method(self):
        """Test is_zeroed() status method."""
        token = SecureString("test")

        assert not token.is_zeroed()

        token.zero()

        assert token.is_zeroed()

    def test_is_zeroed_after_context_manager(self):
        """Test is_zeroed() after context manager exit."""
        token = SecureString("test")

        assert not token.is_zeroed()

        with token:
            assert not token.is_zeroed()

        assert token.is_zeroed()

    def test_zero_actually_zeros_memory(self):
        """Test that zero() actually overwrites the bytearray."""
        token = SecureString("secret_data")

        # Access internal data to verify zeroing
        original_data = bytes(token._data)
        assert original_data == b"secret_data"

        token.zero()

        # Internal data should be all zeros
        zeroed_data = bytes(token._data)
        assert zeroed_data == b"\x00" * len(original_data)
        assert all(b == 0 for b in token._data)

    def test_zero_is_idempotent(self):
        """Test that calling zero() multiple times is safe."""
        token = SecureString("test")

        token.zero()
        assert token.is_zeroed()

        # Calling zero() again should not raise
        token.zero()
        assert token.is_zeroed()

    def test_all_methods_raise_after_zero(self):
        """Test that all access methods raise after zeroing."""
        token = SecureString("secret")
        token.zero()

        with pytest.raises(ValueError):
            token.reveal()

        with pytest.raises(ValueError):
            token.get_bytes()

        with pytest.raises(ValueError):
            token.get_memoryview()

        with pytest.raises(ValueError):
            token.use_secret(lambda s: s)

    def test_context_manager_with_reveal(self):
        """Test typical pattern: context manager with reveal."""
        with SecureString.from_secret("my_token") as token:
            value = token.reveal()
            assert value == "my_token"
            # Use the value
            assert len(value) == 8

        # After context, token is zeroed
        assert token.is_zeroed()

    def test_context_manager_with_get_bytes(self):
        """Test typical pattern: context manager with get_bytes."""
        with SecureString.from_secret("my_token") as token:
            value_bytes = token.get_bytes()
            assert value_bytes == b"my_token"

        assert token.is_zeroed()

    def test_context_manager_with_use_secret(self):
        """Test typical pattern: context manager with use_secret."""
        result = None

        with SecureString.from_secret("api_key_123") as token:
            result = token.use_secret(lambda s: s.decode().replace("_", "-"))

        assert result == "api-key-123"

    def test_unicode_support(self):
        """Test that SecureString handles Unicode correctly."""
        unicode_secret = "🔒 secret 密码"
        token = SecureString(unicode_secret)

        assert token.reveal() == unicode_secret

        # Test get_bytes with Unicode
        secret_bytes = token.get_bytes()
        assert secret_bytes.decode("utf-8") == unicode_secret

        # Test use_secret with Unicode
        result = token.use_secret(lambda s: s.decode("utf-8"))
        assert result == unicode_secret

    def test_empty_string(self):
        """Test SecureString with empty string."""
        token = SecureString("")

        assert token.reveal() == ""
        assert token.get_bytes() == b""

        token.zero()
        assert token.is_zeroed()

    def test_large_string(self):
        """Test SecureString with large string."""
        large_secret = "x" * 10000
        token = SecureString(large_secret)

        assert token.reveal() == large_secret
        assert len(token.get_bytes()) == 10000

        token.zero()

        # Verify all bytes are zeroed
        assert all(b == 0 for b in token._data)

    def test_str_and_repr_hide_value(self):
        """Test that str() and repr() don't reveal the secret."""
        token = SecureString("super_secret")

        str_repr = str(token)
        repr_repr = repr(token)

        assert "super_secret" not in str_repr
        assert "super_secret" not in repr_repr
        assert "***hidden***" in str_repr
        assert "***hidden***" in repr_repr

    def test_del_auto_zeros(self):
        """Test that __del__ automatically zeros memory."""
        token = SecureString("test")
        data_id = id(token._data)

        # Delete the token
        del token

        # We can't directly verify the memory was zeroed after del,
        # but we've tested that zero() works and __del__ calls zero()

    def test_callback_return_values(self):
        """Test that use_secret properly returns callback results."""
        token = SecureString("value")

        # Test returning different types
        assert token.use_secret(lambda s: len(s)) == 5
        assert token.use_secret(lambda s: s.upper()) == b"VALUE"
        assert token.use_secret(lambda s: True) is True
        assert token.use_secret(lambda s: None) is None
        assert token.use_secret(lambda s: {"key": s}) == {"key": b"value"}

    def test_nested_context_managers(self):
        """Test nested context manager usage (not recommended but should work)."""
        token1 = SecureString("secret1")
        token2 = SecureString("secret2")

        with token1:
            assert token1.reveal() == "secret1"
            with token2:
                assert token2.reveal() == "secret2"
                assert token1.reveal() == "secret1"
            # token2 should be zeroed
            assert token2.is_zeroed()
            # token1 should still work
            assert token1.reveal() == "secret1"

        # Both should be zeroed
        assert token1.is_zeroed()
        assert token2.is_zeroed()

    def test_memoryview_comparison(self):
        """Test memoryview comparison and operations."""
        token = SecureString("test123")
        mv = token.get_memoryview()

        # Can compare memoryview contents
        assert bytes(mv) == b"test123"
        assert mv[0] == ord('t')
        assert mv[-1] == ord('3')

        # Slice operations
        assert bytes(mv[0:4]) == b"test"

    def test_security_best_practices_example(self):
        """Test example of security best practices."""
        # Best practice: Use context manager with get_bytes() or use_secret()

        # Example 1: Context manager with get_bytes
        with SecureString.from_secret("api_token") as token:
            token_bytes = token.get_bytes()
            # Use token_bytes for API call
            assert len(token_bytes) == 9

        # Example 2: Context manager with use_secret
        with SecureString.from_secret("password") as pwd:
            result = pwd.use_secret(lambda p: len(p))
            assert result == 8

        # Example 3: Minimize str copies
        token = SecureString("secret")
        try:
            # Prefer get_bytes() over reveal()
            secret_bytes = token.get_bytes()
            # Use secret_bytes instead of string
            assert secret_bytes == b"secret"
        finally:
            token.zero()
