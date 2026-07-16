"""Serialize SD-WAN Manager instance sync: user-initiated work blocks background batch."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_registry_lock = threading.Lock()
_instance_locks: dict[int, threading.Lock] = {}


def _lock_for(instance_id: int) -> threading.Lock:
    with _registry_lock:
        lk = _instance_locks.get(instance_id)
        if lk is None:
            lk = threading.Lock()
            _instance_locks[instance_id] = lk
        return lk


@contextmanager
def user_priority_instance_sync(instance_id: int) -> Iterator[None]:
    """Hold the instance lock for an operator-initiated sync (blocks until available)."""
    lk = _lock_for(instance_id)
    lk.acquire()
    try:
        yield
    finally:
        lk.release()


def try_batch_instance_sync(instance_id: int) -> bool:
    """Non-blocking acquire for periodic / bulk inventory sync."""
    return _lock_for(instance_id).acquire(blocking=False)


def release_batch_instance_sync(instance_id: int) -> None:
    lk = _lock_for(instance_id)
    if lk.locked():
        lk.release()
