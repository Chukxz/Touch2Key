# CONNECTION.PY

"""
Thread-safe-by-construction sqlite wrapper. sqlite3.Connection objects
are not safe to share across threads, so this keeps one connection per
thread (thread-local storage) rather than one shared connection guarded
by a lock -- avoids serializing every read behind a single mutex, which
matters here since the touch-reader thread, aggregation thread, and GUI
thread all touch the store independently.

WAL mode lets readers and a writer proceed concurrently without
blocking each other for the common case (one thread reading
app_settings while another commits a small update); it does not remove
the need for each thread to have its own connection object.
"""

from __future__ import annotations
import sqlite3
import threading
from pathlib import Path

from .schema import SCHEMA_SQL


class Database:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

        # Run schema creation once, eagerly, on whichever thread
        # constructs the Database -- normally app startup on the main
        # thread -- using a throwaway connection rather than the
        # thread-local one, so __init__ doesn't leave a stray
        # per-thread connection open on a thread that may not touch
        # the database again.
        setup_conn = self._new_connection()
        try:
            setup_conn.executescript(SCHEMA_SQL)
            setup_conn.commit()
        finally:
            setup_conn.close()

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @property
    def connection(self) -> sqlite3.Connection:
        """Returns this thread's connection, creating it on first use."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._new_connection()
            self._local.conn = conn
        return conn

    def transaction(self) -> "_Transaction":
        """Wraps a block of statements in one commit/rollback:

            with db.transaction() as conn:
                conn.execute(...)
                conn.execute(...)

        sqlite3 already starts an implicit transaction on the first DML
        statement in autocommit-off (default) mode, so this doesn't
        change behavior -- it makes the intended atomic boundary
        explicit and readable at call sites, and ensures rollback on
        exception instead of leaving a half-applied change uncommitted
        indefinitely on that thread's connection.
        """
        return _Transaction(self.connection)

    def close(self) -> None:
        """Closes this thread's connection. Call from the same thread
        that used it (e.g. on GUI shutdown, or a worker thread's exit)."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


class _Transaction:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
