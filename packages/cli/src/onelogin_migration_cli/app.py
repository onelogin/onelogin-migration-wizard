"""Command line entry point for the migration toolkit."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer
from onelogin_migration_core.config import MigrationSettings, load_settings
from onelogin_migration_core.manager import MigrationManager
from rich.console import Console
from rich.logging import RichHandler

from .credentials import app as credentials_app
from .database import app as db_app
from .telemetry import app as telemetry_app

console = Console()
app = typer.Typer(help="Okta to OneLogin migration automation tools")

# Add subcommands
app.add_typer(credentials_app, name="credentials")
app.add_typer(telemetry_app, name="telemetry")
app.add_typer(db_app, name="db")


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def build_manager(
    config_path: Path,
    *,
    dry_run: bool | None = None,
    bulk_user_upload: bool | None = None,
) -> MigrationManager:
    settings = load_settings(config_path)
    if dry_run is not None:
        settings.dry_run = dry_run
    if bulk_user_upload is not None:
        settings.bulk_user_upload = bulk_user_upload
    return MigrationManager(settings, dry_run=settings.dry_run)


@app.command()
def plan(
    config: Path = typer.Option(
        ..., exists=True, readable=True, help="Path to migration YAML configuration."
    ),
    output: Path | None = typer.Option(None, help="Optional path to write Okta export JSON."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Export users, groups, and apps from Okta."""

    configure_logging(verbose)
    manager = build_manager(config, dry_run=True)
    export = manager.export_from_okta()
    default_export_path: Path | None = None
    if verbose:
        default_export_path = manager.save_export(export)
    export_path = (
        manager.save_export(export, output)
        if output
        else default_export_path or manager.save_export(export)
    )

    if verbose and default_export_path:
        console.print(f"Default export saved to [bold]{default_export_path}[/bold]")
        if output:
            console.print(f"Additional export saved to [bold]{export_path}[/bold]")
    else:
        console.print(f"Export saved to [bold]{export_path}[/bold]")


@app.command()
def migrate(
    config: Path = typer.Option(
        ..., exists=True, readable=True, help="Path to migration YAML configuration."
    ),
    export: Path | None = typer.Option(None, help="Optional pre-generated Okta export JSON."),
    dry_run: bool = typer.Option(
        False, help="Skip writes to OneLogin while exercising the workflow."
    ),
    bulk_user_upload: bool = typer.Option(
        False, help="Write a OneLogin bulk upload CSV instead of invoking user APIs."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Execute a migration using API automation."""

    configure_logging(verbose)
    manager = build_manager(config, dry_run=dry_run, bulk_user_upload=bulk_user_upload)
    if verbose and manager.settings.export_directory == Path("artifacts"):
        manager.settings.export_directory = Path.cwd()
        manager.settings.ensure_export_directory()
    export_data = manager.run(export, force_import=True)
    bulk_output = manager.last_bulk_export
    if bulk_user_upload:
        if bulk_output:
            console.print(f"[green]Bulk user upload CSV saved to {bulk_output}.[/green]")
        else:
            console.print("[green]Bulk user upload CSV generation complete.[/green]")
    elif dry_run:
        console.print("[yellow]Dry-run complete. No changes were written to OneLogin.[/yellow]")
    else:
        console.print("[green]Migration complete.[/green]")
    if not export:
        console.print("Export data was generated and stored for auditing.")
    console.print(f"Users processed: {len(export_data.get('users', []))}")


@app.command()
def show_config(
    config: Path = typer.Option(
        ..., exists=True, readable=True, help="Path to migration YAML configuration."
    ),
) -> None:
    """Display the sanitized configuration for troubleshooting."""

    settings = MigrationSettings.from_file(config)
    console.print_json(data=json.dumps(settings.to_dict()))


@app.command()
def provision_attributes(
    config: Path = typer.Option(
        ..., exists=True, readable=True, help="Path to migration YAML configuration."
    ),
    export: Path | None = typer.Option(None, help="Optional pre-generated Okta export JSON."),
    dry_run: bool = typer.Option(
        False, help="Preview attributes without creating them in OneLogin."
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Analyze Okta users and provision custom attributes in OneLogin."""

    configure_logging(verbose)
    manager = build_manager(config, dry_run=dry_run)

    # Load or export users
    if export:
        console.print(f"Loading Okta export from [bold]{export}[/bold]")
        export_data = manager.load_export(export)
    else:
        console.print("Exporting users from Okta...")
        export_data = manager.export_from_okta()

    users = export_data.get("users", [])
    console.print(f"Analyzing {len(users)} users for custom attributes...")

    # Discover custom attributes
    attributes = manager.discover_custom_attributes(users)

    if not attributes:
        console.print("[yellow]No custom attributes found in Okta user profiles.[/yellow]")
        return

    console.print(f"\n[bold]Discovered {len(attributes)} custom attributes:[/bold]")
    for idx, attr in enumerate(sorted(attributes), start=1):
        console.print(f"  {idx:3d}. {attr}")

    if dry_run:
        console.print("\n[yellow]Dry-run enabled. No attributes were created in OneLogin.[/yellow]")
    else:
        console.print(
            f"\n[bold green]Provisioning {len(attributes)} attributes in OneLogin...[/bold green]"
        )
        result = manager.provision_custom_attributes(attributes)

        if result["created"]:
            console.print(f"[green]✓ Created {len(result['created'])} new attributes[/green]")
        if result["existing"]:
            console.print(f"[blue]ℹ {len(result['existing'])} attributes already exist[/blue]")
        if result["failed"]:
            console.print(f"[red]✗ Failed to create {len(result['failed'])} attributes[/red]")
            for attr, error in result["failed"].items():
                console.print(f"  - {attr}: {error}")

        console.print("\n[green]Custom attribute provisioning complete.[/green]")


def main() -> None:
    """Execute the CLI application."""
    app()


if __name__ == "__main__":
    main()
