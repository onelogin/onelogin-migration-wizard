# Layered Credentials

[![Tests](https://github.com/JSBtechnologies/Okta_to_Onelogin/workflows/Tests/badge.svg)](https://github.com/JSBtechnologies/Okta_to_Onelogin/actions)

Layered Credentials is a standalone Python library that provides a layered credential storage system. It combines multiple security controls—secure in-memory handling, Argon2id + AES‑GCM encryption, OS keyring integration, tamper‑evident audit logging, and safe operational primitives—so you can keep secrets encrypted on disk or in memory depending on your threat model.

## Highlights
- SecureString scrubs plaintext from memory as soon as you are done with it.
- Argon2Vault (V4 default; V3 supported for compatibility) encrypts vault files with Argon2id-derived keys and AES‑256‑GCM; V4 embeds a monotonic counter inside the authenticated payload for rollback protection.
- SessionKeyManager derives per-credential AES keys for the in-memory backend.
- TamperEvidentAuditLogger gives you tamper‑evident audit trails via HMAC chaining and constant‑time verification.
- AutoSaveCredentialManager routes credentials to OS keyring, encrypted vault, memory, or environment backends with a consistent API.
- ConfigValidator uses Pydantic (when available) to validate configuration documents and redact secrets safely.
- Backup & Restore — Export and import encrypted credential backups with separate passwords.
- Password Rotation — Change vault passwords without data loss while preserving audit verification when using the default persisted audit key.
- Keyring Support — Full-featured keyring backend with listing and backup capabilities.
- Custom Exceptions — Comprehensive exception hierarchy for precise error handling.
- Production Hardened — Unified locking, timing-attack prevention, robust error recovery, and secure file permissions.

## Installation
```bash
pip install layered-credentials
```

## Quick Start
```python
from layered_credentials import AutoSaveCredentialManager

manager = AutoSaveCredentialManager(storage_backend="keyring", app_name="my-secure-app")
manager.auto_save_credential("example", "api_token", "super-secret-token")

stored = manager.get_credential("example", "api_token")
if stored:
    # Prefer using get_bytes() or use_secret() to avoid creating Python str copies
    print("Token:", stored.reveal())
    stored.zero()  # immediately wipe the value from memory
```

You can switch backends without changing callers:
```python
manager = AutoSaveCredentialManager(
    storage_backend="vault",
    app_name="my-secure-app",
    vault_password="strong-master-password",
)
```

## Configuration
- `app_name`: Used to derive default storage paths and keyring service name; defaults to "layered-credentials".
- `storage_dir`: Override the base directory for audit logs, vault files, and counters.
- `keyring_service`: Customize the service identifier used with the OS keyring backend.
- `audit_log_identifiers`: Opt-in to include service/key identifiers in audit events.

All defaults are safe for general-purpose use, but applications should provide explicit values that make sense for their environment.

## Security Features

### Unified Vault Locking
All vault operations use a single canonical lock file (`.vault.lock`) to prevent race conditions and deadlocks:
- Atomic read-modify-write cycles — Lock acquired once for the entire operation
- Multiprocess-safe — Tested with concurrent operations across multiple processes
- Deadlock-free — Eliminates nested lock acquisition
- Counter protection — Monotonic counter remains consistent under concurrent load

### Tamper-Evident Audit Logging
Comprehensive audit trail with cryptographic integrity protection:
- HMAC chain — Each event includes the hash of the previous event, forming a tamper-evident chain
- Constant-time comparisons — Uses `hmac.compare_digest()` to prevent timing attacks
- Robust error recovery — Gracefully handles corrupted or incomplete log files
- Audit key persistence — By default the audit HMAC key is generated once and persisted (file: `.audit_key` with owner-only permissions) so audit verification remains possible across vault password rotations. Deriving the audit key from the vault password is supported as a special mode but is not the default; see the Audit Key Lifecycle section for details.
- Privacy by default — Identifiers are not logged unless explicitly enabled

Audit Key Lifecycle
- The recommended default is to persist the audit key to a file adjacent to the audit log (`.audit_key`) with restrictive permissions. This preserves verification of existing audit entries when you rotate the vault password.
- If you opt to derive the audit key from the vault password, be aware that rotating the vault password will change the derived key and will break verification of prior audit entries unless you perform an explicit migration.
- Use the CLI `verify-audit` command to validate the audit chain and the CLI `change-password` command which ensures the audit key file remains usable for verification.

### Secure File Operations
All temporary and persistent files are protected with cross-platform security:
- **Cross-platform permissions** — Owner-only permissions on all platforms:
  - Unix/Linux/macOS: `chmod 0o600` (owner read/write only)
  - Windows: ACL set via `icacls` (current user full control only)
- **Atomic writes** — Write to a secure temporary file, then atomically replace the target
- **Secure cleanup** — Temp files are removed even on errors where possible
- **Graceful degradation** — If permission setting fails, operation continues with logging

### Rollback Protection
Vault V4 format includes enhanced rollback protection:
- Counter inside authenticated payload — Counter is protected by AES-GCM authentication
- Tamper-proof — Cannot modify counter without breaking encryption
- Monotonic enforcement — Rejects attempts to roll back to older states

### Audit Key Storage Backends
Choose how audit keys are stored based on your security and operational requirements:

**FileAuditKeyBackend** (default):
- Stores key in `.audit_key` file with secure permissions
- Portable across all platforms
- Simple and reliable

**KeyringAuditKeyBackend** (recommended for high security):
- Leverages OS-native secure storage:
  - Windows: Windows Credential Manager (DPAPI-protected)
  - macOS: Keychain (hardware-backed on T2/M1+ Macs)
  - Linux: Secret Service API (GNOME Keyring, KWallet)
- Hardware-backed encryption on supported systems
- Requires: `pip install keyring`

**EnvironmentAuditKeyBackend** (for containers/cloud):
- Retrieves key from environment variable
- Ideal for Docker, Kubernetes, cloud deployments
- Key managed externally (AWS Secrets Manager, HashiCorp Vault, etc.)

Example usage:
```python
from layered_credentials import TamperEvidentAuditLogger, KeyringAuditKeyBackend

# Use OS keyring for audit key storage
backend = KeyringAuditKeyBackend(service_name="my-app-audit")
logger = TamperEvidentAuditLogger(
    log_file=Path("audit.log"),
    audit_key_backend=backend,
)
```

### Automated Session Rotation
For long-running applications, enable automatic session key rotation:

```python
from layered_credentials import SessionKeyManager
from datetime import timedelta

# Your credential store
memory_store = {}

# Callback for handling re-encryption
def handle_rotation(manager):
    success, failed, errors = manager.rotate_session_with_reencryption(
        memory_store,
        on_failure="skip"
    )
    print(f"Rotated: {success} success, {failed} failed")

# Enable auto-rotation (context manager handles shutdown)
with SessionKeyManager(
    max_age=timedelta(hours=1),
    auto_rotate=True,
    rotation_callback=handle_rotation,
) as manager:
    # Use manager for your application
    # Rotation happens automatically in background
    pass
# Automatically shuts down on exit
```

Key features:
- **Background rotation** — Runs in separate thread, doesn't block application
- **Graceful shutdown** — Context manager ensures clean termination
- **Exception handling** — Rotation errors are logged, application continues
- **Configurable intervals** — Set rotation frequency based on your security policy

## Advanced Features

### Backup and Restore
Export your credentials to an encrypted backup file with a separate password (defense in depth):
```python
from pathlib import Path
from layered_credentials import AutoSaveCredentialManager

manager = AutoSaveCredentialManager(
    storage_backend="vault",
    vault_password="vault-password",
    app_name="my-app"
)

# Backup credentials
stats = manager.backup_to_file(
    backup_path=Path("backup.enc"),
    backup_password="different-backup-password",
    vault_password="vault-password"
)
print(f"Backed up {stats['credentials_count']} credentials")

# Restore credentials (skips existing to protect modified data)
restore_stats = manager.restore_from_file(
    backup_path=Path("backup.enc"),
    backup_password="different-backup-password",
    vault_password="vault-password"
)
print(f"Restored {restore_stats['credentials_restored']} credentials")
```

### Password Rotation
You can change the vault password without losing data. When you use `TamperEvidentAuditLogger`, the audit HMAC key is persisted by default so audit verification remains possible after password changes.
```python
manager = AutoSaveCredentialManager(
    storage_backend="vault",
    vault_password="old-password",
    app_name="my-app"
)

# Rotate password
result = manager.change_vault_password(
    old_password="old-password",
    new_password="new-stronger-password"
)
print(f"Re-encrypted {result['credentials_count']} credentials")
```
Notes:
- The audit HMAC key is stored by default in a file next to the audit log (owner-only permissions). This preserves the ability to verify old audit entries after password rotation.
- If you opt to derive the audit key directly from the password, verification across rotations is not guaranteed; see the Audit Key Lifecycle section for details.

### Vault Format Migration (V3 → V4)
V4 embeds the monotonic counter inside the authenticated AES‑GCM payload, which protects the counter from tampering.

To migrate an existing V3 vault to V4 create a backup and run the migration helper:
```python
manager = AutoSaveCredentialManager(
    storage_backend="vault",
    vault_password="current-password",
    app_name="my-app"
)

stats = manager.migrate_vault_v3_to_v4(
    vault_password="current-password",
    create_backup=True
)

print(f"Migrated {stats['credentials_count']} credentials")
print(f"Backup created at: {stats.get('backup_path', 'backup path')}")
```
Notes:
- Migration is one-way; keep the backup if you may need to revert.
- Install `filelock` for reliable multiprocess-safe migration.

### List Credentials
List all stored credentials (works with vault, keyring, and memory backends):
```python
manager = AutoSaveCredentialManager(
    storage_backend="keyring",
    app_name="my-app"
)

# Save some credentials
manager.auto_save_credential("github", "token", "ghp_xxxxx")
manager.auto_save_credential("aws", "access_key", "AKIAXXXX")

# List all credentials
credentials = manager.list_credentials()
for service, key, backend in credentials:
    print(f"{service}/{key} stored in {backend}")
```

### Error Handling
Use custom exceptions for precise error handling:
```python
from layered_credentials import (
    AutoSaveCredentialManager,
    VaultRollbackError,
    SecureStringError,
    BackupError
)

try:
    manager = AutoSaveCredentialManager(
        storage_backend="vault",
        vault_password="password"
    )
    cred = manager.get_credential("service", "key")
    cred.reveal()
except VaultRollbackError as e:
    # Specific handling for rollback attacks
    print(f"Rollback detected: {e.details}")
except SecureStringError as e:
    # Handle zeroed SecureString access
    print(f"SecureString error: {e}")
except BackupError as e:
    # Handle backup failures
    print(f"Backup failed: {e}")
```

## Documentation
- See [CHANGELOG.md](CHANGELOG.md) for detailed feature documentation and migration notes.
- See [HARDENING_SUMMARY.md](HARDENING_SUMMARY.md) for a security enhancements overview.
- CI runs a comprehensive test suite across platforms; check the CI status badge and test reports in the repository for current results.

## Threat model
- This library protects secrets at rest and in memory against accidental exposure and local attacker scenarios. It reduces risk from partial writes, cross-process races, and casual tampering. It is not a substitute for hardware-backed key protection (TPM, HSM) when those are required. See HARDENING_SUMMARY.md for details.

## License
Licensed under the MIT license. See the root `LICENSE` file of this repository for full terms.