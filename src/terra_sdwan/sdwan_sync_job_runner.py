"""Background SD-WAN inventory sync jobs (progress polling for Administration UI)."""

from __future__ import annotations

import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from terra.app_log_buffer import append_event
from terra.config import get_settings
from terra.crud_sdwan import get_sdwan_manager
from terra.db import get_session_factory
from terra.inventory_extract import utc_iso_for_json
from terra.models import SdWanLinkStatus, SdWanManagerInstance, SyncedDevice
from terra_sdwan.sdwan_sync import (
    SdWanSyncCancelled,
    sync_cellular_history_best_effort,
    sync_devices_for_instance,
    sync_synced_device_detail,
)
from terra_sdwan.sdwan_sync_instance_gate import user_priority_instance_sync

_jobs_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_executor: ThreadPoolExecutor | None = None
_exec_lock = threading.Lock()
_MAX_JOBS = 64


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _exec_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="terra-sdwan-sync")
        return _executor


def _prune_jobs_locked() -> None:
    if len(_jobs) <= _MAX_JOBS:
        return
    # Drop oldest completed/failed first (by finished_at).
    terminal_statuses = ("done", "failed", "cancelled")
    done = [(k, v.get("finished_at") or 0) for k, v in _jobs.items() if v.get("status") in terminal_statuses]
    done.sort(key=lambda x: x[1])
    for k, _ in done[: max(1, len(_jobs) - _MAX_JOBS + 8)]:
        _jobs.pop(k, None)


def _job_snapshot(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        j = _jobs.get(job_id)
        if j is None:
            return None
        return {
            "job_id": job_id,
            "status": j["status"],
            "phase": j.get("phase", ""),
            "percent": int(j.get("percent", 0)),
            "message": str(j.get("message", "")),
            "rows_touched": j.get("rows_touched"),
            "errors": j.get("errors"),
            "error_detail": j.get("error_detail"),
            "last_sync_at_utc": j.get("last_sync_at_utc"),
        }


def get_job(job_id: str, user_id: int) -> dict[str, Any] | None:
    with _jobs_lock:
        j = _jobs.get(job_id)
        if j is None or int(j.get("user_id", -1)) != int(user_id):
            return None
    return _job_snapshot(job_id)


def request_cancel_job(job_id: str, user_id: int) -> tuple[bool, str]:
    """
    Request cooperative cancellation of a queued or running job.

    Returns ``(accepted, reason)`` where ``reason`` is ``not_found``, ``terminal``, or ``ok``.
    """
    with _jobs_lock:
        j = _jobs.get(job_id)
        if j is None or int(j.get("user_id", -1)) != int(user_id):
            return False, "not_found"
        if j.get("status") in ("done", "failed", "cancelled"):
            return False, "terminal"
        j["cancel_requested"] = True
        return True, "ok"


def _run_job(job_id: str, user_id: int, instance_id: int, secret_key: str) -> None:
    with _jobs_lock:
        j0 = _jobs.get(job_id)
        if j0 is None:
            return
        if j0.get("cancel_requested"):
            j0["status"] = "cancelled"
            j0["phase"] = "cancelled"
            j0["percent"] = 0
            j0["message"] = "Cancelled before start."
            j0["finished_at"] = time.time()
            return
        j0["status"] = "running"
        j0["phase"] = "running"
        j0["percent"] = 0
        j0["message"] = "Starting inventory sync…"

    def notify(phase: str, percent: int, message: str) -> None:
        with _jobs_lock:
            jj = _jobs.get(job_id)
            if jj is not None:
                jj["phase"] = phase
                jj["percent"] = percent
                jj["message"] = message

    def cancel_check() -> bool:
        with _jobs_lock:
            jj = _jobs.get(job_id)
            return bool(jj and jj.get("cancel_requested"))

    try:
        notify("connecting", 5, "Connecting to SD-WAN Manager…")
        cellular_stats: dict[str, Any] | None = None
        sf = get_session_factory()
        with sf() as db:
            inst = get_sdwan_manager(db, user_id, instance_id)
            cname = inst.display_name if inst is not None else "(missing)"
            append_event(
                "INFO",
                "sdwan_sync_job",
                f"Job {job_id} started",
                detail=f'user={user_id} cluster="{cname}" instance_id={instance_id}',
            )
            if inst is None:
                raise RuntimeError("SD-WAN manager not found")
            if inst.link_status != SdWanLinkStatus.connected.value:
                raise RuntimeError("Manager is not in connected state — run Verify first")

            notify("connected", 15, "Connected — fetching inventory from Manager…")
            try:
                n, err = sync_devices_for_instance(
                    db,
                    secret_key,
                    inst,
                    progress_notify=notify,
                    cancel_check=cancel_check,
                )
                if err is None:
                    notify("cellular", 92, "Refreshing cellular history…")
                    cellular_stats = sync_cellular_history_best_effort(db, secret_key, inst)
            except SdWanSyncCancelled:
                db.rollback()
                with _jobs_lock:
                    jj = _jobs.get(job_id)
                    if jj is not None:
                        jj["rows_touched"] = None
                        jj["errors"] = 0
                        jj["error_detail"] = None
                        jj["last_sync_at_utc"] = None
                        jj["status"] = "cancelled"
                        jj["phase"] = "cancelled"
                        jj["message"] = "Cancelled by user."
                        jj["finished_at"] = time.time()
                append_event(
                    "INFO",
                    "sdwan_sync_job",
                    f"Job {job_id} cancelled",
                    detail=f'user={user_id} cluster="{inst.display_name}" instance_id={instance_id}',
                )
                return
            db.commit()
            db.refresh(inst)

            last_iso = utc_iso_for_json(inst.devices_last_sync_at_utc) if inst.devices_last_sync_at_utc else None

        with _jobs_lock:
            jj = _jobs[job_id]
            jj["rows_touched"] = max(n, 0)
            jj["errors"] = 1 if err else 0
            jj["error_detail"] = err
            jj["last_sync_at_utc"] = last_iso
            jj["status"] = "done"
            jj["phase"] = "done"
            jj["percent"] = 100
            jj["message"] = "Sync finished." if not err else "Sync finished with errors."
            jj["finished_at"] = time.time()

        append_event(
            "WARNING" if err else "INFO",
            "sdwan_sync_job",
            f"Job {job_id} completed",
            detail=(
                f'cluster="{inst.display_name}" rows={n} errors={1 if err else 0} detail={err or ""}'
                + (
                    f" cellular_buckets={int((cellular_stats or {}).get('buckets_pushed') or 0)}"
                    f" cellular_errors={int((cellular_stats or {}).get('errors') or 0)}"
                    if cellular_stats
                    else ""
                )
            )[:4000],
        )
    except Exception as e:
        msg = str(e)[:500]
        with _jobs_lock:
            jfail = _jobs.get(job_id)
            if jfail is not None:
                jfail["status"] = "failed"
                jfail["phase"] = "failed"
                jfail["percent"] = 100
                jfail["message"] = msg
                jfail["errors"] = 1
                jfail["error_detail"] = msg
                jfail["finished_at"] = time.time()
        detail = msg
        try:
            sf = get_session_factory()
            with sf() as db:
                inst2 = get_sdwan_manager(db, user_id, instance_id)
                if inst2 is not None:
                    detail = f'cluster="{inst2.display_name}" {msg}'
        except Exception:
            pass
        append_event("ERROR", "sdwan_sync_job", f"Job {job_id} failed", detail=detail)


def _run_device_job(job_id: str, user_id: int, device_id: int, secret_key: str) -> None:
    with _jobs_lock:
        j0 = _jobs.get(job_id)
        if j0 is None:
            return
        if j0.get("cancel_requested"):
            j0["status"] = "cancelled"
            j0["phase"] = "cancelled"
            j0["percent"] = 0
            j0["message"] = "Cancelled before start."
            j0["finished_at"] = time.time()
            return
        j0["status"] = "running"
        j0["phase"] = "running"
        j0["percent"] = 0
        j0["message"] = "Starting device sync…"

    def notify(phase: str, percent: int, message: str) -> None:
        with _jobs_lock:
            jj = _jobs.get(job_id)
            if jj is not None:
                jj["phase"] = phase
                jj["percent"] = percent
                jj["message"] = message

    def cancel_check() -> bool:
        with _jobs_lock:
            jj = _jobs.get(job_id)
            return bool(jj and jj.get("cancel_requested"))

    try:
        notify("connecting", 5, "Resolving device and Manager…")
        sf = get_session_factory()
        with sf() as db:
            device = db.get(SyncedDevice, device_id)
            if device is None:
                raise RuntimeError("Device not found")
            inst = db.get(SdWanManagerInstance, device.sdwan_instance_id)
            if inst is None:
                raise RuntimeError("SD-WAN manager not found for this device")
            if inst.link_status != SdWanLinkStatus.connected.value:
                raise RuntimeError("Manager is not in connected state — run Verify first")
            with _jobs_lock:
                jj = _jobs.get(job_id)
                if jj is not None:
                    jj["instance_id"] = inst.id
            append_event(
                "INFO",
                "sdwan_device_sync_job",
                f"Device job {job_id} started",
                detail=f"user={user_id} device_id={device_id} cluster={inst.display_name!r}",
            )
            with user_priority_instance_sync(inst.id):
                try:
                    ok, err = sync_synced_device_detail(
                        db,
                        secret_key,
                        device,
                        inst,
                        progress_notify=notify,
                        cancel_check=cancel_check,
                    )
                except SdWanSyncCancelled:
                    db.rollback()
                    with _jobs_lock:
                        jj = _jobs.get(job_id)
                        if jj is not None:
                            jj["status"] = "cancelled"
                            jj["phase"] = "cancelled"
                            jj["message"] = "Cancelled by user."
                            jj["finished_at"] = time.time()
                    return
                if not ok:
                    raise RuntimeError(err or "Device sync failed")
                db.commit()
                db.refresh(device)

        with _jobs_lock:
            jj = _jobs[job_id]
            jj["rows_touched"] = 1
            jj["errors"] = 0
            jj["error_detail"] = None
            jj["status"] = "done"
            jj["phase"] = "done"
            jj["percent"] = 100
            jj["message"] = "Device sync finished."
            jj["finished_at"] = time.time()
        append_event(
            "INFO",
            "sdwan_device_sync_job",
            f"Device job {job_id} completed",
            detail=f"device_id={device_id}",
        )
    except Exception as e:
        msg = str(e)[:500]
        with _jobs_lock:
            jfail = _jobs.get(job_id)
            if jfail is not None:
                jfail["status"] = "failed"
                jfail["phase"] = "failed"
                jfail["percent"] = 100
                jfail["message"] = msg
                jfail["errors"] = 1
                jfail["error_detail"] = msg
                jfail["finished_at"] = time.time()
        append_event("ERROR", "sdwan_device_sync_job", f"Device job {job_id} failed", detail=msg)


def start_job(user_id: int, instance_id: int) -> str:
    """Queue a sync job; returns opaque ``job_id``."""
    secret_key = get_settings().secret_key
    job_id = secrets.token_urlsafe(18)
    now = time.time()
    with _jobs_lock:
        _prune_jobs_locked()
        _jobs[job_id] = {
            "user_id": user_id,
            "instance_id": instance_id,
            "status": "queued",
            "phase": "queued",
            "percent": 0,
            "message": "Queued…",
            "created_at": now,
            "finished_at": None,
            "rows_touched": None,
            "errors": None,
            "error_detail": None,
            "last_sync_at_utc": None,
            "cancel_requested": False,
        }
    _get_executor().submit(_run_job, job_id, user_id, instance_id, secret_key)
    return job_id


def start_device_job(user_id: int, device_id: int) -> str:
    """Queue a per-device inventory enrich + cellular history job."""
    secret_key = get_settings().secret_key
    job_id = secrets.token_urlsafe(18)
    now = time.time()
    with _jobs_lock:
        _prune_jobs_locked()
        _jobs[job_id] = {
            "user_id": user_id,
            "instance_id": None,
            "device_id": device_id,
            "status": "queued",
            "phase": "queued",
            "percent": 0,
            "message": "Queued…",
            "created_at": now,
            "finished_at": None,
            "rows_touched": None,
            "errors": None,
            "error_detail": None,
            "last_sync_at_utc": None,
            "cancel_requested": False,
        }
    _get_executor().submit(_run_device_job, job_id, user_id, device_id, secret_key)
    return job_id


def shutdown_executor() -> None:
    """Tear down worker pool (app lifespan); next ``start_job`` creates a fresh pool."""
    global _executor
    with _exec_lock:
        if _executor is not None:
            _executor.shutdown(wait=False, cancel_futures=True)
            _executor = None
