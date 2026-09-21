from pathlib import Path
import os

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


# Documenten

DOCUMENTS_FOLDER = Path(
    os.getenv(
        "DOCUMENTS_FOLDER",
        str(BASE_DIR / "documents")
    )
)

if not DOCUMENTS_FOLDER.is_absolute():
    DOCUMENTS_FOLDER = BASE_DIR / DOCUMENTS_FOLDER


REFERENCE_PHOTOS_FOLDER = Path(
    os.getenv(
        "REFERENCE_PHOTOS_FOLDER",
        str(DOCUMENTS_FOLDER / "TVB" / "licht-referenties")
    )
)

if not REFERENCE_PHOTOS_FOLDER.is_absolute():
    REFERENCE_PHOTOS_FOLDER = BASE_DIR / REFERENCE_PHOTOS_FOLDER


PROJECT_NAME = os.getenv(
    "PROJECT_NAME",
    "TVB Marketing"
)


# Embeddingmodel

EMBEDDING_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "sentence-transformers/"
    "paraphrase-multilingual-MiniLM-L12-v2"
)

EMBEDDING_DIMENSION = int(
    os.getenv(
        "EMBEDDING_DIMENSION",
        "384"
    )
)


# Chunkinstellingen

CHUNK_SIZE = int(
    os.getenv(
        "CHUNK_SIZE",
        "1200"
    )
)

CHUNK_OVERLAP = int(
    os.getenv(
        "CHUNK_OVERLAP",
        "200"
    )
)


# Ondersteunde bestanden

SUPPORTED_EXTENSIONS = {
    ".docx",
    ".jpg",
    ".jpeg",
    ".png",
}