"""
Diagnostic utility to inspect resolved ADB path.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from modules.utils import ADB

logger = logging.getLogger("modules.scripts.check_adb")


def run() -> str | None:
    resolved_path: Path | None = None

    if ADB.exists():
        resolved_path = ADB.resolve()
    else:
        system_adb = shutil.which("adb")
        if system_adb:
            resolved_path = Path(system_adb).resolve()

    if resolved_path:
        logger.info("ADB binary located at: %s", resolved_path)
        return str(resolved_path)

    logger.warning("ADB binary not found in project bin directory or system PATH.")
    return None


if __name__ == "__main__":
    run()
