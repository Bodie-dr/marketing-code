import hashlib
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import psycopg

from chunking import TextChunk
from config import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL_NAME,
)
from document_reader import get_modified_datetime


def get_project_names(
    connection: psycopg.Connection,
) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT name
            FROM projects
            ORDER BY name
            """
        )
        return [row[0] for row in cursor.fetchall()]


def get_or_create_project(
    connection: psycopg.Connection,
    project_name: str,
) -> UUID:

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO projects (
                id,
                name,
                description
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (name)
            DO UPDATE SET
                updated_at = NOW()
            RETURNING id
            """,
            (
                uuid4(),
                project_name,
                "Word-documenten voor de AI-kennisbank",
            ),
        )

        result = cursor.fetchone()

    if result is None:
        raise RuntimeError(
            "Project kon niet worden aangemaakt."
        )

    return result[0]


def link_project_to_onedrive_folder(
    connection: psycopg.Connection,
    project_id: UUID,
    folder: Path,
) -> None:
    folder_path = str(folder.resolve())
    folder_id = hashlib.sha256(
        folder_path.casefold().encode("utf-8")
    ).hexdigest()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO project_onedrive_folders (
                id,
                project_id,
                drive_id,
                folder_id,
                folder_name,
                folder_path
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id)
            DO UPDATE SET
                drive_id = EXCLUDED.drive_id,
                folder_id = EXCLUDED.folder_id,
                folder_name = EXCLUDED.folder_name,
                folder_path = EXCLUDED.folder_path,
                updated_at = NOW()
            """,
            (
                uuid4(),
                project_id,
                "local-onedrive",
                folder_id,
                folder.name,
                folder_path,
            ),
        )


def get_document(
    connection: psycopg.Connection,
    project_id: UUID,
    relative_path: str,
) -> tuple[UUID, int] | None:

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                id,
                current_version
            FROM documents
            WHERE project_id = %s
              AND relative_path = %s
            """,
            (
                project_id,
                relative_path
            ),
        )

        result = cursor.fetchone()

    if result is None:
        return None

    return result[0], result[1]


def checksum_exists(
    connection: psycopg.Connection,
    document_id: UUID,
    checksum: str,
) -> bool:

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM document_versions
                WHERE document_id = %s
                  AND checksum_sha256 = %s
            )
            """,
            (
                document_id,
                checksum
            ),
        )

        result = cursor.fetchone()

    return bool(
        result and result[0]
    )


def create_document(
    connection: psycopg.Connection,
    project_id: UUID,
    file_path: Path,
    relative_path: str,
) -> UUID:

    document_id = uuid4()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO documents (
                id,
                project_id,
                filename,
                relative_path,
                file_type,
                current_version,
                is_active
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                0,
                TRUE
            )
            """,
            (
                document_id,
                project_id,
                file_path.name,
                relative_path,
                file_path.suffix
                    .lower()
                    .lstrip("."),
            ),
        )

    return document_id


def create_document_version(
    connection: psycopg.Connection,
    document_id: UUID,
    version_number: int,
    full_text: str,
    checksum: str,
    file_path: Path,
) -> UUID:

    version_id = uuid4()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO document_versions (
                id,
                document_id,
                version_number,
                full_text,
                checksum_sha256,
                file_size_bytes,
                source_modified_at
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                version_id,
                document_id,
                version_number,
                full_text,
                checksum,
                file_path.stat().st_size,
                get_modified_datetime(file_path),
            ),
        )

    return version_id


def insert_chunks_and_embeddings(
    connection: psycopg.Connection,
    version_id: UUID,
    chunks: list[TextChunk],
    embeddings: np.ndarray,
) -> None:

    if len(chunks) != len(embeddings):
        raise ValueError(
            "Aantal chunks en embeddings "
            "komt niet overeen."
        )

    with connection.cursor() as cursor:
        for chunk, embedding in zip(
            chunks,
            embeddings
        ):
            chunk_id = uuid4()

            cursor.execute(
                """
                INSERT INTO document_chunks (
                    id,
                    version_id,
                    chunk_number,
                    content,
                    character_start,
                    character_end,
                    character_count
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    chunk_id,
                    version_id,
                    chunk.chunk_number,
                    chunk.content,
                    chunk.character_start,
                    chunk.character_end,
                    len(chunk.content),
                ),
            )

            cursor.execute(
                """
                INSERT INTO embeddings (
                    id,
                    chunk_id,
                    model_name,
                    dimensions,
                    embedding
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    uuid4(),
                    chunk_id,
                    EMBEDDING_MODEL_NAME,
                    EMBEDDING_DIMENSION,
                    np.asarray(
                        embedding,
                        dtype=np.float32
                    ),
                ),
            )


def set_current_version(
    connection: psycopg.Connection,
    document_id: UUID,
    version_number: int,
    filename: str,
) -> None:

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE documents
            SET
                current_version = %s,
                filename = %s,
                is_active = TRUE,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                version_number,
                filename,
                document_id,
            ),
        )