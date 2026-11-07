"""
touch2key-stats: attach to the running engine (started by the GUI or the CLI)
and print its live state: measured touch rate, ADB rate cap, PPS alert
threshold, and CPU / memory (RSS & Private) / threads for the engine and workers.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from typing import Any

import psutil

from modules.scripts.runtime_info import (
    STALE_AFTER_S,
    attach,
    labeled_processes,
    read_snapshot,
    snapshot_age,
)

_MB = 1024 * 1024
_LOGICAL_CORES = psutil.cpu_count() or 1


def _num(value: Any) -> str:
    return "--" if value is None else f"{value:g}"


def _proc_stats(role: str, proc: psutil.Process) -> dict[str, Any]:
    try:
        with proc.oneshot():
            raw_cpu = proc.cpu_percent(interval=None)
            full_mem = proc.memory_full_info()
            rss_mb = full_mem.rss / _MB
            priv_mb = getattr(full_mem, "uss", full_mem.rss) / _MB
            threads = proc.num_threads()

            # Normalize across total logical cores to match Task Manager's 0-100% scale
            cpu = (raw_cpu / _LOGICAL_CORES) if raw_cpu is not None else None

            return {
                "role": role,
                "pid": proc.pid,
                "cpu": cpu,
                "rss_mb": rss_mb,
                "priv_mb": priv_mb,
                "threads": threads,
            }
    except psutil.AccessDenied:
        return {"role": role, "pid": proc.pid, "error": "access denied (run elevated)"}
    except psutil.Error:
        return {"role": role, "pid": proc.pid, "error": "exited"}


def _summary_lines(snap: dict[str, Any]) -> list[str]:
    age = snapshot_age(snap)
    if age > STALE_AFTER_S:
        return [f"telemetry stale ({age:.0f}s since last update; engine may be hung)"]

    rate = snap.get("rate_hz")
    rate_txt = "--" if rate is None else f"{rate:.1f} Hz"
    resp = snap.get("respawns") or {}
    workers = snap.get("workers") or {}
    vkb_pid = workers.get("vkb")
    visualizer_pid = workers.get("visualizer")

    parts_1 = [
        f"Rate {rate_txt} ({snap.get('rate_status') or 'n/a'})",
        f"Alert <{_num(snap.get('pps_threshold'))} PPS",
        f"Cap {_num(snap.get('rate_cap_hz'))} Hz",
        f"Cursor: {'Visible' if snap.get('menu_mode') else 'Not Visible'}",
    ]

    parts_2 = [
        f"Touch Events: DOWN {snap.get('downs', 0)}, MOVE {snap.get('moves', 0)}, "
        f"UP {snap.get('ups', 0)}, ALL {snap.get('all', 0)}",
    ]

    parts_3 = [
        f"Respawns: Keyboard {resp.get('keyboard', 0)} / Mouse {resp.get('mouse', 0)}",
        f"Virtual Kbd: {'Active' if vkb_pid else 'Not Active'}",
        f"Visualizer: {'Active' if visualizer_pid else 'Not Active'}",
    ]
    if snap.get("window_lost"):
        parts_3.append("[NO TARGET WINDOW FOUND]")

    return [
        " | ".join(parts_1),
        " | ".join(parts_2),
        " | ".join(parts_3),
    ]


def _format_table(stamp: str, uptime: str, rows: list[dict[str, Any]]) -> list[str]:
    total_cpu = 0.0
    total_rss = 0.0
    total_priv = 0.0

    lines: list[str] = []
    # Header definitions:
    # ROLE: 12 (left) | PID: 7 (right) | CPU: 7 (right) | RSS: 10 (right) | PRIV: 10 (right) | THR: 4 (right)
    header = (
        f"{stamp}  {'ROLE':<12} {'PID':>7}  {'CPU':>7}  {'RSS':>10}  {'PRIV':>10}  {'THR':>4}"
    )
    divider = (
        f"{stamp}  {'-'*12} {'-'*7}  {'-'*7}  {'-'*10}  {'-'*10}  {'-'*4}"
    )

    for r in rows:
        role = r["role"]
        pid = r["pid"]

        if "error" in r:
            lines.append(
                f"{stamp}  {role:<12} {pid:>7}  {'--':>7}  {'--':>10}  {r['error']:>10}  {'--':>4}"
            )
            continue

        cpu = r.get("cpu")
        cpu_txt = "--" if cpu is None else f"{cpu:.1f}%"
        rss_txt = f"{r['rss_mb']:.1f} MB"
        priv_txt = f"{r['priv_mb']:.1f} MB"
        thr = r["threads"]

        total_cpu += cpu or 0.0
        total_rss += r["rss_mb"]
        total_priv += r["priv_mb"]

        lines.append(
            f"{stamp}  {role:<12} {pid:>7}  {cpu_txt:>7}  {rss_txt:>10}  {priv_txt:>10}  {thr:>4}"
        )

    summary_bar = (
        f"{stamp}  Summary: Uptime {uptime} | Processes {len(rows)} | "
        f"CPU {total_cpu:.1f}% | RSS {total_rss:.1f} MB | PRIV {total_priv:.1f} MB"
    )

    return [summary_bar, header, divider, *lines]


def main() -> None:
    parser = argparse.ArgumentParser(description="Touch2Key engine live telemetry")
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
        help="Wipes the previous terminal output (ignored if --json is passed)",
    )
    args = parser.parse_args()

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

            # Wait before gathering stats to establish baseline
            time.sleep(args.interval)

            # Retrieve refreshed snapshot and process tree
            snap = read_snapshot(engine.pid) or snap
            procs = labeled_processes(engine, snap)

            live = {p.pid for _, p in procs}
            for pid in list(tracked):
                if pid not in live:
                    del tracked[pid]

            for _, p in procs:
                cached = tracked.get(p.pid)
                if cached is None or cached != p:
                    try:
                        p.cpu_percent(interval=None)  # Prime baseline
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                    tracked[p.pid] = p

            rows = [
                _proc_stats(role, tracked[p.pid])
                for role, p in procs
                if p.pid in tracked
            ]

            # Calculate Engine Uptime
            try:
                uptime_str = str(
                    datetime.timedelta(seconds=int(time.time() - engine.create_time()))
                )
            except psutil.Error:
                uptime_str = "n/a"

            if args.json:
                payload = {
                    "ts": time.time(),
                    "uptime": uptime_str,
                    "engine": snap,
                    "processes": rows,
                }
                print(json.dumps(payload), flush=True)
            else:
                if args.clear:
                    os.system("cls" if sys.platform == "win32" else "clear")

                stamp = time.strftime("%H:%M:%S")
                print("")
                for summary in _summary_lines(snap):
                    print(f"{stamp}  {summary}", flush=True)

                for line in _format_table(stamp, uptime_str, rows):
                    print(line, flush=True)

            if args.once:
                return

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()