from onelogin_migration_core.progress import MigrationProgress


def test_progress_tracking() -> None:
    progress = MigrationProgress(categories=("users", "groups"))

    snapshots = []
    progress.subscribe(snapshots.append)

    progress.set_total("users", 2)
    progress.set_total("groups", 1)

    progress.increment("users")
    progress.increment("groups")
    progress.increment("users")

    assert snapshots[-1].completed["users"] == 2
    assert snapshots[-1].percent("users") == 100.0
    assert round(snapshots[-1].overall_percent, 1) == 100.0
