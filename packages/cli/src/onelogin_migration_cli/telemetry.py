"""Telemetry management CLI commands.

This module provides a complete command-line interface for managing
anonymized telemetry, including viewing status, exporting data, and
controlling consent settings.

Usage:
    onelogin-migration-tool telemetry status
    onelogin-migration-tool telemetry export output.json
    onelogin-migration-tool telemetry disable
    onelogin-migration-tool telemetry clear
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer
from onelogin_migration_core.db import get_user_database, get_telemetry_manager
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

app = typer.Typer(name="telemetry", help="Manage anonymized telemetry and analytics")
console = Console()


@app.command()
def status() -> None:
    """Show telemetry status and statistics.

    Examples:
        onelogin-migration-tool telemetry status
    """
    try:
        db = get_user_database()
        telemetry = get_telemetry_manager(db)
        conn = db.connect()

        # Get telemetry settings
        cursor = conn.execute("SELECT * FROM telemetry_settings LIMIT 1")
        settings = cursor.fetchone()

        if not settings:
            console.print("[yellow]⚠[/yellow] Telemetry not configured yet")
            console.print("Run the GUI and accept the license to initialize telemetry settings.")
            return

        settings = dict(settings)
        enabled = settings.get("enabled", 0) == 1
        consent_date = settings.get("user_consent_date")
        installation_id = settings.get("installation_id", "N/A")

        # Display status
        console.print("\n[bold]Telemetry Status[/bold]")
        console.print("─" * 60)

        status_icon = "[green]✓ Enabled[/green]" if enabled else "[red]✗ Disabled[/red]"
        console.print(f"Status:           {status_icon}")
        console.print(f"Consent Date:     {consent_date or 'N/A'}")
        console.print(f"Installation ID:  {installation_id}")
        console.print(
            f"Anonymized:       {'Yes (SHA-256 hashing)' if settings.get('anonymized') else 'No'}"
        )

        # Get statistics
        cursor = conn.execute("SELECT COUNT(*) as count FROM connector_telemetry")
        connector_count = cursor.fetchone()["count"]

        cursor = conn.execute("SELECT COUNT(*) as count FROM error_telemetry")
        error_count = cursor.fetchone()["count"]

        cursor = conn.execute(
            "SELECT COUNT(DISTINCT migration_run_id) as count FROM migration_scenario_telemetry"
        )
        migration_count = cursor.fetchone()["count"]

        console.print("\n[bold]Data Collected (Anonymized)[/bold]")
        console.print("─" * 60)
        console.print(f"Connector decisions:  {connector_count:,}")
        console.print(f"Error patterns:       {error_count:,}")
        console.print(f"Migration scenarios:  {migration_count:,}")

        # Show recent activity
        cursor = conn.execute(
            """
            SELECT timestamp, COUNT(*) as count
            FROM connector_telemetry
            GROUP BY DATE(timestamp)
            ORDER BY timestamp DESC
            LIMIT 7
            """
        )
        recent = cursor.fetchall()

        if recent:
            console.print("\n[bold]Recent Activity (Last 7 Days)[/bold]")
            console.print("─" * 60)
            for row in recent:
                date = (
                    row["timestamp"].split("T")[0] if "T" in row["timestamp"] else row["timestamp"]
                )
                console.print(f"{date}:  {row['count']} connector decisions")

        console.print()

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def export(
    output: Path = typer.Argument(..., help="Output file path for telemetry export (JSON)"),
    include_raw: bool = typer.Option(
        False, "--include-raw", help="Include raw telemetry records (default: summaries only)"
    ),
) -> None:
    """Export telemetry data to JSON file.

    Examples:
        # Export summary statistics
        onelogin-migration-tool telemetry export telemetry-export.json

        # Export with raw telemetry records
        onelogin-migration-tool telemetry export telemetry-export.json --include-raw
    """
    try:
        db = get_user_database()
        conn = db.connect()

        # Get telemetry settings
        cursor = conn.execute("SELECT * FROM telemetry_settings LIMIT 1")
        settings_row = cursor.fetchone()

        if not settings_row:
            console.print("[yellow]⚠[/yellow] No telemetry data found")
            return

        export_data = {
            "export_timestamp": datetime.now().isoformat(),
            "settings": dict(settings_row),
            "summary": {},
            "raw_data": {} if include_raw else None,
        }

        # Summary statistics
        cursor = conn.execute("SELECT * FROM connector_telemetry_summary")
        export_data["summary"]["connector_decisions"] = [dict(row) for row in cursor.fetchall()]

        cursor = conn.execute("SELECT * FROM error_pattern_summary")
        export_data["summary"]["error_patterns"] = [dict(row) for row in cursor.fetchall()]

        cursor = conn.execute("SELECT * FROM scenario_effectiveness")
        export_data["summary"]["migration_scenarios"] = [dict(row) for row in cursor.fetchall()]

        # Raw data (if requested)
        if include_raw:
            cursor = conn.execute(
                "SELECT * FROM connector_telemetry ORDER BY timestamp DESC LIMIT 1000"
            )
            export_data["raw_data"]["connector_telemetry"] = [
                dict(row) for row in cursor.fetchall()
            ]

            cursor = conn.execute(
                "SELECT * FROM error_telemetry ORDER BY timestamp DESC LIMIT 1000"
            )
            export_data["raw_data"]["error_telemetry"] = [dict(row) for row in cursor.fetchall()]

            cursor = conn.execute(
                "SELECT * FROM migration_scenario_telemetry ORDER BY timestamp DESC LIMIT 100"
            )
            export_data["raw_data"]["migration_scenarios"] = [
                dict(row) for row in cursor.fetchall()
            ]

        # Write to file
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w") as f:
            json.dump(export_data, f, indent=2)

        console.print(f"[green]✓[/green] Telemetry data exported to {output}")

        # Show summary
        connector_count = len(export_data["summary"]["connector_decisions"])
        error_count = len(export_data["summary"]["error_patterns"])
        scenario_count = len(export_data["summary"]["migration_scenarios"])

        console.print("\n[bold]Exported:[/bold]")
        console.print(f"  - {connector_count} connector decision summaries")
        console.print(f"  - {error_count} error pattern summaries")
        console.print(f"  - {scenario_count} migration scenario summaries")

        if include_raw:
            raw_connector = len(export_data["raw_data"].get("connector_telemetry", []))
            raw_error = len(export_data["raw_data"].get("error_telemetry", []))
            raw_scenario = len(export_data["raw_data"].get("migration_scenarios", []))
            console.print("\n[bold]Raw Records (limited to last 1000):[/bold]")
            console.print(f"  - {raw_connector} connector decisions")
            console.print(f"  - {raw_error} error events")
            console.print(f"  - {raw_scenario} migration runs")

    except Exception as e:
        console.print(f"[red]✗[/red] Error exporting telemetry: {e}")
        raise typer.Exit(1)


@app.command()
def disable() -> None:
    """Disable telemetry collection.

    This will stop collecting new telemetry data but preserve existing data.
    Use 'telemetry clear' to also remove all collected data.

    Examples:
        onelogin-migration-tool telemetry disable
    """
    try:
        db = get_user_database()
        conn = db.connect()

        # Check if telemetry is already disabled
        cursor = conn.execute("SELECT enabled FROM telemetry_settings LIMIT 1")
        settings = cursor.fetchone()

        if not settings:
            console.print("[yellow]⚠[/yellow] Telemetry not configured")
            return

        if not settings["enabled"]:
            console.print("[yellow]⚠[/yellow] Telemetry is already disabled")
            return

        # Confirm action
        if not Confirm.ask("Are you sure you want to disable telemetry?"):
            console.print("Cancelled")
            return

        # Disable telemetry
        conn.execute("UPDATE telemetry_settings SET enabled = 0")
        conn.commit()

        console.print("[green]✓[/green] Telemetry collection disabled")
        console.print("\nExisting telemetry data has been preserved.")
        console.print(
            "To remove all data, run: [bold]onelogin-migration-tool telemetry clear[/bold]"
        )

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def enable() -> None:
    """Re-enable telemetry collection.

    This will resume collecting anonymized telemetry data.

    Examples:
        onelogin-migration-tool telemetry enable
    """
    try:
        db = get_user_database()
        conn = db.connect()

        # Check current status
        cursor = conn.execute("SELECT enabled FROM telemetry_settings LIMIT 1")
        settings = cursor.fetchone()

        if not settings:
            console.print("[yellow]⚠[/yellow] Telemetry not configured yet")
            console.print("Run the GUI and accept the license to initialize telemetry settings.")
            return

        if settings["enabled"]:
            console.print("[yellow]⚠[/yellow] Telemetry is already enabled")
            return

        # Enable telemetry
        conn.execute("UPDATE telemetry_settings SET enabled = 1")
        conn.commit()

        console.print("[green]✓[/green] Telemetry collection enabled")
        console.print("\nAnonymized telemetry will now be collected (no PII).")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def clear(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Clear all telemetry data.

    This will permanently delete all collected telemetry data while
    preserving your consent settings.

    Examples:
        # Interactive confirmation
        onelogin-migration-tool telemetry clear

        # Skip confirmation
        onelogin-migration-tool telemetry clear --yes
    """
    try:
        db = get_user_database()
        conn = db.connect()

        # Get current counts
        cursor = conn.execute("SELECT COUNT(*) as count FROM connector_telemetry")
        connector_count = cursor.fetchone()["count"]

        cursor = conn.execute("SELECT COUNT(*) as count FROM error_telemetry")
        error_count = cursor.fetchone()["count"]

        cursor = conn.execute("SELECT COUNT(*) as count FROM migration_scenario_telemetry")
        scenario_count = cursor.fetchone()["count"]

        total_records = connector_count + error_count + scenario_count

        if total_records == 0:
            console.print("[yellow]⚠[/yellow] No telemetry data to clear")
            return

        console.print("\n[bold]Records to be deleted:[/bold]")
        console.print(f"  - {connector_count:,} connector decisions")
        console.print(f"  - {error_count:,} error patterns")
        console.print(f"  - {scenario_count:,} migration scenarios")
        console.print(f"\n[bold]Total: {total_records:,} records[/bold]")

        # Confirm action
        if not confirm:
            if not Confirm.ask("\n[bold red]This action cannot be undone.[/bold red] Continue?"):
                console.print("Cancelled")
                return

        # Clear all telemetry data
        conn.execute("DELETE FROM connector_telemetry")
        conn.execute("DELETE FROM error_telemetry")
        conn.execute("DELETE FROM migration_scenario_telemetry")
        conn.commit()

        console.print(f"\n[green]✓[/green] Cleared {total_records:,} telemetry records")
        console.print("\nYour telemetry consent settings have been preserved.")

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def view_summary() -> None:
    """View telemetry summary statistics in a formatted table.

    Examples:
        onelogin-migration-tool telemetry view-summary
    """
    try:
        db = get_user_database()
        conn = db.connect()

        # Connector decisions summary
        console.print("\n[bold]Connector Decision Summary[/bold]")
        console.print("─" * 80)

        cursor = conn.execute(
            "SELECT * FROM connector_telemetry_summary ORDER BY total_decisions DESC LIMIT 10"
        )
        rows = cursor.fetchall()

        if rows:
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Match Type")
            table.add_column("Decisions", justify="right")
            table.add_column("Accepted", justify="right")
            table.add_column("Avg Confidence", justify="right")

            for row in rows:
                table.add_row(
                    row["match_type"] or "N/A",
                    str(row["total_decisions"]),
                    str(row["accepted_count"]),
                    f"{row['avg_confidence']:.1f}%" if row["avg_confidence"] else "N/A",
                )

            console.print(table)
        else:
            console.print("[yellow]No connector decisions recorded yet[/yellow]")

        # Error pattern summary
        console.print("\n[bold]Error Pattern Summary[/bold]")
        console.print("─" * 80)

        cursor = conn.execute(
            "SELECT * FROM error_pattern_summary ORDER BY occurrence_count DESC LIMIT 10"
        )
        rows = cursor.fetchall()

        if rows:
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("Error Category")
            table.add_column("Component")
            table.add_column("Occurrences", justify="right")
            table.add_column("HTTP Status")

            for row in rows:
                table.add_row(
                    row["error_category"],
                    row["component"],
                    str(row["occurrence_count"]),
                    str(row["http_status"]) if row["http_status"] else "N/A",
                )

            console.print(table)
        else:
            console.print("[yellow]No errors recorded yet[/yellow]")

        # Migration scenario effectiveness
        console.print("\n[bold]Migration Scenario Effectiveness[/bold]")
        console.print("─" * 80)

        cursor = conn.execute(
            "SELECT * FROM scenario_effectiveness ORDER BY scenario_count DESC LIMIT 5"
        )
        rows = cursor.fetchall()

        if rows:
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("User Count")
            table.add_column("Scenarios", justify="right")
            table.add_column("Avg Success %", justify="right")
            table.add_column("Avg Duration", justify="right")

            for row in rows:
                avg_duration_min = (
                    row["avg_duration_seconds"] / 60 if row["avg_duration_seconds"] else 0
                )
                table.add_row(
                    row["user_count_bucket"],
                    str(row["scenario_count"]),
                    f"{row['avg_success_rate']:.1f}%" if row["avg_success_rate"] else "N/A",
                    f"{avg_duration_min:.1f} min",
                )

            console.print(table)
        else:
            console.print("[yellow]No migration scenarios recorded yet[/yellow]")

        console.print()

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)
