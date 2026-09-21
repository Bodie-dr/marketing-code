import os
import logging
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector


logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).resolve().parent / ".env")


def get_connection_string() -> str:
    database_url = (
         os.getenv("DATABASE_URL")
    )

    if database_url:
        return database_url

    required_variables = [
        "DB_HOST",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
    ]

    missing_variables = [
        variable
        for variable in required_variables
        if not os.getenv(variable)
    ]

    if missing_variables:
        raise RuntimeError(
            "Stel DATABASE_URL of de losse databasevariabelen in .env in. "
            "Ontbrekend: "
            + ", ".join(missing_variables)
        )

    return (
        f"host={os.environ['DB_HOST']} "
        f"port={os.getenv('DB_PORT', '5432')} "
        f"dbname={os.environ['DB_NAME']} "
        f"user={os.environ['DB_USER']} "
        f"password={os.environ['DB_PASSWORD']}"
    )


def create_connection() -> psycopg.Connection:
    logger.info(
        "Verbinding maken met PostgreSQL..."
    )

    connection = psycopg.connect(
        get_connection_string(),
        autocommit=False,
        connect_timeout=10,
    )

    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE EXTENSION IF NOT EXISTS vector"
        )

    connection.commit()

    register_vector(connection)

    logger.info(
        "PostgreSQL-verbinding is gereed."
    )

    return connection



def create_schema(
    connection: psycopg.Connection
) -> None:
    schema_sql = """
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS projects (
        id UUID PRIMARY KEY,
        name VARCHAR(255) NOT NULL UNIQUE,
        description TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS documents (
        id UUID PRIMARY KEY,

        project_id UUID NOT NULL
            REFERENCES projects(id)
            ON DELETE CASCADE,

        filename VARCHAR(500) NOT NULL,
        relative_path TEXT NOT NULL,
        file_type VARCHAR(30) NOT NULL DEFAULT 'docx',

        current_version INTEGER NOT NULL DEFAULT 0,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,

        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT unique_document_path
            UNIQUE(project_id, relative_path)
    );

    CREATE TABLE IF NOT EXISTS document_versions (
        id UUID PRIMARY KEY,

        document_id UUID NOT NULL
            REFERENCES documents(id)
            ON DELETE CASCADE,

        version_number INTEGER NOT NULL,
        full_text TEXT NOT NULL,
        checksum_sha256 CHAR(64) NOT NULL,
        file_size_bytes BIGINT NOT NULL,
        source_modified_at TIMESTAMPTZ,
        imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT unique_document_version
            UNIQUE(document_id, version_number),

        CONSTRAINT unique_document_checksum
            UNIQUE(document_id, checksum_sha256)
    );

    CREATE TABLE IF NOT EXISTS document_chunks (
        id UUID PRIMARY KEY,

        version_id UUID NOT NULL
            REFERENCES document_versions(id)
            ON DELETE CASCADE,

        chunk_number INTEGER NOT NULL,
        content TEXT NOT NULL,

        character_start INTEGER NOT NULL,
        character_end INTEGER NOT NULL,
        character_count INTEGER NOT NULL,

        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT unique_version_chunk
            UNIQUE(version_id, chunk_number)
    );

    CREATE TABLE IF NOT EXISTS embeddings (
        id UUID PRIMARY KEY,

        chunk_id UUID NOT NULL
            REFERENCES document_chunks(id)
            ON DELETE CASCADE,

        model_name VARCHAR(255) NOT NULL,
        dimensions INTEGER NOT NULL,
        embedding VECTOR(384) NOT NULL,

        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT unique_chunk_embedding
            UNIQUE(chunk_id, model_name)
    );

    CREATE TABLE IF NOT EXISTS photo_references (
        id UUID PRIMARY KEY,
        filename VARCHAR(500) NOT NULL,
        content_type VARCHAR(100) NOT NULL,
        checksum_sha256 CHAR(64) NOT NULL UNIQUE,
        image_data BYTEA NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS training_photo_pairs (
        id UUID PRIMARY KEY,
        split VARCHAR(20) NOT NULL CHECK (split IN ('train', 'val')),
        input_filename VARCHAR(500) NOT NULL,
        target_filename VARCHAR(500) NOT NULL,
        input_image BYTEA NOT NULL,
        target_image BYTEA NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT unique_training_photo_pair
            UNIQUE(split, input_filename, target_filename)
    );

    CREATE INDEX IF NOT EXISTS idx_documents_project
        ON documents(project_id);

    CREATE INDEX IF NOT EXISTS idx_versions_document
        ON document_versions(document_id);


    CREATE INDEX IF NOT EXISTS idx_embeddings_chunk
        ON embeddings(chunk_id);

    CREATE INDEX IF NOT EXISTS idx_photo_references_created
        ON photo_references(created_at);

    CREATE INDEX IF NOT EXISTS idx_training_photo_pairs_split
        ON training_photo_pairs(split);

    CREATE TABLE IF NOT EXISTS project_onedrive_folders (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL
        REFERENCES projects(id)
        ON DELETE CASCADE,

    drive_id TEXT NOT NULL,
    folder_id TEXT NOT NULL,
    folder_name TEXT NOT NULL,
    folder_path TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT unique_project_onedrive_folder
        UNIQUE(project_id),

    CONSTRAINT unique_onedrive_folder
        UNIQUE(drive_id, folder_id)
);
    """

    try:
        with connection.cursor() as cursor:
            cursor.execute(schema_sql)

            cursor.execute(
                """
                ALTER TABLE document_versions
                ADD COLUMN IF NOT EXISTS checksum_sha256 CHAR(64)
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_versions_checksum
                ON document_versions(checksum_sha256)
                """
            )

        connection.commit()

        logger.info(
            "Databaseschema is gereed."
        )

    except Exception:
        connection.rollback()
        raise