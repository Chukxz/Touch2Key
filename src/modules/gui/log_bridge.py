"""
Routes stdlib logging records into the GUI's log console dock without
crossing thread boundaries unsafely. Call install_gui_logging() once,
early in gui/app.py's startup, before any engine threads start logging.
"""
from __future__ import annotations
import logging

from PySide6.QtCore import QObject, Signal


class _LogEmitter(QObject):
    message = Signal(str, int)  # formatted line, levelno


class QtLogHandler(logging.Handler):
    """A logging.Handler whose emit() just forwards to a Qt Signal.
    Signal.emit() queues safely across threads (see signal_bridge.py's
    docstring for the mechanism), so no manual locking or queue is
    needed here. If log volume ever becomes extreme enough to matter,
    swap this for logging.handlers.QueueHandler + QueueListener feeding
    the same _LogEmitter from one dedicated consumer thread instead --
    this class's interface (the .emitter.message signal) wouldn't need
    to change for callers."""

    def __init__(self, level: int = logging.NOTSET):
        super().__init__(level)
        self.emitter = _LogEmitter()
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S"
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            line = record.getMessage()
        self.emitter.message.emit(line, record.levelno)


def install_gui_logging(
    logger_name: str = "modules", level: int = logging.INFO
) -> QtLogHandler:
    """Attaches a QtLogHandler to the given logger (default: the
    package root, so every module's logger.* calls are captured) and
    returns the handler so the caller can connect its signal."""
    handler = QtLogHandler(level)
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.addHandler(handler)
    return handler
