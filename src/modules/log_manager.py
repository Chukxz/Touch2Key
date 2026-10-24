from __future__ import annotations

import atexit
import os
import collections
import contextlib
import datetime
import logging
import sys
import shutil
import threading
from logging.handlers import MemoryHandler, QueueHandler
import multiprocessing
from modules.utils import LOGS_FOLDER, DIAGNOSTICS_FOLDER, prune_directory

_CONSOLE_MODES = ("auto", "on", "off")


def initialize_cleanup() -> None:
    """Prunes old log and diagnostics files based on age and count limits."""
    prune_directory(LOGS_FOLDER, max_age_days=60, max_count=100)
    prune_directory(DIAGNOSTICS_FOLDER, max_age_days=60, max_count=20)


def _normalize_console_mode(mode: str | bool | None) -> str:
    if mode is True:
        return "on"
    if mode is False:
        return "off"
    mode = (mode or "auto").lower()
    return mode if mode in _CONSOLE_MODES else "auto"


def _isatty(stream) -> bool:
    try:
        return bool(stream is not None and stream.isatty())
    except Exception:
        return False


def _windows_console_process_count() -> int:
    """Processes attached to our console; 0 if we have no console (Windows)."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        if not kernel32.GetConsoleWindow():
            return 0
        buf = (ctypes.c_uint * 16)()
        return int(kernel32.GetConsoleProcessList(buf, 16))
    except Exception:
        return 0


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


class _SuspendableStreamHandler(logging.StreamHandler):
    """StreamHandler that can hold records and replay them in order on resume.

    Suspension is nestable (counter). Filters/levels are applied at handle()
    time, so only records that would have been printed are held. Printed lines
    are also appended to a shared history deque.
    """

    def __init__(self, stream, max_held: int = 5000, history=None):
        super().__init__(stream)
        self._suspend_depth = 0
        self._max_held = max_held
        self._held: collections.deque[logging.LogRecord] = collections.deque()
        self._dropped = 0
        self._history = history

    def _write(self, record: logging.LogRecord) -> None:
        if self._history is not None:
            try:
                self._history.append(self.format(record))
            except Exception:
                pass
        super().emit(record)

    def emit(self, record: logging.LogRecord) -> None:
        # Called with the handler lock held (Handler.handle).
        if self._suspend_depth > 0:
            if len(self._held) >= self._max_held:
                self._held.popleft()
                self._dropped += 1
            self._held.append(record)
            return
        self._write(record)

    def suspend(self) -> None:
        self.acquire()
        try:
            self._suspend_depth += 1
        finally:
            self.release()

    def resume(self, force: bool = False) -> None:
        self.acquire()
        try:
            self._suspend_depth = 0 if force else max(0, self._suspend_depth - 1)
            if self._suspend_depth > 0:
                return
            if self._dropped:
                try:
                    self.stream.write(
                        f"[{self._dropped} log lines dropped while suspended]\n"
                    )
                except Exception:
                    pass
                self._dropped = 0
            while self._held:
                self._write(self._held.popleft())
            self.flush()
        finally:
            self.release()


class AppLogManager:
    """Configures centralized logging with stdout redirection and queue or disk output."""

    _initialized = False
    _memory_handler: MemoryHandler | None = None
    _target_file_handler: logging.FileHandler | None = None
    _console_handlers: list[_SuspendableStreamHandler] = []
    _console_level = logging.INFO
    _console_allowed = False  # False in queue (worker) mode
    _formatter: logging.Formatter | None = None
    _history: collections.deque[str] = collections.deque(maxlen=1000)
    _live_lock = threading.Lock()
    _live_active = False
    _orig_stdout = sys.stdout
    _orig_stderr = sys.stderr

    # ------------------------------------------------------------------
    # Terminal detection
    # ------------------------------------------------------------------
    @classmethod
    def has_terminal(cls) -> bool:
        """True if there is a usable terminal to print to.

        False under pythonw.exe / desktop-icon launches without a console.
        """
        if cls._orig_stdout is None and cls._orig_stderr is None:
            return False
        if sys.platform == "win32":
            return _windows_console_process_count() > 0
        return _isatty(cls._orig_stdout) or _isatty(cls._orig_stderr)

    @classmethod
    def owns_console(cls) -> bool:
        """Heuristic (Windows): the console was created for this process, i.e.
        double-click launch of a console script rather than a shell launch.

        Entry-point launcher stubs add a process, so up to 2 counts as owned.
        Always False on other platforms.
        """
        if sys.platform != "win32":
            return False
        count = _windows_console_process_count()
        return 0 < count <= 2

    @classmethod
    def console_enabled(cls) -> bool:
        return bool(cls._console_handlers)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    @classmethod
    def setup_logging(
        cls,
        level: int = logging.INFO,
        log_prefix: str = "touch2key",
        log_queue: multiprocessing.Queue | None = None,
        console: str | bool = "on",
    ) -> None:
        """Initializes logging pipeline. If log_queue is provided, routes logs to the queue
        and skips local file creation.

        console: "auto" (only if a terminal exists), "on" (whenever a stream
        exists), "off". Booleans are accepted. Can be changed later with
        set_console(). Ignored in queue mode.
        """
        if cls._initialized:
            return

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        cls._formatter = formatter
        cls._console_level = level

        if log_queue is not None:
            # Route all root logs into the multiprocessing queue (no file saved)
            queue_handler = QueueHandler(log_queue)
            root_logger.addHandler(queue_handler)
            cls._console_allowed = False
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
                flushLevel=logging.ERROR,
                target=cls._target_file_handler,
            )
            root_logger.addHandler(cls._memory_handler)

            cls._console_allowed = True
            cls.set_console(console)

            atexit.register(cls.flush_and_close)

        # Always intercept global print() and sys.stderr outputs
        stdout_logger = logging.getLogger("STDOUT")
        stderr_logger = logging.getLogger("STDERR")
        sys.stdout = _StreamToLogger(stdout_logger, logging.INFO, cls._orig_stdout)
        sys.stderr = _StreamToLogger(stderr_logger, logging.ERROR, cls._orig_stderr)

        cls._initialized = True

    # ------------------------------------------------------------------
    # Runtime console toggle
    # ------------------------------------------------------------------
    @classmethod
    def set_console(cls, mode: str | bool | None = "auto") -> bool:
        """Turn terminal logging on/off at runtime. Returns True if active.

        Never raises: with no usable stream, "on" simply stays inactive.
        """
        if not cls._console_allowed:
            return False

        mode = _normalize_console_mode(mode)
        want = mode == "on" or (mode == "auto" and cls.has_terminal())

        if want and not cls._console_handlers:
            cls._add_console_handlers()
            if not cls._console_handlers:
                logging.getLogger(__name__).debug(
                    "Terminal logging requested (%s) but no console stream exists.",
                    mode,
                )
        elif not want and cls._console_handlers:
            cls._remove_console_handlers()
        return bool(cls._console_handlers)

    @classmethod
    def _add_console_handlers(cls) -> None:
        root_logger = logging.getLogger()
        level = cls._console_level

        # No-console launches (pythonw.exe) have None streams;
        # StreamHandler(None) falls back to sys.stderr and recurses.
        if cls._orig_stdout is not None:
            stdout_handler = _SuspendableStreamHandler(
                cls._orig_stdout, history=cls._history
            )
            stdout_handler.setFormatter(cls._formatter)
            stdout_handler.setLevel(level)
            stdout_handler.addFilter(
                lambda record: level <= record.levelno < logging.WARNING
            )
            root_logger.addHandler(stdout_handler)
            cls._console_handlers.append(stdout_handler)

        if cls._orig_stderr is not None:
            stderr_handler = _SuspendableStreamHandler(
                cls._orig_stderr, history=cls._history
            )
            stderr_handler.setFormatter(cls._formatter)
            stderr_handler.setLevel(logging.WARNING)
            root_logger.addHandler(stderr_handler)
            cls._console_handlers.append(stderr_handler)

    @classmethod
    def _remove_console_handlers(cls) -> None:
        cls.end_live_line()
        root_logger = logging.getLogger()
        for handler in cls._console_handlers:
            handler.resume(force=True)  # don't swallow held records
            root_logger.removeHandler(handler)
        cls._console_handlers.clear()

    @classmethod
    @contextlib.contextmanager
    def raw_streams(cls):
        """Temporarily restore the real stdout/stderr.

        Use around code that prints formatted text, e.g. argparse usage and
        --help, which the redirect would otherwise strip and split into
        prefixed log lines. With no terminal the streams may be None; the
        redirect is then left in place so nothing crashes.
        """
        saved = sys.stdout, sys.stderr
        if cls._orig_stdout is not None:
            sys.stdout = cls._orig_stdout
        if cls._orig_stderr is not None:
            sys.stderr = cls._orig_stderr
        try:
            yield
        finally:
            sys.stdout, sys.stderr = saved

    @classmethod
    def write_record(cls, record: logging.LogRecord) -> None:
        """Write a record (e.g. from the worker queue) to the file log only."""
        if cls._memory_handler:
            cls._memory_handler.handle(record)

    # ------------------------------------------------------------------
    # Console suspension / live line / history
    # ------------------------------------------------------------------
    @classmethod
    def suspend_console(cls) -> None:
        """Hold all terminal log output (file logging is unaffected). Nestable."""
        for handler in cls._console_handlers:
            handler.suspend()

    @classmethod
    def resume_console(cls) -> None:
        """Release one suspension level; replays held records when it reaches 0."""
        for handler in cls._console_handlers:
            handler.resume()

    @classmethod
    @contextlib.contextmanager
    def console_suspended(cls):
        cls.suspend_console()
        try:
            yield
        finally:
            cls.end_live_line()
            cls.resume_console()

    @classmethod
    def live_line(cls, text: str) -> None:
        """Rewrite a single ANSI status line on the real stdout (bypasses logging).

        Truncated to the terminal width so it never wraps. No-op without a
        console stream. Call suspend_console() first so log output doesn't
        interleave with the line.
        """
        stream = cls._orig_stdout
        if stream is None or not cls._console_handlers:
            return
        width = shutil.get_terminal_size(fallback=(80, 24)).columns - 1
        if width > 0 and len(text) > width:
            text = text[:width]
        with cls._live_lock:
            try:
                stream.write(f"\r\x1b[2K{text}")
                stream.flush()
                cls._live_active = True
            except Exception:
                pass

    @classmethod
    def end_live_line(cls) -> None:
        """Terminate the live line with a newline so replayed logs start clean."""
        stream = cls._orig_stdout
        with cls._live_lock:
            if not cls._live_active or stream is None:
                return
            try:
                stream.write("\n")
                stream.flush()
            except Exception:
                pass
            cls._live_active = False

    @classmethod
    def console_history(cls) -> list[str]:
        """Copy of the recent log lines printed to the terminal."""
        return list(cls._history)

    @classmethod
    def clear_console(cls) -> None:
        """Clear the terminal screen and the remembered log lines."""
        cls._history.clear()
        stream = cls._orig_stdout
        if stream is None:
            return
        try:
            stream.flush()
        except Exception:
            pass
        os.system("cls" if os.name == "nt" else "clear")

    @classmethod
    def console_write(
        cls, text: str = "", end: str = "\n", remember: bool = True
    ) -> None:
        """Print raw text on the real stdout (bypasses logging and the file log).

        Complete lines (end == "\\n") are remembered for console_history()
        unless remember=False. Use remember=False for transient lines such as
        an input prompt.
        """
        stream = cls._orig_stdout
        if stream is None:
            return
        with cls._live_lock:
            try:
                stream.write(text + end)
                stream.flush()
                if remember and end == "\n":
                    cls._history.append(text)
            except Exception:
                pass

    @classmethod
    def flush_and_close(cls) -> None:
        """Restores original streams and flushes buffered logs if active."""
        cls.end_live_line()
        for handler in cls._console_handlers:
            handler.resume(force=True)

        sys.stdout = cls._orig_stdout
        sys.stderr = cls._orig_stderr

        if cls._memory_handler:
            cls._memory_handler.flush()
            cls._memory_handler.close()
            cls._memory_handler = None

        if cls._target_file_handler:
            cls._target_file_handler.close()
            cls._target_file_handler = None