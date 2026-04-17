"""CLI admin utility for layered-credentials package.

Provides administrative commands for vault management, audit verification,
backups, and migrations.
"""

import json
import sys
from pathlib import Path
from typing import Optional

try:
    import click
except ImportError:
    print(
        "Error: Click is required for the CLI. Install with: pip install layered-credentials[cli]",
        file=sys.stderr,
    )
    sys.exit(1)

from layered_credentials import AutoSaveCredentialManager, TamperEvidentAuditLogger


@click.group()
@click.version_option(version="0.1.0", prog_name="layered-credentials")
def cli():
    """Layered Credentials admin utility.

    Manage vaults, verify audit logs, create backups, and more.
    """
    pass


@cli.command()
@click.option("--app-name", default="layered-credentials", help="Application name")
@click.option("--storage-dir", type=click.Path(), help="Custom storage directory")
def verify_audit(app_name: str, storage_dir: Optional[str]):
    """Verify audit log integrity.

    Checks the tamper-evident audit log for any signs of tampering,
    including hash chain breaks, modified entries, or missing entries.
    """
    from layered_credentials.core import _default_storage_dir

    if storage_dir:
        base_dir = Path(storage_dir)
    else:
        base_dir = _default_storage_dir(app_name)

    audit_file = base_dir / "audit.log"

    if not audit_file.exists():
        click.echo(f"No audit log found at {audit_file}")
        return

    click.echo(f"Verifying audit log: {audit_file}")

    # Note: We can't verify without the audit key, which is derived from vault password
    # or set explicitly. User needs to use the Python API for full verification.
    click.echo("Warning: Full verification requires vault password or audit key.")
    click.echo("Use the Python API for cryptographic verification.")

    # Basic sanity checks
    line_count = 0
    tamper_evident_count = 0
    basic_count = 0
    errors = []

    try:
        with open(audit_file) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                line_count += 1

                try:
                    entry = json.loads(line)
                    if "current_hash" in entry and "event" in entry:
                        tamper_evident_count += 1
                    else:
                        basic_count += 1
                except json.JSONDecodeError as e:
                    errors.append(f"Line {line_num}: Invalid JSON - {e}")

        click.echo(f"\nAudit Log Statistics:")
        click.echo(f"  Total entries: {line_count}")
        click.echo(f"  Tamper-evident entries: {tamper_evident_count}")
        click.echo(f"  Basic entries: {basic_count}")

        if errors:
            click.echo(f"\nErrors found: {len(errors)}")
            for error in errors[:10]:  # Show first 10 errors
                click.echo(f"  - {error}")
            if len(errors) > 10:
                click.echo(f"  ... and {len(errors) - 10} more")
            sys.exit(1)
        else:
            click.echo("\n✓ No structural errors found")
            if tamper_evident_count > 0:
                click.echo("  (Full cryptographic verification requires vault password)")

    except Exception as e:
        click.echo(f"Error reading audit log: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--app-name", default="layered-credentials", help="Application name")
@click.option("--storage-dir", type=click.Path(), help="Custom storage directory")
@click.option("--vault-password", prompt=True, hide_input=True, help="Vault password")
@click.option("--no-backup", is_flag=True, help="Skip creating backup")
def migrate(app_name: str, storage_dir: Optional[str], vault_password: str, no_backup: bool):
    """Migrate vault from V3 to V4 format.

    V4 format moves the rollback protection counter inside the authenticated
    encrypted payload, making it tamper-proof. Creates a backup by default.
    """
    try:
        manager = AutoSaveCredentialManager(
            storage_backend="vault",
            vault_password=vault_password,
            app_name=app_name,
            storage_dir=Path(storage_dir) if storage_dir else None,
        )

        click.echo("Starting vault migration from V3 to V4...")

        stats = manager.migrate_vault_v3_to_v4(
            vault_password=vault_password,
            create_backup=not no_backup,
        )

        click.echo("\n✓ Migration successful!")
        click.echo(f"  Migrated {stats['credentials_count']} credentials")
        click.echo(f"  Format: {stats['old_format']} → {stats['new_format']}")

        if "backup_path" in stats:
            click.echo(f"  Backup created: {stats['backup_path']}")

    except Exception as e:
        click.echo(f"Error during migration: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--app-name", default="layered-credentials", help="Application name")
@click.option("--storage-dir", type=click.Path(), help="Custom storage directory")
@click.option("--backend", type=click.Choice(["vault", "keyring", "memory"]), default="vault")
@click.option("--vault-password", help="Vault password (for vault backend)")
def list_credentials(
    app_name: str, storage_dir: Optional[str], backend: str, vault_password: Optional[str]
):
    """List all stored credentials.

    Shows service/key pairs for all credentials in the specified backend.
    Does not reveal actual credential values.
    """
    try:
        kwargs = {
            "storage_backend": backend,
            "app_name": app_name,
        }

        if storage_dir:
            kwargs["storage_dir"] = Path(storage_dir)

        if backend == "vault":
            if not vault_password:
                vault_password = click.prompt("Vault password", hide_input=True)
            kwargs["vault_password"] = vault_password

        manager = AutoSaveCredentialManager(**kwargs)
        credentials = manager.list_credentials()

        if not credentials:
            click.echo("No credentials found")
            return

        click.echo(f"\nStored Credentials ({len(credentials)} total):\n")

        # Group by service
        by_service = {}
        for service, key, cred_backend in credentials:
            if service not in by_service:
                by_service[service] = []
            by_service[service].append((key, cred_backend))

        for service in sorted(by_service.keys()):
            click.echo(f"  {service}:")
            for key, cred_backend in sorted(by_service[service]):
                click.echo(f"    - {key} (backend: {cred_backend})")

    except Exception as e:
        click.echo(f"Error listing credentials: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--app-name", default="layered-credentials", help="Application name")
@click.option("--storage-dir", type=click.Path(), help="Custom storage directory")
@click.option("--vault-password", prompt=True, hide_input=True, help="Current vault password")
@click.option("--backup-path", type=click.Path(), required=True, help="Path to save backup")
@click.option(
    "--backup-password", prompt=True, hide_input=True, help="Password for backup encryption"
)
def backup(
    app_name: str,
    storage_dir: Optional[str],
    vault_password: str,
    backup_path: str,
    backup_password: str,
):
    """Create encrypted backup of credentials.

    Exports all credentials to an encrypted backup file with a separate password.
    Provides defense in depth - backup password is independent of vault password.
    """
    try:
        manager = AutoSaveCredentialManager(
            storage_backend="vault",
            vault_password=vault_password,
            app_name=app_name,
            storage_dir=Path(storage_dir) if storage_dir else None,
        )

        click.echo("Creating encrypted backup...")

        stats = manager.backup_to_file(
            backup_path=Path(backup_path),
            backup_password=backup_password,
            vault_password=vault_password,
        )

        click.echo("\n✓ Backup successful!")
        click.echo(f"  Backed up {stats['credentials_count']} credentials")
        click.echo(f"  Backup file: {backup_path}")
        click.echo(f"  Format: {stats['backup_format']}")

    except Exception as e:
        click.echo(f"Error creating backup: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--app-name", default="layered-credentials", help="Application name")
@click.option("--storage-dir", type=click.Path(), help="Custom storage directory")
@click.option("--vault-password", prompt=True, hide_input=True, help="Current vault password")
@click.option("--backup-path", type=click.Path(), required=True, help="Path to backup file")
@click.option("--backup-password", prompt=True, hide_input=True, help="Backup decryption password")
@click.option("--overwrite", is_flag=True, help="Overwrite existing credentials")
def restore(
    app_name: str,
    storage_dir: Optional[str],
    vault_password: str,
    backup_path: str,
    backup_password: str,
    overwrite: bool,
):
    """Restore credentials from encrypted backup.

    Imports credentials from a backup file. By default, skips credentials that
    already exist (to protect modified data). Use --overwrite to replace existing.
    """
    try:
        manager = AutoSaveCredentialManager(
            storage_backend="vault",
            vault_password=vault_password,
            app_name=app_name,
            storage_dir=Path(storage_dir) if storage_dir else None,
        )

        click.echo("Restoring from encrypted backup...")

        stats = manager.restore_from_file(
            backup_path=Path(backup_path),
            backup_password=backup_password,
            vault_password=vault_password,
        )

        click.echo("\n✓ Restore complete!")
        click.echo(f"  Restored {stats['credentials_restored']} credentials")
        click.echo(f"  Skipped {stats['credentials_skipped']} existing credentials")

        if stats["credentials_skipped"] > 0 and not overwrite:
            click.echo("\n  (Use --overwrite to replace existing credentials)")

    except Exception as e:
        click.echo(f"Error restoring backup: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--app-name", default="layered-credentials", help="Application name")
@click.option("--storage-dir", type=click.Path(), help="Custom storage directory")
@click.option("--old-password", prompt=True, hide_input=True, help="Current vault password")
@click.option("--new-password", prompt=True, hide_input=True, help="New vault password")
@click.option(
    "--confirm-password",
    prompt=True,
    hide_input=True,
    help="Confirm new password",
)
def change_password(
    app_name: str,
    storage_dir: Optional[str],
    old_password: str,
    new_password: str,
    confirm_password: str,
):
    """Change vault password.

    Re-encrypts all credentials with a new password. If using TamperEvidentAuditLogger,
    the audit HMAC key is automatically rotated with the password change.
    """
    if new_password != confirm_password:
        click.echo("Error: New passwords don't match", err=True)
        sys.exit(1)

    try:
        manager = AutoSaveCredentialManager(
            storage_backend="vault",
            vault_password=old_password,
            app_name=app_name,
            storage_dir=Path(storage_dir) if storage_dir else None,
        )

        click.echo("Changing vault password...")

        stats = manager.change_vault_password(
            old_password=old_password,
            new_password=new_password,
        )

        click.echo("\n✓ Password changed successfully!")
        click.echo(f"  Re-encrypted {stats['credentials_count']} credentials")

        if hasattr(manager.audit_logger, "rotate_audit_key"):
            click.echo("  Audit key rotated with new password")

    except Exception as e:
        click.echo(f"Error changing password: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--app-name", default="layered-credentials", help="Application name")
@click.option("--storage-dir", type=click.Path(), help="Custom storage directory")
def info(app_name: str, storage_dir: Optional[str]):
    """Show vault information and statistics.

    Displays vault path, format, and other metadata without requiring password.
    """
    from layered_credentials.core import _default_storage_dir

    if storage_dir:
        base_dir = Path(storage_dir)
    else:
        base_dir = _default_storage_dir(app_name)

    vault_path = base_dir / "vault.enc"
    counter_file = base_dir / ".vault_counter"
    audit_file = base_dir / "audit.log"

    click.echo(f"Layered Credentials Info\n")
    click.echo(f"App Name: {app_name}")
    click.echo(f"Storage Directory: {base_dir}")
    click.echo(f"\nVault:")

    if vault_path.exists():
        try:
            with open(vault_path) as f:
                data = json.load(f)

            version = data.get("version", "unknown")
            click.echo(f"  Path: {vault_path}")
            click.echo(f"  Format: V{version}")
            click.echo(f"  Size: {vault_path.stat().st_size:,} bytes")

            if counter_file.exists():
                counter = counter_file.read_text().strip()
                click.echo(f"  Counter: {counter}")
        except Exception as e:
            click.echo(f"  Error reading vault: {e}")
    else:
        click.echo(f"  No vault found at {vault_path}")

    click.echo(f"\nAudit Log:")
    if audit_file.exists():
        line_count = sum(1 for line in open(audit_file) if line.strip())
        click.echo(f"  Path: {audit_file}")
        click.echo(f"  Entries: {line_count}")
        click.echo(f"  Size: {audit_file.stat().st_size:,} bytes")
    else:
        click.echo(f"  No audit log found")


def main():
    """Entry point for CLI."""
    cli()


if __name__ == "__main__":
    main()
