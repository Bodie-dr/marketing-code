import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

import numpy as np
from dotenv import load_dotenv

from database.config import DATABASE_PATH


logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).resolve().parent / ".env")


def _adapt_value(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return value.astype(np.float32).tobytes()
    return value


class SQLiteCursor:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "SQLiteCursor":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def execute(
        self,
        sql: str,
        parameters: Iterable[Any] = (),
    ) -> "SQLiteCursor":
        sql = sql.replace("%s", "?")
        adapted_parameters = tuple(
            _adapt_value(parameter)
            for parameter in parameters
        )

        if not adapted_parameters and sql.count(";") > 1:
            self._cursor.executescript(sql)
            return self

        self._cursor.execute(sql, adapted_parameters)
        return self

    def executemany(
        self,
        sql: str,
        parameters: Iterable[Iterable[Any]],
    ) -> "SQLiteCursor":
        sql = sql.replace("%s", "?")
        adapted_parameters = [
            tuple(_adapt_value(parameter) for parameter in row)
            for row in parameters
        ]
        self._cursor.executemany(sql, adapted_parameters)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self) -> None:
        self._cursor.close()


class SQLiteConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def cursor(self) -> SQLiteCursor:
        return SQLiteCursor(self._connection.cursor())

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def create_connection(database_path: str | Path | None = None) -> SQLiteConnection:
    path = Path(database_path or DATABASE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Verbinding maken met SQLite: %s", path)
    raw_connection = sqlite3.connect(path)
    raw_connection.execute("PRAGMA foreign_keys = ON")
    raw_connection.create_function(
        "NOW",
        0,
        lambda: datetime.now(timezone.utc).isoformat(),
    )
    logger.info("SQLite-verbinding is gereed.")
    return SQLiteConnection(raw_connection)


def create_schema(connection: SQLiteConnection) -> None:
    schema_sql = """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        created_at TEXT NOT NULL DEFAULT (NOW()),
        updated_at TEXT NOT NULL DEFAULT (NOW())
    );

    CREATE TABLE IF NOT EXISTS documents (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        file_type TEXT NOT NULL DEFAULT 'docx',
        current_version INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (NOW()),
        updated_at TEXT NOT NULL DEFAULT (NOW()),
        CONSTRAINT unique_document_path UNIQUE(project_id, relative_path)
    );

    CREATE TABLE IF NOT EXISTS document_versions (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        version_number INTEGER NOT NULL,
        full_text TEXT NOT NULL,
        checksum_sha256 TEXT NOT NULL,
        file_size_bytes INTEGER NOT NULL,
        source_modified_at TEXT,
        imported_at TEXT NOT NULL DEFAULT (NOW()),
        CONSTRAINT unique_document_version UNIQUE(document_id, version_number),
        CONSTRAINT unique_document_checksum UNIQUE(document_id, checksum_sha256)
    );

    CREATE TABLE IF NOT EXISTS document_chunks (
        id TEXT PRIMARY KEY,
        version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
        chunk_number INTEGER NOT NULL,
        content TEXT NOT NULL,
        character_start INTEGER NOT NULL,
        character_end INTEGER NOT NULL,
        character_count INTEGER NOT NULL,
        created_at TEXT NOT NULL DEFAULT (NOW()),
        CONSTRAINT unique_version_chunk UNIQUE(version_id, chunk_number)
    );

    CREATE TABLE IF NOT EXISTS embeddings (
        id TEXT PRIMARY KEY,
        chunk_id TEXT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
        model_name TEXT NOT NULL,
        dimensions INTEGER NOT NULL,
        embedding BLOB NOT NULL,
        created_at TEXT NOT NULL DEFAULT (NOW()),
        CONSTRAINT unique_chunk_embedding UNIQUE(chunk_id, model_name)
    );

    CREATE TABLE IF NOT EXISTS project_onedrive_folders (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        drive_id TEXT NOT NULL,
        folder_id TEXT NOT NULL,
        folder_name TEXT NOT NULL,
        folder_path TEXT,
        created_at TEXT NOT NULL DEFAULT (NOW()),
        updated_at TEXT NOT NULL DEFAULT (NOW()),
        CONSTRAINT unique_project_onedrive_folder UNIQUE(project_id),
        CONSTRAINT unique_onedrive_folder UNIQUE(drive_id, folder_id)
    );

    CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);
    CREATE INDEX IF NOT EXISTS idx_versions_document ON document_versions(document_id);
    CREATE INDEX IF NOT EXISTS idx_versions_checksum ON document_versions(checksum_sha256);
    CREATE INDEX IF NOT EXISTS idx_embeddings_chunk ON embeddings(chunk_id);
    CREATE INDEX IF NOT EXISTS idx_photo_references_created ON photo_references(created_at);
    CREATE INDEX IF NOT EXISTS idx_training_photo_pairs_split
        ON training_photo_pairs(split);
    """

    try:
        with connection.cursor() as cursor:
            cursor.execute(schema_sql)
        connection.commit()
        logger.info("Databaseschema is gereed.")
    except Exception:
        connection.rollback()
        raise
