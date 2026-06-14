"""In-memory TTL cache with a diskcache-compatible surface.

This is an internal replacement for `diskcache.Cache` — same call sites
in `cache.py` work without change. It is process-local (no persistence
across restarts), which matches the real behavior of parts-mcp in
production: the hosted container is redeployed regularly and the local
stdio session is short-lived, so persistent caching never bought us
anything.

The class implements only the diskcache methods that parts-mcp uses:
`get`, `set(expire=...)`, `delete`, `clear`, `iterkeys`, `stats`,
`volume`, and `__len__`. Unused methods (transact, push, pull, pop,
touch, evict, check, expire, cull, etc.) are intentionally absent.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from typing import Any


class TTLCache:
    """Thread-safe in-memory cache with per-key TTLs."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _is_expired(expiry: float | None) -> bool:
        return expiry is not None and time.monotonic() >= expiry

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self._misses += 1
                return default
            value, expiry = entry
            if self._is_expired(expiry):
                del self._data[key]
                self._misses += 1
                return default
            self._hits += 1
            return value

    def set(self, key: str, value: Any, expire: int | float | None = None) -> None:
        expiry = time.monotonic() + expire if expire else None
        with self._lock:
            self._data[key] = (value, expiry)

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0

    def iterkeys(self) -> Iterator[str]:
        with self._lock:
            snapshot = list(self._data.items())
        for key, (_, expiry) in snapshot:
            if not self._is_expired(expiry):
                yield key

    def stats(self, enable: bool = False) -> tuple[int, int]:
        """Return `(hits, misses)`. `enable` is accepted for API parity with
        diskcache but ignored — stats are always collected."""
        del enable
        with self._lock:
            return (self._hits, self._misses)

    def volume(self) -> int:
        """Diskcache reports bytes on disk. For an in-memory cache we return
        0 — there is no disk volume to report. Callers that want an item
        count should use `len()` instead."""
        return 0

    def __len__(self) -> int:
        with self._lock:
            return sum(
                1 for (_, expiry) in self._data.values()
                if not self._is_expired(expiry)
            )

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None
