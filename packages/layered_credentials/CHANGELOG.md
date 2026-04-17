# Changelog

All notable changes to the layered-credentials package will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Unified Vault Locking**: Single canonical lock file for all vault operations
  - Replaced multiple lock files (`.vault.lock` and `.vault_data.lock`) with single `.vault.lock`
  - Eliminates deadlock risk by preventing nested lock acquisition
  - Lock acquired once at manager level (AutoSaveCredentialManager) for entire read-modify-write cycle
  - Vault encrypt/decrypt methods no longer acquire locks (called within manager's lock context)
  - All vault operations (save, read, delete, backup, restore, password change) protected by single lock
  - Multiprocess concurrency tests verify no deadlocks under heavy concurrent load
  - Counter remains monotonic under concurrent operations
  - Lock timeout set to 15 seconds for reasonable performance under contention

- **Audit Key Lifecycle & Password Rotation**: Persistent audit key by default to preserve verification across rotations
  - TamperEvidentAuditLogger persists an audit HMAC key file (`.audit_key`) with owner-only permissions by default
  - Password changes preserve audit verification when the persisted audit key is used
  - An explicit rotate_audit_key() helper is available for advanced workflows and migrations
  - Deriving the audit key from the vault password remains supported as a special mode but is not the default (operators must understand migration implications)
  - Comprehensive test suite verifies rotation and verification behavior when using a persisted audit key

- **Pluggable Audit Key Storage Backends**: Choose how audit keys are stored
  - Abstract `AuditKeyBackend` base class enables multiple storage strategies
  - `FileAuditKeyBackend`: File-based storage (default, backwards compatible)
  - `KeyringAuditKeyBackend`: OS-native secure storage (Windows Credential Manager, macOS Keychain, Linux Secret Service)
  - `EnvironmentAuditKeyBackend`: Environment variable storage for containerized/cloud deployments
  - Hardware-backed encryption on supported platforms (macOS T2/M1+, Windows DPAPI)
  - TamperEvidentAuditLogger accepts `audit_key_backend` parameter
  - Zero breaking changes - defaults to file backend for backwards compatibility
  - 23 comprehensive tests verify all backends

- **Automated Session Key Rotation**: Background rotation for long-running applications
  - SessionKeyManager supports `auto_rotate` flag for automatic background rotation
  - `rotation_callback` parameter allows user-provided re-encryption logic
  - Threading-based scheduler with `threading.Timer`
  - `shutdown()` method ensures graceful termination with configurable timeout
  - Context manager support (`__enter__`/`__exit__`) for automatic cleanup
  - Exception handling prevents rotation errors from crashing application
  - Configurable rotation intervals via `max_age` parameter
  - `get_session_info()` includes auto-rotation status
  - 21 comprehensive tests verify scheduler, shutdown, and exception handling

### Security
- **Cross-Platform File Permissions**: Proper file security on all platforms
  - Unix/Linux/macOS: `chmod 0o600` (owner read/write only)
  - Windows: ACL set via `icacls` (current user full control only)
  - Applied to all sensitive files: vault, counter, audit keys, temp files
  - Graceful degradation if permission setting fails (logs warning, continues operation)
  - 14 comprehensive tests verify permissions on Unix and Windows (mocked)
  - Replaces platform-dependent `hasattr(os, "chmod")` checks with unified API
- **Constant-Time HMAC Comparisons**: Prevent timing attacks in audit log verification
  - Replaced timing-vulnerable `==` comparisons with `hmac.compare_digest()`
  - Applied to both `prev_hash` and `current_hash` verification in audit logs
  - Prevents attackers from using timing analysis to forge valid hash chains
  - Comprehensive test suite verifies tampering detection
  - No performance impact (constant-time comparison is equally fast)

- **Audit Verify Error Privacy**: Improved error messages to prevent information leakage
  - Error messages no longer include actual hash values
  - Generic messages like "hash chain broken" and "entry tampered" prevent info disclosure
  - Detailed hash values logged to debug log (LOGGER.debug) for troubleshooting
  - Reduces attack surface by not revealing internal state in error messages
  - All existing tests pass with new error format

### Fixed
- **Robust Last Audit Line Reading**: Gracefully handles corrupted/incomplete audit logs
  - Expanded buffer algorithm handles lines longer than 4KB (up to 1MB)
  - Automatic UTF-8 decoding error recovery (expands buffer if mid-character)
  - Skips incomplete lines from interrupted writes
  - Skips corrupted JSON entries and finds last valid entry
  - Prevents crashes from malformed audit log files
  - Comprehensive test suite covers edge cases (incomplete lines, UTF-8 errors, corruption)

- **Secure Temp File Permissions**: All temporary files now created with 0o600 permissions
  - Vault temp files (`.vault.enc.tmp.*`) restricted to owner-only access
  - Counter temp files (`.vault_counter.tmp.*`) secured
  - Backup/restore temp files secured
  - Prevents information disclosure through world-readable temp files
  - Applied to all 5 temp file creation locations
  - Unix-like systems only (Windows uses different permission model)

### Added
- **V3→V4 Migration Helper**: Safe migration from V3 to V4 vault format
  - New `migrate_vault_v3_to_v4()` method on AutoSaveCredentialManager
  - Automatic backup creation before migration (optional)
  - V4 format improvements: counter inside authenticated payload (tamper-proof)
  - Verifies migration success and data integrity
  - Logs migration event in audit log
  - Returns migration statistics (credential count, backup path, timestamps)
  - Comprehensive test suite covers success and error scenarios

### Documentation
- **Comprehensive Documentation Updates**: Updated all documentation to reflect Phase 2 security hardening
  - README.md: Added Security Features section with detailed explanations
  - README.md: Updated highlights to mention TamperEvidentAuditLogger and production hardening
  - README.md: Updated Password Rotation section with audit key lifecycle details
  - README.md: Added Vault Format Migration (V3→V4) section with usage examples
  - HARDENING_SUMMARY.md: Added Phase 2 section documenting all 6 security PRs
  - HARDENING_SUMMARY.md: Updated test counts (283+ total tests)
  - HARDENING_SUMMARY.md: Updated conclusion with combined Phase 1 & 2 results
  - All changes maintain clarity and provide actionable code examples

### CI/CD
- **GitHub Actions CI Pipeline**: Comprehensive automated testing infrastructure
  - Tests run on every push and pull request to main/develop branches
  - Matrix testing: Python 3.10, 3.11, 3.12, 3.13 across Ubuntu, macOS, Windows
  - Separate test jobs for core, CLI, GUI, and layered-credentials packages
  - Code quality checks: black, isort, ruff linting
  - Security scanning with bandit
  - Integration tests verify cross-package compatibility
  - Test result artifacts uploaded for debugging
  - Test summary job provides overall status
  - GUI tests run with Xvfb on Ubuntu for headless testing

### CLI
- **CLI Admin Utility**: Command-line interface for administrative tasks
  - `verify-audit`: Verify audit log integrity and check for tampering
  - `migrate`: Migrate vault from V3 to V4 format with automatic backup
  - `list-credentials`: List all stored credentials by service/key
  - `backup`: Create encrypted backup with separate password
  - `restore`: Restore credentials from encrypted backup
  - `change-password`: Change vault password and rotate audit key
  - `info`: Show vault information, format, and statistics
  - All commands support custom app names and storage directories
  - Password prompts with hidden input for security
  - Clear error messages and success indicators
  - Install with: `pip install layered-credentials[cli]`
  - Run with: `python -m layered_credentials.cli [command]`

### Added
- **Configurable Argon2 and Crypto Parameters**: Full control over cryptographic parameters
  - All Argon2id parameters now configurable: `time_cost`, `memory_cost`, `parallelism`
  - Crypto parameters now configurable: `hash_len`, `salt_len`, `nonce_len`
  - Comprehensive validation with OWASP/NIST-based bounds checking
  - Security warnings for parameters below recommended thresholds
  - `get_parameters()` method to inspect current configuration
  - Defaults unchanged (backwards compatible): time_cost=3, memory_cost=65536, parallelism=4
  - AES key length validation (must be 16, 24, or 32 bytes for AES-128/192/256)
  - V2 format decryption uses hardcoded defaults for backwards compatibility
- **SessionKeyManager Rotation and Resilience**: Enhanced session key rotation with safe re-encryption
  - New `rotate_session_with_reencryption()` method for safe rotation without data loss
  - Automatically decrypts, rotates keys, and re-encrypts all credentials
  - Three failure modes: "skip" (leave failed creds), "abort" (raise on error), "invalidate" (remove failed creds)
  - Configurable `max_age` parameter for rotation policy (default: 1 hour)
  - `get_rotation_count()` method to track rotation history
  - `get_session_info()` method for monitoring session state
  - `should_rotate()` respects instance `max_age` parameter
  - Deprecated `_rotate_session()` (use new method instead)
  - Returns detailed stats: `(success_count, failure_count, error_messages)`
  - Backwards compatible with existing code
- **SecureString Enhancements**: Improved SecureString with context manager and better API
  - Context manager support: `with SecureString.from_secret("...") as token:`
  - `from_secret()` class method for recommended usage pattern
  - `get_bytes()` method to access secret without creating str copies
  - `get_memoryview()` for zero-copy access to secret data
  - `use_secret(callback)` pattern to minimize copies in memory
  - `is_zeroed()` method to check zeroing status
  - Enhanced documentation about Python's limitations
  - All methods properly raise after zeroing
  - Backwards compatible with existing code
- **TamperEvidentAuditLogger**: New audit logger with tamper-evidence via HMAC chaining
  - Each log entry includes prev_hash and current_hash forming an immutable chain
  - Detects tampering, insertion, deletion, and truncation attacks
  - Audit key can be derived from vault password, provided explicitly, or auto-generated
  - Includes `verify_log()` method to validate entire audit chain
  - Thread-safe concurrent logging maintains valid chain
  - Backwards compatible with non-tamper-evident logs
  - Optional: can be disabled for backwards compatibility
- **V4 Vault Format**: New encrypted vault format with enhanced security
  - Counter now included inside authenticated encrypted payload (tamper-proof)
  - Prevents counter manipulation attacks
  - Backwards compatible with V3 and V2 formats
- **Atomic Writes**: All vault write operations now use temporary files + `os.replace()` for atomicity
  - Prevents partial writes and corruption
  - No vault corruption even if process crashes during write
- **Cross-Process File Locking**: Added `filelock` dependency for cross-process file locking
  - Prevents TOCTOU (time-of-check-time-of-use) races
  - Safe for concurrent access from multiple processes
  - All vault read/write/delete operations protected by file locks
  - All vault operations are now atomic, preventing partial writes that could leak information
- **Comprehensive Concurrency Tests**: 11 new tests verifying thread and process safety
  - Concurrent encrypt/decrypt operations
  - Concurrent vault writes and reads
  - Concurrent delete operations
  - Monotonic counter verification under load
  - Atomic write verification

### Fixed
- Vault corruption during concurrent writes from multiple threads/processes
- TOCTOU race conditions between vault read and write operations
- Counter file corruption during concurrent counter updates
- Delete operations failing with rollback errors during concurrent operations

### Security
- **Tamper-Proof Counter**: Counter is now inside the authenticated encrypted payload, preventing manipulation
- **Rollback Protection**: Enhanced rollback detection works even with concurrent operations
- **Atomic Operations**: All vault operations are now atomic, preventing partial writes that could leak information
- **File Locking**: Cross-process file locking prevents race conditions that could lead to data corruption or security issues

### Dependencies
- Added: `filelock>=3.13.0` for cross-process file locking

### Testing
- All 223 tests passing (51 original + 11 concurrency + 17 tamper-evidence + 29 SecureString + 21 rotation + 27 parameter + 12 backup/restore + 12 keyring backend + 19 error handling + 24 backwar[...] 
  - Test coverage includes V4 format encryption/decryption and backward compatibility, concurrency, tamper detection, rotation, backup/restore, and keyring flows.
  - See CI artifacts for full test logs and coverage.

### Migration Notes
- **No action required**: V4 format is generated automatically for new encryptions
- **Backwards compatible**: Existing V3 and V2 vaults can still be decrypted
- **Gradual migration**: Vaults will be upgraded to V4 on next write operation (or via `migrate_vault_v3_to_v4()`)
- **File locking**: Ensure `filelock` is installed for cross-process safety (automatically included in dependencies)

### Breaking Changes
- None - all changes are backwards compatible

## [0.1.0] - 2024-11-04

### Added
- Initial release of layered-credentials package
- SecureString class for memory-protected strings
- Argon2VaultV3 for password-based encryption
- SessionKeyManager for per-session derived keys
- AuditLogger with privacy controls
- ConfigValidator for configuration validation
- AutoSaveCredentialManager with multi-backend support:
  - keyring (OS native)
  - vault (encrypted file)
  - memory (session-only)
  - env (read-only)
- Comprehensive test suite (51 tests)
- Thread-safe operations
- Rollback protection with monotonic counter

[Unreleased]: https://github.com/JSBtechnologies/Okta_to_Onelogin/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/JSBtechnologies/Okta_to_Onelogin/releases/tag/v0.1.0