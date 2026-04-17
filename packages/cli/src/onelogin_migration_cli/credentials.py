"""Credential management CLI commands.

This module provides a complete command-line interface for managing
secure credentials, including storage, retrieval, migration from YAML,
and audit log viewing.

Usage:
    onelogin-migration-tool credentials set okta token
    onelogin-migration-tool credentials list
    onelogin-migration-tool credentials migrate config/migration.yaml
"""

from __future__ import annotations

from pathlib import Path

import typer
from onelogin_migration_core.config_parser import CredentialExtractor
from onelogin_migration_core.credentials import AutoSaveCredentialManager
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

app = typer.Typer(name="credentials", help="Manage secure credentials for migration")
console = Console()


@app.command()
def set(
    service: str = typer.Argument(..., help="Service name (e.g., 'okta', 'onelogin')"),
    key: str = typer.Argument(..., help="Credential key (e.g., 'token', 'client_id')"),
    value: str | None = typer.Option(
        None, "--value", "-v", help="Credential value (will prompt if not provided)"
    ),
    backend: str = typer.Option(
        "keyring", "--backend", "-b", help="Storage backend (keyring/vault/memory)"
    ),
    vault_password: str | None = typer.Option(
        None, "--vault-password", help="Vault password (required for vault backend)"
    ),
):
    """Store a credential securely.

    Examples:
        # Interactive prompt for value
        onelogin-migration-tool credentials set okta token

        # Provide value directly (not recommended for sensitive data)
        onelogin-migration-tool credentials set okta token --value "00abc123..."

        # Store in encrypted vault
        onelogin-migration-tool credentials set okta token --backend vault --vault-password "mypass"
    """
    # Prompt for value if not provided
    if not value:
        value = Prompt.ask(f"Enter value for {service}.{key}", password=True)

    if not value:
        console.print("[red]✗[/red] Value cannot be empty")
        raise typer.Exit(1)

    # Prompt for vault password if using vault backend
    if backend == "vault" and not vault_password:
        vault_password = Prompt.ask("Enter vault password", password=True)

    try:
        manager = AutoSaveCredentialManager(
            storage_backend=backend, vault_password=vault_password, enable_audit_log=True
        )

        success = manager.auto_save_credential(service, key, value)

        if success:
            console.print(f"[green]✓[/green] Stored {service}.{key} in {backend}")
        else:
            console.print("[red]✗[/red] Failed to store credential")
            raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def get(
    service: str = typer.Argument(..., help="Service name"),
    key: str = typer.Argument(..., help="Credential key"),
    reveal: bool = typer.Option(False, "--reveal", "-r", help="Show full value (default: masked)"),
    backend: str = typer.Option("keyring", "--backend", "-b", help="Storage backend"),
    vault_password: str | None = typer.Option(
        None, "--vault-password", help="Vault password (for vault backend)"
    ),
):
    """Retrieve a credential.

    Examples:
        # Show masked value
        onelogin-migration-tool credentials get okta token

        # Show full value
        onelogin-migration-tool credentials get okta token --reveal

        # Get from vault
        onelogin-migration-tool credentials get okta token --backend vault --vault-password "mypass"
    """
    if backend == "vault" and not vault_password:
        vault_password = Prompt.ask("Enter vault password", password=True)

    try:
        manager = AutoSaveCredentialManager(storage_backend=backend, vault_password=vault_password)

        credential = manager.get_credential(service, key)

        if credential:
            if reveal:
                console.print(f"{service}.{key}: [yellow]{credential.reveal()}[/yellow]")
            else:
                # Mask middle characters
                value = credential.reveal()
                if len(value) <= 8:
                    masked = "●" * len(value)
                else:
                    masked = value[:4] + "●" * (len(value) - 8) + value[-4:]
                console.print(f"{service}.{key}: {masked}")
                console.print("[dim]Use --reveal to see full value[/dim]")
        else:
            console.print(f"[yellow]![/yellow] Credential {service}.{key} not found")
            raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def list(
    backend: str | None = typer.Option(None, "--backend", "-b", help="Filter by backend"),
    show_values: bool = typer.Option(False, "--show-values", help="Show masked values"),
):
    """List all stored credentials.

    Examples:
        # List all credentials
        onelogin-migration-tool credentials list

        # List only keyring credentials
        onelogin-migration-tool credentials list --backend keyring

        # Show masked values
        onelogin-migration-tool credentials list --show-values
    """
    try:
        # Try to list from all backends
        backends_to_check = [backend] if backend else ["keyring", "memory"]

        all_credentials = []

        for check_backend in backends_to_check:
            try:
                manager = AutoSaveCredentialManager(storage_backend=check_backend)
                credentials = manager.list_credentials()
                all_credentials.extend(credentials)
            except Exception as e:
                console.print(f"[dim]Could not access {check_backend}: {e}[/dim]")

        if not all_credentials:
            console.print("[yellow]No credentials stored[/yellow]")
            return

        table = Table(title="Stored Credentials")
        table.add_column("Service", style="cyan")
        table.add_column("Key", style="magenta")
        table.add_column("Backend", style="green")
        if show_values:
            table.add_column("Value", style="dim")

        for service, key, cred_backend in all_credentials:
            if show_values:
                table.add_row(service, key, cred_backend, "●●●●●●●●")
            else:
                table.add_row(service, key, cred_backend)

        console.print(table)

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def delete(
    service: str = typer.Argument(..., help="Service name"),
    key: str = typer.Argument(..., help="Credential key"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
    backend: str = typer.Option("keyring", "--backend", "-b", help="Storage backend"),
    vault_password: str | None = typer.Option(
        None, "--vault-password", help="Vault password (for vault backend)"
    ),
):
    """Delete a credential.

    Examples:
        # Delete with confirmation
        onelogin-migration-tool credentials delete okta token

        # Delete without confirmation
        onelogin-migration-tool credentials delete okta token --force
    """
    if not force:
        confirm = Confirm.ask(f"Delete {service}.{key}?")
        if not confirm:
            console.print("Cancelled")
            return

    if backend == "vault" and not vault_password:
        vault_password = Prompt.ask("Enter vault password", password=True)

    try:
        manager = AutoSaveCredentialManager(
            storage_backend=backend, vault_password=vault_password, enable_audit_log=True
        )

        success = manager.delete_credential(service, key)

        if success:
            console.print(f"[green]✓[/green] Deleted {service}.{key}")
        else:
            console.print("[red]✗[/red] Failed to delete credential")
            raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def test(
    service: str = typer.Argument(..., help="Service to test (okta/onelogin)"),
    backend: str = typer.Option("keyring", "--backend", "-b", help="Storage backend"),
    vault_password: str | None = typer.Option(
        None, "--vault-password", help="Vault password (for vault backend)"
    ),
):
    """Test credentials by attempting to authenticate with the service.

    Examples:
        onelogin-migration-tool credentials test okta
        onelogin-migration-tool credentials test onelogin
    """
    console.print(f"Testing {service} credentials...")

    if backend == "vault" and not vault_password:
        vault_password = Prompt.ask("Enter vault password", password=True)

    try:
        manager = AutoSaveCredentialManager(storage_backend=backend, vault_password=vault_password)

        if service == "okta":
            # Check for required credentials
            domain = manager.get_credential("okta", "domain")
            token = manager.get_credential("okta", "token")

            if not token:
                console.print("[red]✗[/red] Missing okta.token credential")
                raise typer.Exit(1)

            # TODO: Perform actual connection test with Okta API
            # For now, just verify credentials exist
            console.print("[green]✓[/green] Okta credentials found")
            console.print(f"  Domain: {domain.reveal() if domain else 'Not set'}")
            console.print(f"  Token: {'●' * 20}")

        elif service == "onelogin":
            # Check for required credentials
            client_id = manager.get_credential("onelogin", "client_id")
            client_secret = manager.get_credential("onelogin", "client_secret")
            region = manager.get_credential("onelogin", "region")

            if not client_id or not client_secret:
                console.print("[red]✗[/red] Missing onelogin credentials")
                raise typer.Exit(1)

            # TODO: Perform actual connection test with OneLogin API
            console.print("[green]✓[/green] OneLogin credentials found")
            console.print(f"  Client ID: {client_id.reveal()[:10]}...")
            console.print(f"  Client Secret: {'●' * 20}")
            console.print(f"  Region: {region.reveal() if region else 'Not set'}")

        else:
            console.print(f"[red]✗[/red] Unknown service: {service}")
            console.print("Supported services: okta, onelogin")
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def migrate(
    config_path: Path = typer.Argument(..., help="Path to YAML config file"),
    backend: str = typer.Option("keyring", "--backend", "-b", help="Storage backend"),
    vault_password: str | None = typer.Option(
        None, "--vault-password", help="Vault password (for vault backend)"
    ),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="Create backup of original"),
):
    """Migrate credentials from YAML to secure storage.

    This command:
    1. Detects all credentials in the YAML config
    2. Stores them securely in the chosen backend
    3. Creates a backup of the original file
    4. Saves a sanitized version without credentials

    Examples:
        # Migrate to keyring (default)
        onelogin-migration-tool credentials migrate config/migration.yaml

        # Migrate to encrypted vault
        onelogin-migration-tool credentials migrate config/migration.yaml \\
            --backend vault --vault-password "mypass"

        # Migrate without creating backup
        onelogin-migration-tool credentials migrate config/migration.yaml --no-backup
    """
    if not config_path.exists():
        console.print(f"[red]✗[/red] File not found: {config_path}")
        raise typer.Exit(1)

    console.print(f"Extracting credentials from [cyan]{config_path}[/cyan]...")

    if backend == "vault" and not vault_password:
        vault_password = Prompt.ask("Enter vault password", password=True)

    try:
        manager = AutoSaveCredentialManager(
            storage_backend=backend, vault_password=vault_password, enable_audit_log=True
        )

        extractor = CredentialExtractor()

        sanitized_config, extracted, backup_path = extractor.extract_and_secure(
            config_path, manager
        )

        console.print(f"[green]✓[/green] Extracted {len(extracted)} credentials:")
        for cred_name in extracted:
            console.print(f"  • {cred_name}")

        if backup:
            console.print(f"[blue]ℹ[/blue] Backup created: {backup_path}")

        console.print(f"[green]✓[/green] Config sanitized and saved to {config_path}")
        console.print()
        console.print("[yellow]⚠[/yellow]  Important: Keep your backup safe!")
        console.print("[dim]The sanitized config no longer contains credentials.[/dim]")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def export(
    output_path: Path = typer.Argument(..., help="Output path for vault export"),
    vault_password: str | None = typer.Option(None, "--vault-password", help="Vault password"),
):
    """Export encrypted vault for backup.

    This is only supported for the vault backend and creates a copy of
    the encrypted vault file for backup purposes.

    Example:
        onelogin-migration-tool credentials export backup/vault-2024-01-15.enc
    """
    vault_path = Path.home() / ".onelogin-migration" / "vault.enc"

    if not vault_path.exists():
        console.print("[red]✗[/red] Vault file not found")
        console.print(f"[dim]Expected location: {vault_path}[/dim]")
        raise typer.Exit(1)

    try:
        import shutil

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(vault_path, output_path)
        console.print(f"[green]✓[/green] Vault exported to {output_path}")
        console.print("[yellow]⚠[/yellow]  Keep this backup secure!")
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command(name="import")
def import_vault(
    input_path: Path = typer.Argument(..., help="Path to vault export file"),
    vault_password: str | None = typer.Option(
        None, "--vault-password", help="Vault password to verify"
    ),
):
    """Import vault from backup.

    This command restores a previously exported vault file.

    Example:
        onelogin-migration-tool credentials import backup/vault-2024-01-15.enc
    """
    if not input_path.exists():
        console.print(f"[red]✗[/red] File not found: {input_path}")
        raise typer.Exit(1)

    if not vault_password:
        vault_password = Prompt.ask("Enter vault password to verify", password=True)

    console.print("Verifying vault integrity...")

    try:
        # Verify we can decrypt the vault before importing
        import json

        from .credentials import Argon2VaultV2

        vault = Argon2VaultV2()
        with open(input_path) as f:
            encrypted_vault = json.load(f)

        # Try to decrypt to verify password
        vault.decrypt(encrypted_vault, vault_password)

        console.print("[green]✓[/green] Vault verified successfully")

        # Copy to standard location
        vault_path = Path.home() / ".onelogin-migration" / "vault.enc"
        vault_path.parent.mkdir(parents=True, exist_ok=True)

        import shutil

        shutil.copy(input_path, vault_path)

        console.print(f"[green]✓[/green] Vault imported to {vault_path}")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        console.print("[yellow]![/yellow] Make sure the vault password is correct")
        raise typer.Exit(1)


@app.command()
def audit(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of events to show"),
    event_type: str | None = typer.Option(None, "--type", "-t", help="Filter by event type"),
):
    """View audit log.

    Shows recent credential operations for security monitoring and compliance.

    Examples:
        # Show last 20 events
        onelogin-migration-tool credentials audit

        # Show last 50 events
        onelogin-migration-tool credentials audit --limit 50

        # Filter by event type
        onelogin-migration-tool credentials audit --type credential_stored
    """
    try:
        manager = AutoSaveCredentialManager(storage_backend="keyring", enable_audit_log=True)

        summary = manager.get_audit_summary()

        console.print("[bold]Audit Summary[/bold]")
        console.print(f"Total events: {summary['total_events']}")
        console.print()

        if summary.get("by_type"):
            console.print("[bold]Events by type:[/bold]")
            for etype, count in summary["by_type"].items():
                if event_type and etype != event_type:
                    continue
                console.print(f"  {etype}: {count}")
            console.print()

        if summary.get("recent_failures"):
            console.print("[bold red]Recent failures:[/bold red]")
            for event in summary["recent_failures"][:5]:
                timestamp = event.get("timestamp", "Unknown")
                service = event.get("service", "Unknown")
                key = event.get("key", "Unknown")
                console.print(f"  [{timestamp}] {service}.{key}")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def validate(
    config_path: Path = typer.Argument(..., help="Path to YAML config file to validate"),
):
    """Validate that a config has been properly sanitized.

    Checks that no credential values remain in plaintext.

    Example:
        onelogin-migration-tool credentials validate config/migration.yaml
    """
    if not config_path.exists():
        console.print(f"[red]✗[/red] File not found: {config_path}")
        raise typer.Exit(1)

    try:
        extractor = CredentialExtractor()
        is_sanitized, remaining = extractor.validate_sanitized_config(config_path)

        if is_sanitized:
            console.print("[green]✓[/green] Config is properly sanitized")
            console.print("[dim]No plaintext credentials detected[/dim]")
        else:
            console.print(f"[red]✗[/red] Config still contains {len(remaining)} credentials:")
            for cred in remaining:
                console.print(f"  • {cred}")
            console.print()
            console.print("Run 'credentials migrate' to secure these credentials")
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
