from __future__ import annotations

import atexit
import datetime
import logging
from logging.handlers import MemoryHandler
from pathlib import Path
from modules.utils import LOGS_FOLDER


class AppLogManager:
    """Configures centralized logging with on-exit disk dumping for CLI and GUI modes."""

    _initialized = False
    _memory_handler: MemoryHandler | None = None
    _target_file_handler: logging.FileHandler | None = None

    @classmethod
    def setup_logging(
        cls,
        is_gui: bool = False,
        level: int = logging.INFO,
        log_prefix: str = "touch2key",
    ) -> None:
        """Initializes the root logging pipeline."""
        if cls._initialized:
            return

        LOGS_FOLDER.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path = LOGS_FOLDER / f"{log_prefix}_{timestamp}.log"

        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 1. Delayed File Target (Flushed on exit)
        cls._target_file_handler = logging.FileHandler(
            log_file_path, mode="w", encoding="utf-8"
        )
        cls._target_file_handler.setFormatter(formatter)

        # Buffer up to 100,000 records in memory; flush only when target closes or capacity hits
        cls._memory_handler = MemoryHandler(
            capacity=100_000,
            flushLevel=logging.CRITICAL + 1,  # Prevent automatic flushing during runtime
            target=cls._target_file_handler,
        )
        root_logger.addHandler(cls._memory_handler)

        # 2. CLI Stream Output (Only when not in GUI mode)
        if not is_gui:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        # Register atomic flush on program termination
        atexit.register(cls.flush_and_close)
        cls._initialized = True

    @classmethod
    def flush_and_close(cls) -> None:
        """Flushes buffered records to the disk file."""
        if cls._memory_handler:
            cls._memory_handler.flush()
            cls._memory_handler.close()
            cls._memory_handler = None

        if cls._target_file_handler:
            cls._target_file_handler.close()
            cls._target_file_handler = None
