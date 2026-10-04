from __future__ import annotations

import atexit
import datetime
import logging
import sys
from logging.handlers import MemoryHandler, QueueHandler
import multiprocessing
from modules.utils import LOGS_FOLDER, DIAGNOSTICS_FOLDER, prune_directory


def initialize_cleanup() -> None:
    """Prunes old log and diagnostics files based on age and count limits."""
    prune_directory(LOGS_FOLDER, max_age_days=60, max_count=100)
    prune_directory(DIAGNOSTICS_FOLDER, max_age_days=60, max_count=20)


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
    """Configures centralized logging with stdout redirection and queue or disk output."""

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
        log_queue: multiprocessing.Queue | None = None,
    ) -> None:
        """Initializes logging pipeline. If log_queue is provided, routes logs to the queue 
        and skips local file creation.
        """
        if cls._initialized:
            return

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        if log_queue is not None:
            # Route all root logs into the multiprocessing queue (no file saved)
            queue_handler = QueueHandler(log_queue)
            queue_handler.setFormatter(formatter)
            root_logger.addHandler(queue_handler)
        else:
            # Standard local file and memory buffering mode
            LOGS_FOLDER.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file_path = LOGS_FOLDER / f"{log_prefix}_{timestamp}.log"

            cls._target_file_handler = logging.FileHandler(
                log_file_path, mode="w", encoding="utf-8"
            )
            cls._target_file_handler.setLevel(logging.DEBUG)
            cls._target_file_handler.setFormatter(formatter)

            cls._memory_handler = MemoryHandler(
                capacity=100_000,
                flushLevel=logging.CRITICAL + 1,
                target=cls._target_file_handler,
            )
            root_logger.addHandler(cls._memory_handler)

            if not is_gui:
                stdout_handler = logging.StreamHandler(cls._orig_stdout)
                stdout_handler.setFormatter(formatter)
                stdout_handler.setLevel(level)
                stdout_handler.addFilter(
                    lambda record: level <= record.levelno < logging.WARNING
                )
                root_logger.addHandler(stdout_handler)

                stderr_handler = logging.StreamHandler(cls._orig_stderr)
                stderr_handler.setFormatter(formatter)
                stderr_handler.setLevel(logging.WARNING)
                root_logger.addHandler(stderr_handler)

            atexit.register(cls.flush_and_close)

        # Always intercept global print() and sys.stderr outputs
        stdout_logger = logging.getLogger("STDOUT")
        stderr_logger = logging.getLogger("STDERR")
        sys.stdout = _StreamToLogger(stdout_logger, logging.INFO, cls._orig_stdout)
        sys.stderr = _StreamToLogger(stderr_logger, logging.ERROR, cls._orig_stderr)

        cls._initialized = True

    @classmethod
    def flush_and_close(cls) -> None:
        """Restores original streams and flushes buffered logs if active."""
        sys.stdout = cls._orig_stdout
        sys.stderr = cls._orig_stderr

        if cls._memory_handler:
            cls._memory_handler.flush()
            cls._memory_handler.close()
            cls._memory_handler = None

        if cls._target_file_handler:
            cls._target_file_handler.close()
            cls._target_file_handler = None