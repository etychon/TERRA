"""Unit tests for per-device sync instance gate."""

from __future__ import annotations

import threading

from terra_sdwan.sdwan_sync_instance_gate import (
    release_batch_instance_sync,
    try_batch_instance_sync,
    user_priority_instance_sync,
)


def test_user_sync_blocks_batch_acquire() -> None:
    saw_block = threading.Event()

    def batch_worker() -> None:
        assert try_batch_instance_sync(99) is False
        saw_block.set()

    with user_priority_instance_sync(99):
        t = threading.Thread(target=batch_worker)
        t.start()
        assert saw_block.wait(timeout=1)
        t.join(timeout=1)

    assert try_batch_instance_sync(99) is True
    release_batch_instance_sync(99)


def test_batch_holds_lock_until_release() -> None:
    user_started = threading.Event()

    def user_worker() -> None:
        with user_priority_instance_sync(7):
            user_started.set()

    assert try_batch_instance_sync(7) is True
    t = threading.Thread(target=user_worker)
    t.start()
    assert not user_started.wait(timeout=0.15)
    release_batch_instance_sync(7)
    assert user_started.wait(timeout=2)
    t.join(timeout=1)
