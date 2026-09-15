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
    """Safe cross-thread logging handler directing log records to a Qt Signal."""

    def __init__(self, level: int = logging.NOTSET):
        super().__init__(level)
        self.emitter = _LogEmitter()
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S"
            )
        )
        self._in_emit = False

    def emit(self, record: logging.LogRecord) -> None:
        # Re-entrancy guard
        if self._in_emit:
            return
        self._in_emit = True
        try:
            try:
                line = self.format(record)
            except Exception:
                line = record.getMessage()
            self.emitter.message.emit(line, record.levelno)
        finally:
            self._in_emit = False


_installed_handler: QtLogHandler | None = None


def install_gui_logging(
    logger_name: str = "modules", level: int = logging.INFO
) -> QtLogHandler:
    """Attaches a single singleton QtLogHandler to prevent duplicate output."""
    global _installed_handler
    if _installed_handler is not None:
        return _installed_handler

    handler = QtLogHandler(level)
    target_logger = logging.getLogger(logger_name)
    target_logger.setLevel(level)
    target_logger.addHandler(handler)
    _installed_handler = handler
    return handler