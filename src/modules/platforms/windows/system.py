from ..base import AbstractSystemConfig
import ctypes
import psutil
from modules.utils import NT_TIMER_RES


class SystemConfig(AbstractSystemConfig):
    def set_dpi_awareness(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(
                2
            )  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    def set_timer_resolution(self):
        ctypes.windll.ntdll.NtSetTimerResolution(
            NT_TIMER_RES, 1, ctypes.byref(ctypes.c_ulong())
        )

    def set_high_priority(self, pid: int | None, label: str):
        try:
            p = psutil.Process(pid)
            p.nice(psutil.HIGH_PRIORITY_CLASS)
            p.cpu_affinity(list(range(psutil.cpu_count() or 1)))
            print(
                f"\n[SYSTEM] - {label} process with PID {pid} set to HIGH (Floating Affinity)."
            )
        except Exception as e:
            print(f"\n[SYSTEM] - Warning: {e}.")
