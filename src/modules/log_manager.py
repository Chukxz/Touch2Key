from __future__ import annotations

import atexit
import datetime
import logging
import sys
from logging.handlers import MemoryHandler
from pathlib import Path
from modules.utils import LOGS_FOLDER


class _StreamToLogger:
    """Redirects writes from stdout/stderr to a logger instance."""

    def __init__(self, logger: logging.Logger, log_level: int, original_stream):
        self.logger = logger
        self.log_level = log_level
        self.original_stream = original_stream

    def write(self, buf: str) -> None:
        for line in buf.rstrip().splitlines():
            line_str = line.strip()
            if line_str:
                self.logger.log(self.log_level, line_str)

    def flush(self) -> None:
        if hasattr(self.original_stream, "flush"):
            self.original_stream.flush()


class AppLogManager:
    """Configures centralized logging with stdout redirection and on-exit disk dumping."""

    _initialized = False
    _memory_handler: MemoryHandler | None = None
    _target_file_handler: logging.FileHandler | None = None
    _orig_stdout = sys.stdout
    _orig_stderr = sys.stderr

    @classmethod
    def setup_logging(
        cls,
        is_gui: bool = False,
        level: int = logging.INFO,
        log_prefix: str = "touch2key",
    ) -> None:
        """Initializes the root logging pipeline and intercepts stdout/stderr."""
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

        # Buffer up to 100,000 records in memory
        cls._memory_handler = MemoryHandler(
            capacity=100_000,
            flushLevel=logging.CRITICAL + 1,
            target=cls._target_file_handler,
        )
        root_logger.addHandler(cls._memory_handler)

        # 2. Console Handler (CLI Mode: writes to the real stdout stream)
        if not is_gui:
            console_handler = logging.StreamHandler(cls._orig_stdout)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        # 3. Intercept all global print() and sys.stderr outputs
        stdout_logger = logging.getLogger("STDOUT")
        stderr_logger = logging.getLogger("STDERR")
        sys.stdout = _StreamToLogger(stdout_logger, logging.INFO, cls._orig_stdout)
        sys.stderr = _StreamToLogger(stderr_logger, logging.ERROR, cls._orig_stderr)

        atexit.register(cls.flush_and_close)
        cls._initialized = True

    @classmethod
    def flush_and_close(cls) -> None:
        """Restores original streams and flushes buffered logs to disk."""
        sys.stdout = cls._orig_stdout
        sys.stderr = cls._orig_stderr

        if cls._memory_handler:
            cls._memory_handler.flush()
            cls._memory_handler.close()
            cls._memory_handler = None

        if cls._target_file_handler:
            cls._target_file_handler.close()
            cls._target_file_handler = None