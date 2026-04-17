"""Database security management CLI commands.

This module provides CLI commands for managing database security,
including permission checks, encryption setup, and security audits.

Usage:
    onelogin-migration-tool db check
    onelogin-migration-tool db secure
    onelogin-migration-tool db encrypt --password
"""

from __future__ import annotations

from pathlib import Path

import typer
from onelogin_migration_core.db import EncryptedConnectorDatabase, check_database_security
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

app = typer.Typer(name="db", help="Database security and management commands")
console = Console()


@app.command()
def check() -> None:
    """Check database security status and permissions.

    Examples:
        onelogin-migration-tool db check
    """
    try:
        security_status = check_database_security()

        if not security_status["exists"]:
            console.print("[yellow]⚠[/yellow] Database not found")
            console.print("Run the GUI to initialize the database first")
            return

        console.print("\n[bold]Database Security Status[/bold]")
        console.print("─" * 60)

        # Basic info
        console.print(f"Location:  {security_status['path']}")
        size_mb = security_status["size_bytes"] / (1024 * 1024)
        console.print(f"Size:      {size_mb:.2f} MB")

        # Permissions
        perms = security_status["permissions"]
        perm_icon = "[green]✓[/green]" if perms["secure"] else "[red]✗[/red]"
        console.print("\n[bold]File Permissions[/bold]")
        console.print(f"  Status:     {perm_icon} {perms['octal']}")

        if perms["world_readable"]:
            console.print("  [red]⚠ Warning:[/red] Readable by all users on system")
        if perms["group_readable"]:
            console.print("  [yellow]⚠ Warning:[/yellow] Readable by group members")

        if not perms["secure"]:
            console.print(f"  [yellow]→ Recommendation:[/yellow] {perms['recommendation']}")
            console.print("    Run: [bold]onelogin-migration-tool db secure[/bold]")

        # Encryption
        enc = security_status["encryption"]
        enc_icon = "[green]✓[/green]" if enc["enabled"] else "[yellow]○[/yellow]"
        console.print("\n[bold]Encryption[/bold]")
        console.print(f"  Available:  {'Yes' if enc['available'] else 'No'}")
        console.print(f"  Enabled:    {enc_icon} {'Yes' if enc['enabled'] else 'No'}")

        if not enc["available"]:
            console.print(f"  [yellow]→ Recommendation:[/yellow] {enc['recommendation']}")
            console.print("    Run: [bold]pip install cryptography[/bold]")
        elif not enc["enabled"]:
            console.print(f"  [yellow]→ Recommendation:[/yellow] {enc['recommendation']}")
            console.print("    Run: [bold]onelogin-migration-tool db encrypt[/bold]")

        console.print()

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def secure() -> None:
    """Secure database with proper file permissions.

    This command fixes file permissions to ensure only the owner
    can read and write the database file (mode 0o600).

    Examples:
        onelogin-migration-tool db secure
    """
    try:
        db_path = Path.home() / ".onelogin-migration" / "connectors.db"

        if not db_path.exists():
            console.print("[red]✗[/red] Database not found")
            console.print("Run the GUI to initialize the database first")
            raise typer.Exit(1)

        # Check current permissions
        import os

        current_mode = os.stat(db_path).st_mode & 0o777
        secure_mode = 0o600

        console.print("\n[bold]Securing Database[/bold]")
        console.print("─" * 60)
        console.print(f"File: {db_path}")
        console.print(f"Current permissions: {oct(current_mode)}")

        if current_mode == secure_mode:
            console.print("\n[green]✓[/green] Database is already secured with 0o600 permissions")
            return

        # Apply secure permissions
        console.print("\nApplying secure permissions...")

        try:
            os.chmod(db_path, secure_mode)
            new_mode = os.stat(db_path).st_mode & 0o777

            if new_mode == secure_mode:
                console.print("[green]✓[/green] Successfully secured database")
                console.print(f"New permissions: {oct(new_mode)}")
                console.print("\n[bold]Security Details:[/bold]")
                console.print("  - Owner: read/write access")
                console.print("  - Group: no access")
                console.print("  - Others: no access")
            else:
                console.print("[yellow]⚠[/yellow] Permissions changed but not as expected")
                console.print(f"Expected: {oct(secure_mode)}, Got: {oct(new_mode)}")

        except PermissionError:
            console.print("[red]✗[/red] Permission denied - insufficient privileges")
            console.print("Try running with appropriate permissions")
            raise typer.Exit(1)

        console.print()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def encrypt(
    password: str | None = typer.Option(
        None, "--password", "-p", help="Encryption password (will prompt if not provided)"
    ),
    generate: bool = typer.Option(
        False, "--generate", "-g", help="Generate a secure random password"
    ),
    save_keyring: bool = typer.Option(
        True, "--save-keyring/--no-save-keyring", help="Save password to system keyring"
    ),
) -> None:
    """Enable encryption for telemetry data.

    This command encrypts existing telemetry data using AES-256-GCM encryption.
    The encryption password can be provided, generated, or stored in the system keyring.

    Examples:
        # Interactive password prompt
        onelogin-migration-tool db encrypt

        # Generate secure random password
        onelogin-migration-tool db encrypt --generate

        # Provide password directly (not recommended)
        onelogin-migration-tool db encrypt --password "mypassword"
    """
    try:
        if not EncryptedConnectorDatabase.is_encryption_available():
            console.print("[red]✗[/red] Encryption not available")
            console.print("\nThe 'cryptography' library is required for encryption.")
            console.print("Install it with: [bold]pip install cryptography[/bold]")
            raise typer.Exit(1)

        console.print("\n[bold]Database Encryption Setup[/bold]")
        console.print("─" * 60)

        # Get or generate password
        if generate:
            password = EncryptedConnectorDatabase.generate_password()
            console.print("\n[green]✓[/green] Generated secure password:")
            console.print(f"[bold]{password}[/bold]")
            console.print("\n[yellow]⚠ IMPORTANT:[/yellow] Save this password securely!")
            console.print("You will need it to access encrypted telemetry data.")

            if not Confirm.ask("\nHave you saved the password securely?"):
                console.print("\n[yellow]Encryption cancelled[/yellow]")
                return

        elif not password:
            password = Prompt.ask("\nEnter encryption password", password=True)
            password_confirm = Prompt.ask("Confirm password", password=True)

            if password != password_confirm:
                console.print("\n[red]✗[/red] Passwords do not match")
                raise typer.Exit(1)

        if not password or len(password) < 8:
            console.print("\n[red]✗[/red] Password must be at least 8 characters")
            raise typer.Exit(1)

        # Initialize encrypted database
        console.print("\nInitializing encryption...")


        db_path = Path.home() / ".onelogin-migration" / "connectors.db"
        encrypted_db = EncryptedConnectorDatabase(db_path, password)

        # Save to keyring if requested
        if save_keyring:
            if encrypted_db._save_key_to_keyring(password):
                console.print("[green]✓[/green] Password saved to system keyring")
            else:
                console.print(
                    "[yellow]⚠[/yellow] Could not save to keyring (install 'keyring' package)"
                )

        # Verify current encryption status
        status = encrypted_db.verify_encryption()

        console.print("\n[bold]Current Status:[/bold]")
        console.print(f"  Total telemetry records: {status['telemetry_total']}")
        console.print(f"  Already encrypted: {status['telemetry_encrypted']}")

        if status["telemetry_total"] == 0:
            console.print("\n[yellow]ℹ[/yellow] No telemetry data to encrypt yet")
            console.print("Encryption will be applied to new telemetry as it's collected")
            return

        if status["encryption_percentage"] == 100:
            console.print("\n[green]✓[/green] All telemetry data is already encrypted")
            return

        # Encrypt existing data
        to_encrypt = status["telemetry_total"] - status["telemetry_encrypted"]

        if not Confirm.ask(f"\nEncrypt {to_encrypt} telemetry records?"):
            console.print("\n[yellow]Encryption cancelled[/yellow]")
            return

        console.print("\nEncrypting telemetry data...")
        encrypted_count = encrypted_db.encrypt_telemetry_data()

        console.print(f"\n[green]✓[/green] Successfully encrypted {encrypted_count} records")

        # Verify
        final_status = encrypted_db.verify_encryption()
        console.print("\n[bold]Final Status:[/bold]")
        console.print(
            f"  Encrypted: {final_status['telemetry_encrypted']}/{final_status['telemetry_total']}"
        )
        console.print(f"  Coverage: {final_status['encryption_percentage']:.1f}%")

        console.print("\n[green]✓[/green] Database encryption enabled successfully")
        console.print()

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show detailed database status and statistics.

    Examples:
        onelogin-migration-tool db status
    """
    try:
        from .db import get_default_connector_db

        db = get_default_connector_db()
        conn = db.connect()

        console.print("\n[bold]Database Status[/bold]")
        console.print("─" * 60)

        # Get record counts
        counts = db.get_connector_counts()

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Category", style="dim")
        table.add_column("Count", justify="right")

        table.add_row("OneLogin Connectors", f"{counts['onelogin']:,}")
        table.add_row("Okta Connectors", f"{counts['okta']:,}")
        table.add_row("Connector Mappings", f"{counts['mappings']:,}")
        table.add_row("User Overrides", f"{counts.get('user_overrides', 0):,}")

        console.print(table)

        # Check security status
        security_status = check_database_security()
        perms_icon = (
            "[green]✓[/green]" if security_status["permissions"]["secure"] else "[red]✗[/red]"
        )

        console.print(
            f"\n[bold]Security:[/bold] {perms_icon} Permissions {security_status['permissions']['octal']}"
        )

        if not security_status["permissions"]["secure"]:
            console.print(
                "  [yellow]→ Run[/yellow] [bold]onelogin-migration-tool db secure[/bold] [yellow]to fix[/yellow]"
            )

        console.print()

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def migrate() -> None:
    """Migrate existing database to use transparent encryption.

    This command encrypts all existing plaintext telemetry data using
    automatic transparent encryption. Safe to run multiple times - already
    encrypted data will be skipped.
    """
    console.print("\n[bold cyan]Database Encryption Migration[/bold cyan]\n")

    try:
        from .db import is_encryption_available, migrate_database_encryption

        # Check if encryption is available
        if not is_encryption_available():
            console.print("[red]✗ Error:[/red] Encryption not available")
            console.print("\n[yellow]Install the cryptography package:[/yellow]")
            console.print("  pip install cryptography")
            raise typer.Exit(1)

        console.print("[cyan]→[/cyan] Checking database...")

        # Run migration
        result = migrate_database_encryption()

        if result["status"] == "error":
            console.print(f"\n[red]✗ Migration failed:[/red] {result['message']}")
            raise typer.Exit(1)

        # Display results
        console.print("\n[green]✓[/green] Migration completed successfully!\n")

        console.print("[bold]Results:[/bold]")
        console.print(f"  Records encrypted: {result['encrypted']}")
        console.print(f"  Records skipped (already encrypted): {result['skipped']}")
        console.print(f"  Total processed: {result['total']}")

        if result["encrypted"] > 0:
            console.print(
                f"\n[green]✓[/green] Successfully encrypted {result['encrypted']} telemetry records"
            )
        elif result["skipped"] > 0:
            console.print(f"\n[cyan]ℹ[/cyan] All {result['skipped']} records already encrypted")
        else:
            console.print("\n[cyan]ℹ[/cyan] No telemetry data found to encrypt")

        console.print()

    except ImportError as e:
        console.print(f"[red]✗[/red] Import error: {e}")
        console.print("\n[yellow]Install required packages:[/yellow]")
        console.print("  pip install cryptography")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)
