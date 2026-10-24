"""
touch2key-stats: attach to the running engine (started by the GUI or the CLI)
and print its live state: measured touch rate, ADB rate cap, PPS alert
threshold, and CPU / memory / threads for the engine and each worker.
"""

from __future__ import annotations

import os
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


def _summary_lines(snap: dict[str, Any]) -> tuple[str, ...]:
    age = snapshot_age(snap)
    if age > STALE_AFTER_S:
        return (f"telemetry stale ({age:.0f}s since last update; engine may be hung)",)

    rate = snap.get("rate_hz")
    rate_txt = "--" if rate is None else f"{rate:.1f} Hz"
    resp = snap.get("respawns") or {}
    vkb_pid = snap.get("workers", {}).get("vkb")
    visualizer_pid = snap.get("workers", {}).get("visualizer")
    parts_1 = [
        f"Rate {rate_txt} {snap.get('rate_status') or 'n/a'}",
        f"Alert <{_num(snap.get('pps_threshold'))} PPS",
        f"Cap {_num(snap.get('rate_cap_hz'))} Hz",
        f"Cursor: {'Visible' if snap.get('menu_mode') else 'Not Visible'}",
    ]

    parts_2 = [
        f"Touch Events Count: DOWN {snap.get("downs", 0)}, MOVE {snap.get("moves", 0)}, UP {snap.get("ups", 0)}, ALL {snap.get("all", 0)}",
    ]

    parts_3 = [
        f"Respawns: Keyboard {resp.get('keyboard', 0)} / Mouse {resp.get('mouse', 0)}",
        f"Virtual Kbd {'Not Active' if vkb_pid is None else 'Active'}",
        f"Visualizer {'Not Active' if visualizer_pid is None else 'Active'}",
    ]
    if snap.get("window_lost"):
        parts_3.append("NO TARGET WINDOW")
    return "  ".join(parts_1), "  ".join(parts_2), "  ".join(parts_3)


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
    parser.add_argument(
        "-c",
        "--clear",
        action="store_true",
        help="Wipes the previous terminal output (if json flag is not set)",
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
                if args.clear:
                    os.system("cls" if sys.platform == "win32" else "clear")

                stamp = time.strftime("%H:%M:%S")
                summaries = _summary_lines(snap)
                for summary in summaries:
                    print(f"{stamp}  {summary}", flush=True)
                for row in rows:
                    print(f"{stamp}  {_row_text(row)}", flush=True)

            if args.once:
                return

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
