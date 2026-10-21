"""
touch2key-stats: attach to the running engine (started by the GUI or the CLI)
and print its live state: measured touch rate, ADB rate cap, PPS alert
threshold, and CPU / memory / threads for the engine and each worker.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import psutil

from modules.runtime_info import (
    STALE_AFTER_S,
    attach,
    labeled_processes,
    read_snapshot,
    snapshot_age,
)

_MB = 1024 * 1024


def _num(value: Any) -> str:
    return "--" if value is None else f"{value:g}"


def _proc_stats(role: str, proc: psutil.Process) -> dict[str, Any]:
    try:
        with proc.oneshot():
            return {
                "role": role,
                "pid": proc.pid,
                "cpu": proc.cpu_percent(interval=None),
                "rss_mb": proc.memory_info().rss / _MB,
                "threads": proc.num_threads(),
            }
    except psutil.AccessDenied:
        return {"role": role, "pid": proc.pid, "error": "access denied (run elevated)"}
    except psutil.Error:
        return {"role": role, "pid": proc.pid, "error": "exited"}


def _summary_line(snap: dict[str, Any]) -> str:
    age = snapshot_age(snap)
    if age > STALE_AFTER_S:
        return f"telemetry stale ({age:.0f}s since last update; engine may be hung)"

    rate = snap.get("rate_hz")
    rate_txt = "--" if rate is None else f"{rate:.1f} Hz"
    resp = snap.get("respawns") or {}
    vkb_pid = snap.get("workers", {}).get("vkb", 0)
    visualizer_pid = snap.get("workers", {}).get("visualizer", 0)
    parts = [
        f"rate {rate_txt} {snap.get('rate_status') or 'n/a'}",
        f"alert<{_num(snap.get('pps_threshold'))} PPS",
        f"cap {_num(snap.get('rate_cap_hz'))} Hz",
        f"mode {'menu' if snap.get('menu_mode') else 'game'}",
        f"respawns kbd {resp.get('keyboard', 0)} / mouse {resp.get('mouse', 0)}",
        f"virtual kbd { 'Active' if vkb_pid > 0 else 'Not Active'}",
        f"visualizer {'Active' if visualizer_pid > 0 else 'Not Active'}",
    ]
    if snap.get("window_lost"):
        parts.append("NO TARGET WINDOW")
    return "  ".join(parts)


def _row_text(row: dict[str, Any]) -> str:
    head = f"{row['role']:<8} pid {row['pid']:<7}"
    if "error" in row:
        return f"{head} {row['error']}"
    return (
        f"{head} cpu {row['cpu']:5.1f}%  rss {row['rss_mb']:7.1f} MB  "
        f"thr {row['threads']:3d}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Touch2Key engine telemetry")
    parser.add_argument(
        "-i", "--interval", type=float, default=1.0, help="Seconds between samples"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Print one sample and exit (exit code 1 if no engine is running)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one JSON object per sample (JSON Lines) instead of text",
    )
    args = parser.parse_args()

    # Reused Process objects: cpu_percent() needs a previous call as baseline.
    tracked: dict[int, psutil.Process] = {}
    announced_waiting = False

    try:
        while True:
            attached = attach()
            if attached is None:
                tracked.clear()
                if args.once:
                    print("[!] No running engine found.")
                    sys.exit(1)
                if not announced_waiting:
                    print("[*] Waiting for engine...")
                    announced_waiting = True
                time.sleep(args.interval)
                continue
            announced_waiting = False

            engine, snap = attached
            procs = labeled_processes(engine, snap)

            live = {p.pid for _, p in procs}
            for pid in list(tracked):
                if pid not in live:
                    del tracked[pid]
            for _, p in procs:
                cached = tracked.get(p.pid)
                if cached is None or cached != p:  # new, or PID reused
                    p.cpu_percent(interval=None)  # prime the baseline
                    tracked[p.pid] = p

            time.sleep(args.interval)

            snap = read_snapshot(engine.pid) or snap  # fresh values after the wait
            rows = [_proc_stats(role, tracked[p.pid]) for role, p in procs]

            if args.json:
                print(
                    json.dumps({"ts": time.time(), "engine": snap, "processes": rows}),
                    flush=True,
                )
            else:
                stamp = time.strftime("%H:%M:%S")
                print(f"{stamp}  {_summary_line(snap)}", flush=True)
                for row in rows:
                    print(f"{stamp}  {_row_text(row)}", flush=True)

            if args.once:
                return
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
