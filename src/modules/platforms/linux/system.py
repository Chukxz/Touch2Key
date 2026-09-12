from ..base import AbstractSystemConfig
import psutil
import os


class SystemConfig(AbstractSystemConfig):
    def set_dpi_awareness(self):
        # Linux display servers (X11/Wayland) handle scaling
        # at the compositor/toolkit layer. Raw input via uinput operates
        # directly on absolute device coordinates. No API call is needed.
        pass

    def set_timer_resolution(self):
        # Modern Linux kernels use High-Resolution Timers (hrtimers)
        # by default. Python's time.sleep() automatically has nanosecond-level
        # precision natively. No NT API equivalent is required.
        pass

    def set_high_priority(self, pid: int | None, label: str):
        try:
            # If pid is None, psutil.Process() defaults to the current process
            p = psutil.Process(pid if pid is not None else os.getpid())

            # Process priority is handled via 'nice' values.
            # Range is -20 (Highest/Realtime) to 19 (Lowest). 0 is default.
            # -10 is standard "High Priority".
            try:
                p.nice(-10)
            except psutil.AccessDenied:
                # Setting negative nice values on Linux requires root/sudo.
                # If they run the app without sudo, we catch it gracefully.
                print(
                    f"\n[SYSTEM] - Notice: {label} process with PID {pid} priority boost skipped (requires root)."
                )

            p.cpu_affinity(list(range(psutil.cpu_count() or 1)))

            if p.nice() < 0:
                print(
                    f"\n[SYSTEM] - {label} process with PID {pid} set to HIGH (Nice: {p.nice()}, Floating Affinity)."
                )

        except Exception as e:
            print(f"\n[SYSTEM] - Warning: {e}.")
