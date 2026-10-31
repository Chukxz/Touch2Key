"""
Runtime registry and telemetry snapshot for the running engine.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable
from pathlib import Path
import psutil

from modules.utils import READ_ATTEMPTS, RUNTIME_FILE, VISUALIZER_RUNTIME_FILE

logger = logging.getLogger("modules.runtime_info")

PUBLISH_INTERVAL_S = 1.0
STALE_AFTER_S = 5.0  # no update for this long: the publisher (engine) is stuck

# create_time() comes from the same psutil source on both sides, so this only
# has to absorb float rounding; a reused PID differs by far more.
_CREATE_TIME_TOLERANCE_S = 1.0

# Snapshot worker names that are shown under a different (shorter) role, so the
# 8-character role column in the dashboard / touch2key-stats stays aligned.
_ROLE_LABELS = {"visualizer": "visual"}


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------
def _write(payload: dict[str, Any]) -> None:
    tmp = RUNTIME_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, RUNTIME_FILE)  # atomic: readers never see a torn file


def _read() -> dict[str, Any] | None:
    for _ in range(READ_ATTEMPTS):
        try:
            data = json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            time.sleep(0.01)  # writer is mid-replace; retry
    return None


def unregister() -> None:
    """Removes the registry, but only if it still describes THIS process."""
    try:
        data = json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
        if data.get("pid") == os.getpid():
            RUNTIME_FILE.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def register_process(path: Path) -> None:
    """Writes this process's identity (pid + create_time) to `path`."""
    proc = psutil.Process(os.getpid())
    payload = {"pid": proc.pid, "create_time": proc.create_time()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)  # atomic: readers never see a torn file


def unregister_process(path: Path) -> None:
    """Removes `path`, but only if it still describes THIS process."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("pid") == os.getpid():
            path.unlink(missing_ok=True)
    except (OSError, ValueError, AttributeError):
        pass


def read_process(path: Path) -> psutil.Process | None:
    """The live process `path` describes; None if missing, dead, or the PID was reused."""
    for _ in range(READ_ATTEMPTS):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            break
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            time.sleep(0.01)  # writer is mid-replace; retry
    else:
        return None

    try:
        proc = psutil.Process(int(data["pid"]))
        if (
            abs(proc.create_time() - float(data["create_time"]))
            > _CREATE_TIME_TOLERANCE_S
        ):
            return None
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            return None
        return proc
    except (KeyError, TypeError, ValueError, psutil.Error):
        return None


# ---------------------------------------------------------------------------
# Publisher (engine side)
# ---------------------------------------------------------------------------
class TelemetryPublisher:
    """Publishes snapshot_fn() to the registry every `interval` seconds.

    Never raises into the engine: a failing snapshot or write is logged at debug
    level and retried on the next tick.
    """

    def __init__(
        self,
        snapshot_fn: Callable[[], dict[str, Any]],
        role: str = "engine",
        interval: float = PUBLISH_INTERVAL_S,
    ):
        proc = psutil.Process(os.getpid())
        self._identity = {
            "pid": proc.pid,
            "create_time": proc.create_time(),
            "role": role,
        }
        self._snapshot_fn = snapshot_fn
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._publish()  # visible immediately, not one interval later
        self._thread = threading.Thread(
            target=self._run, name="TelemetryPublisher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        unregister()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._publish()

    def _publish(self) -> None:
        try:
            snapshot = self._snapshot_fn()
        except Exception:
            logger.debug("Telemetry snapshot failed.", exc_info=True)
            snapshot = {}
        payload = {**self._identity, "updated_at": time.time(), **snapshot}
        try:
            _write(payload)
        except OSError:
            logger.debug("Could not write telemetry snapshot.", exc_info=True)


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------
def attach() -> tuple[psutil.Process, dict[str, Any]] | None:
    """(engine process, last published payload) if the registry still describes
    a live process; None if it is missing, stale, or the PID was reused."""
    data = _read()
    if data is None:
        return None
    try:
        proc = psutil.Process(int(data["pid"]))
        if (
            abs(proc.create_time() - float(data["create_time"]))
            > _CREATE_TIME_TOLERANCE_S
        ):
            return None
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            return None
        return proc, data
    except (KeyError, TypeError, ValueError, psutil.Error):
        return None


def find_engine() -> psutil.Process | None:
    attached = attach()
    return attached[0] if attached else None


def read_snapshot(expected_pid: int | None = None) -> dict[str, Any] | None:
    """The last published payload, if it belongs to expected_pid (when given).

    No liveness check: callers that already hold the process handle (the GUI,
    which started the engine) don't need one.
    """
    data = _read()
    if data is None:
        return None
    if expected_pid is not None and data.get("pid") != expected_pid:
        return None
    return data


def snapshot_age(data: dict[str, Any]) -> float:
    """Seconds since the engine last published."""
    return max(0.0, time.time() - float(data.get("updated_at", 0.0)))


def worker_processes(engine: psutil.Process) -> list[psutil.Process]:
    """Live descendants of the engine (input workers, virtual keyboard),
    excluding multiprocessing's resource_tracker helper."""
    workers: list[psutil.Process] = []
    try:
        children = engine.children(recursive=True)
    except psutil.Error:
        return workers

    for child in children:
        try:
            if "resource_tracker" in " ".join(child.cmdline()):
                continue
        except psutil.AccessDenied:
            pass  # cannot tell (e.g. elevated child); keep it
        except psutil.Error:
            continue  # exited while we looked
        workers.append(child)
    return workers


def labeled_processes(
    engine: psutil.Process | None, snapshot: dict[str, Any] | None
) -> list[tuple[str, psutil.Process]]:
    """[("engine", proc), ("keyboard", proc), ("mouse", proc), ("vkb", proc),
    ("visual", proc)] -- whichever of them are alive.

    * engine, keyboard, mouse, vkb: the engine's live process tree. Roles come
      from the snapshot (a child that is not in it yet, e.g. just respawned, is
      labelled "other" until the next tick). A worker the snapshot names that
      the tree walk missed is looked up directly, but only if the engine is
      its parent, so a reused PID can't be picked up.
    * visual: the visualizer is NOT an engine child (the GUI button or
      touch2key-visualizer starts it), so it is found through its own registry
      file. That makes it listed even when `engine` is None (engine stopped).
    """
    workers = (snapshot or {}).get("workers") or {}
    _ROLE_LABELS.update(workers)
    roles = {
        pid: _ROLE_LABELS.get(name, "other") for name, pid in workers.items() if pid
    }

    out: list[tuple[str, psutil.Process]] = []
    seen: set[int] = set()

    if engine is not None:
        out.append(("engine", engine))
        seen.add(engine.pid)

        for child in worker_processes(engine):
            out.append((roles.get(child.pid, "other"), child))
            seen.add(child.pid)

        for name, pid in workers.items():
            if not pid or pid in seen or name == "visualizer":
                continue
            try:
                proc = psutil.Process(int(pid))
                if proc.ppid() != engine.pid:
                    continue
            except (TypeError, ValueError, psutil.Error):
                continue
            out.append((_ROLE_LABELS.get(name, "other"), proc))
            seen.add(proc.pid)

    visualizer = read_process(VISUALIZER_RUNTIME_FILE)
    if visualizer is not None and visualizer.pid not in seen:
        out.append((_ROLE_LABELS["visualizer"], visualizer))

    return out
