from __future__ import annotations
import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from database.chunking import split_text_into_chunks
from database.config import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    DOCUMENTS_FOLDER,
    PROJECT_NAME,
    SUPPORTED_EXTENSIONS,
)
from database.database import (
    create_connection,
    create_schema,
)
from foto_generation.foto_model import (
    ensure_training_photo_pairs_table,
    import_local_training_pairs,
)
from database.document_reader import (
    calculate_sha256,
    read_image_metadata,
    read_docx,
)
from database.document_repository import (
    checksum_exists,
    create_document,
    create_document_version,
    get_document,
    get_or_create_project,
    insert_chunks_and_embeddings,
    link_project_to_onedrive_folder,
    set_current_version,
)
from database.embedding_service import EmbeddingService


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    ),
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)


@dataclass
class ImportStatistics:
    found: int = 0
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    chunks: int = 0


def add_statistics(
    total: ImportStatistics,
    current: ImportStatistics,
) -> None:
    total.found += current.found
    total.imported += current.imported
    total.updated += current.updated
    total.skipped += current.skipped
    total.failed += current.failed
    total.chunks += current.chunks


def find_documents(
    folder: Path,
) -> list[Path]:
    files: list[Path] = []

    for file_path in folder.rglob("*"):
        if not file_path.is_file():
            continue

        # Tijdelijke Word-bestanden overslaan.

        if file_path.name.startswith("~$"):
            continue

        if (
            file_path.suffix.lower()
            in SUPPORTED_EXTENSIONS
        ):
            files.append(file_path)

    return sorted(files)


def import_document(
    connection,
    embedding_service: EmbeddingService,
    project_id,
    file_path: Path,
    folder: Path,
    preview: bool,
) -> tuple[str, int]:

    file_path = file_path.resolve()
    folder = folder.resolve()

    try:
        relative_path = (
            file_path
            .relative_to(folder)
            .as_posix()
        )

    except ValueError:
        relative_path = file_path.name

    checksum = calculate_sha256(
        file_path
    )

    existing_document = get_document(
        connection,
        project_id,
        relative_path,
    )

    if existing_document:
        document_id, current_version = (
            existing_document
        )

        if checksum_exists(
            connection,
            document_id,
            checksum,
        ):
            logger.info(
                "Overgeslagen, ongewijzigd: %s",
                relative_path,
            )

            return "skipped", 0

        version_number = (
            current_version + 1
        )

        status = "updated"

    else:
        document_id = None
        version_number = 1
        status = "imported"

    if file_path.suffix.lower() == ".docx":
        full_text = read_docx(file_path)
    else:
        full_text = read_image_metadata(file_path)

    if not full_text:
        raise ValueError(
            "Het document bevat geen "
            "uitleesbare tekst."
        )

    chunks = split_text_into_chunks(
        text=full_text,
        chunk_size=CHUNK_SIZE,
        overlap=CHUNK_OVERLAP,
    )

    if not chunks:
        raise ValueError(
            "Er konden geen chunks "
            "worden gemaakt."
        )

    if preview:
        logger.info(
            "[PREVIEW] %s | versie %s | "
            "%s tekens | %s chunks",
            relative_path,
            version_number,
            len(full_text),
            len(chunks),
        )

        return status, len(chunks)

    chunk_texts = [
        chunk.content
        for chunk in chunks
    ]

    embeddings = (
        embedding_service
        .create_embeddings(chunk_texts)
    )

    try:
        if document_id is None:
            document_id = create_document(
                connection=connection,
                project_id=project_id,
                file_path=file_path,
                relative_path=relative_path,
            )

        version_id = create_document_version(
            connection=connection,
            document_id=document_id,
            version_number=version_number,
            full_text=full_text,
            checksum=checksum,
            file_path=file_path,
        )

        insert_chunks_and_embeddings(
            connection=connection,
            version_id=version_id,
            chunks=chunks,
            embeddings=embeddings,
        )

        set_current_version(
            connection=connection,
            document_id=document_id,
            version_number=version_number,
            filename=file_path.name,
        )

        connection.commit()

        logger.info(
            "Opgeslagen: %s | versie %s | "
            "%s chunks",
            relative_path,
            version_number,
            len(chunks),
        )

        return status, len(chunks)

    except Exception:
        connection.rollback()
        raise


def ingest_all_documents(
    folder: Path,
    project_name: str,
    preview: bool,
    onedrive_folder: Path | None = None,
) -> ImportStatistics:

    statistics = ImportStatistics()

    if not folder.exists():
        folder.mkdir(
            parents=True,
            exist_ok=True
        )

        raise FileNotFoundError(
            f"De map is aangemaakt: {folder}. "
            "Plaats hier Word-documenten of afbeeldingen in."
        )

    files = find_documents(folder)

    statistics.found = len(files)

    if not files:
        logger.warning(
            "Geen ondersteunde documenten of afbeeldingen gevonden in %s",
            folder,
        )

        return statistics

    connection = None

    try:
        connection = create_connection()

        create_schema(connection)

        project_id = get_or_create_project(
            connection,
            project_name,
        )

        if onedrive_folder is not None:
            link_project_to_onedrive_folder(
                connection,
                project_id,
                onedrive_folder,
            )

            logger.info(
                "OneDrive-map gekoppeld: %s -> project_id=%s",
                onedrive_folder,
                project_id,
            )

        connection.commit()

        embedding_service = EmbeddingService()

        for index, file_path in enumerate(
            files,
            start=1
        ):
            logger.info(
                "[%s/%s] Verwerken: %s",
                index,
                len(files),
                file_path.name,
            )

            try:
                status, chunk_count = (
                    import_document(
                        connection=connection,
                        embedding_service=(
                            embedding_service
                        ),
                        project_id=project_id,
                        file_path=file_path,
                        folder=folder,
                        preview=preview,
                    )
                )

                if status == "imported":
                    statistics.imported += 1

                elif status == "updated":
                    statistics.updated += 1

                elif status == "skipped":
                    statistics.skipped += 1

                statistics.chunks += (
                    chunk_count
                )

            except Exception as error:
                connection.rollback()

                statistics.failed += 1

                logger.exception(
                    "Import mislukt voor %s: %s",
                    file_path.name,
                    error,
                )

    finally:
        if connection is not None:
            connection.close()

    return statistics


def ingest_document_root(
    folder: Path,
    project_name: str,
    preview: bool,
) -> ImportStatistics:
    """Import root files and map each direct subfolder to a project."""
    statistics = ImportStatistics()

    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        raise FileNotFoundError(
            f"De map is aangemaakt: {folder}. "
            "Plaats hier Word-documenten, afbeeldingen of bedrijfsfolders in."
        )

    root_files = [
        path
        for path in folder.iterdir()
        if (
            path.is_file()
            and not path.name.startswith("~$")
            and path.suffix.lower() in SUPPORTED_EXTENSIONS
        )
    ]
    subfolders = sorted(
        path for path in folder.iterdir() if path.is_dir()
    )

    if root_files:
        add_statistics(
            statistics,
            ingest_all_documents(
                folder=folder,
                project_name=project_name,
                preview=preview,
            ),
        )

    for subfolder in subfolders:
        if not find_documents(subfolder):
            logger.info(
                "Geen ondersteunde documenten of afbeeldingen in submap: %s",
                subfolder.name,
            )
            continue

        logger.info(
            "Bedrijfsmap gevonden: %s -> project '%s'",
            subfolder,
            subfolder.name,
        )

        add_statistics(
            statistics,
            ingest_all_documents(
                folder=subfolder,
                project_name=subfolder.name,
                preview=preview,
                onedrive_folder=subfolder,
            ),
        )

    if not root_files and not subfolders:
        logger.warning(
            "Geen ondersteunde documenten, afbeeldingen of bedrijfsfolders gevonden in %s",
            folder,
        )

    return statistics


def import_training_photo_pairs(
    train_input_dir: Path,
    train_target_dir: Path,
    val_input_dir: Path,
    val_target_dir: Path,
) -> tuple[int, int]:
    connection = create_connection()
    try:
        create_schema(connection)
        ensure_training_photo_pairs_table(connection)

        train_imported = import_local_training_pairs(
            connection,
            "train",
            train_input_dir,
            train_target_dir,
        )
        val_imported = import_local_training_pairs(
            connection,
            "val",
            val_input_dir,
            val_target_dir,
        )

        connection.commit()
        logger.info(
            "Trainingfoto's geïmporteerd: train=%s, val=%s",
            train_imported,
            val_imported,
        )
        return train_imported, val_imported
    finally:
        connection.close()


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Importeer Word-documenten en afbeeldingen "
            "in SQLite."
        )
    )

    parser.add_argument(
        "--folder",
        type=str,
        default=str(DOCUMENTS_FOLDER),
        help="Map met Word-documenten en afbeeldingen.",
    )

    parser.add_argument(
        "--project",
        type=str,
        default=PROJECT_NAME,
        help="Projectnaam in SQLite.",
    )

    parser.add_argument(
        "--train-input-dir",
        type=str,
        default="data/train/input",
        help="Map met training-inputfoto's.",
    )

    parser.add_argument(
        "--train-target-dir",
        type=str,
        default="data/train/target",
        help="Map met training-targetfoto's.",
    )

    parser.add_argument(
        "--val-input-dir",
        type=str,
        default="data/val/input",
        help="Map met validatie-inputfoto's.",
    )

    parser.add_argument(
        "--val-target-dir",
        type=str,
        default="data/val/target",
        help="Map met validatie-targetfoto's.",
    )

    parser.add_argument(
        "--preview",
        action="store_true",
        help=(
            "Bestanden analyseren zonder "
            "de database te wijzigen."
        ),
    )

    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()

    folder = Path(
        arguments.folder
    )

    logger.info(
        "Documentenmap: %s",
        folder
    )

    logger.info(
        "Project: %s",
        arguments.project
    )

    logger.info(
        "Previewmodus: %s",
        arguments.preview
    )

    try:
        if arguments.preview:
            logger.info(
                "Previewmodus is actief; trainingsfoto's worden niet geïmporteerd."
            )
        else:
            train_imported, val_imported = import_training_photo_pairs(
                train_input_dir=Path(arguments.train_input_dir),
                train_target_dir=Path(arguments.train_target_dir),
                val_input_dir=Path(arguments.val_input_dir),
                val_target_dir=Path(arguments.val_target_dir),
            )
            logger.info(
                "Trainingsfoto's uit mappen in DB gezet: train=%s, val=%s",
                train_imported,
                val_imported,
            )

        statistics = ingest_document_root(
            folder=folder,
            project_name=arguments.project,
            preview=arguments.preview,
        )

    except Exception as error:
        logger.exception(
            "Importproces afgebroken: %s",
            error,
        )

        return 1

    logger.info("=" * 50)
    logger.info("IMPORTSAMENVATTING")
    logger.info(
        "Gevonden documenten : %s",
        statistics.found
    )
    logger.info(
        "Nieuwe documenten    : %s",
        statistics.imported
    )
    logger.info(
        "Nieuwe versies       : %s",
        statistics.updated
    )
    logger.info(
        "Overgeslagen         : %s",
        statistics.skipped
    )
    logger.info(
        "Mislukt              : %s",
        statistics.failed
    )
    logger.info(
        "Verwerkte chunks     : %s",
        statistics.chunks
    )
    logger.info("=" * 50)

    return 1 if statistics.failed else 0


if __name__ == "__main__":
    sys.exit(main())