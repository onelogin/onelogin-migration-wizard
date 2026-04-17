"""Progress tracking utilities for migrations."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class ProgressSnapshot:
    """Immutable snapshot of migration progress."""

    totals: dict[str, int]
    completed: dict[str, int]

    def percent(self, category: str) -> float:
        total = self.totals.get(category, 0)
        if total <= 0:
            return 0.0
        return min(100.0, (self.completed.get(category, 0) / total) * 100)

    @property
    def overall_percent(self) -> float:
        total = sum(self.totals.values())
        if total <= 0:
            return 0.0
        completed = sum(self.completed.get(key, 0) for key in self.totals)
        return min(100.0, (completed / total) * 100)


class MigrationProgress:
    """Thread-safe progress tracker with subscriber support."""

    def __init__(self, categories: Iterable[str] | None = None) -> None:
        categories = categories or ("users", "groups", "applications", "policies")
        self._totals: dict[str, int] = dict.fromkeys(categories, 0)
        self._completed: dict[str, int] = dict.fromkeys(categories, 0)
        self._callbacks: list[Callable[[ProgressSnapshot], None]] = []
        self._lock = Lock()

    def set_total(self, category: str, total: int) -> None:
        with self._lock:
            self._totals[category] = max(0, int(total))
        self._notify()

    def increment(self, category: str, count: int = 1) -> None:
        with self._lock:
            self._completed[category] = self._completed.get(category, 0) + max(0, int(count))
        self._notify()

    def subscribe(self, callback: Callable[[ProgressSnapshot], None]) -> None:
        self._callbacks.append(callback)

    def snapshot(self) -> ProgressSnapshot:
        with self._lock:
            return ProgressSnapshot(dict(self._totals), dict(self._completed))

    def reset(self) -> None:
        with self._lock:
            for key in self._totals:
                self._completed[key] = 0
        self._notify()

    def _notify(self) -> None:
        snapshot = self.snapshot()
        for callback in self._callbacks:
            callback(snapshot)


__all__ = ["MigrationProgress", "ProgressSnapshot"]
