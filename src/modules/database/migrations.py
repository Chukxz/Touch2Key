import sqlite3
import logging
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger("modules.database.migrations")


class Migration(ABC):
    """Base class for all database migrations."""

    @property
    @abstractmethod
    def version(self) -> int:
        """The database version this migration targets (must be > 0)."""
        pass

    @property
    def description(self) -> str:
        """Optional description for the logs."""
        return self.__class__.__name__

    @abstractmethod
    def apply(self, conn: sqlite3.Connection) -> None:
        """Executes the SQL or Python logic required for this migration."""
        pass


# ==========================================
# DEFINE YOUR MIGRATIONS HERE
# ==========================================


class Migration_001_AddHudImagePath(Migration):
    @property
    def version(self) -> int:
        return 1

    @property
    def description(self) -> str:
        return "Add hud_image_path column to layouts table"

    def apply(self, conn: sqlite3.Connection) -> None:
        # We use executescript for raw SQL schema changes
        conn.executescript("""
            ALTER TABLE layouts ADD COLUMN hud_image_path TEXT;
        """)


class Migration_002_ExampleFutureDataMigration(Migration):
    """
    Example of why classes are better:
    If you ever need to read data, change it in Python, and write it back.
    """

    @property
    def version(self) -> int:
        return 2

    def apply(self, conn: sqlite3.Connection) -> None:
        # 1. You could execute normal SQL
        # conn.execute("ALTER TABLE app_settings ADD COLUMN new_setting INTEGER;")

        # 2. OR you could do complex Python logic if needed:
        # cursor = conn.execute("SELECT id, name FROM layouts")
        # for row in cursor.fetchall():
        #     new_name = row["name"].strip().lower()
        #     conn.execute("UPDATE layouts SET name = ? WHERE id = ?", (new_name, row["id"]))
        pass


# Register all your migration classes in order
MIGRATIONS: list[Migration] = [
    # Migration_001_AddHudImagePath(),   <-- Uncomment when you add it
    # Migration_002_ExampleFutureDataMigration(),  <-- Uncomment when you add it
]

# The latest version is dynamically determined by the highest version in the list
LATEST_VERSION = max((m.version for m in MIGRATIONS), default=0)

# ==========================================
# MIGRATION RUNNER
# ==========================================


def run_migrations(db_path: Path | str) -> None:
    """Applies pending migrations in sequential order."""
    db_path = Path(db_path)
    if not db_path.exists():
        return

    # Sort migrations safely by version number just in case they are out of order in the list
    sorted_migrations = sorted(MIGRATIONS, key=lambda m: m.version)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Useful if a migration needs to read rows as dicts

    try:
        current_version = conn.execute("PRAGMA user_version;").fetchone()[0]

        # Filter out migrations that have already been applied
        pending = [m for m in sorted_migrations if m.version > current_version]

        if not pending:
            logger.debug("Database is up to date (version %d).", current_version)
            return

        logger.info(
            "Migrating database from version %d to %d...",
            current_version,
            pending[-1].version,
        )

        for migration in pending:
            logger.info("Applying v%d: %s...", migration.version, migration.description)

            # Run the migration's internal logic
            migration.apply(conn)

            # Update SQLite's internal version tracker immediately
            conn.execute(f"PRAGMA user_version = {migration.version};")

        conn.commit()
        logger.info("Migrations completed successfully.")

    except Exception as e:
        logger.error("Migration failed! Rolling back changes: %s", e)
        conn.rollback()
        raise
    finally:
        conn.close()


def set_fresh_install_version(conn: sqlite3.Connection) -> None:
    """Called during ConnectionManager setup to mark a brand new DB as fully updated."""
    current_version = conn.execute("PRAGMA user_version;").fetchone()[0]
    if current_version == 0 and LATEST_VERSION > 0:
        conn.execute(f"PRAGMA user_version = {LATEST_VERSION};")
        conn.commit()
