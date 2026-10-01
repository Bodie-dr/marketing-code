from pathlib import Path
import os

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent

PROJECT_DIR = BASE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"

load_dotenv(PROJECT_DIR / ".env")


# Documenten

DEFAULT_DOCUMENTS_FOLDER = DATA_DIR / "documents"

DOCUMENTS_FOLDER = Path(
    os.getenv(
        "DOCUMENTS_FOLDER",
        str(DEFAULT_DOCUMENTS_FOLDER)
    )
)

if not DOCUMENTS_FOLDER.is_absolute():
    DOCUMENTS_FOLDER = PROJECT_DIR / DOCUMENTS_FOLDER


PROJECT_NAME = os.getenv(
    "PROJECT_NAME",
    "TVB Marketing"
)

DATABASE_PATH = Path(
    os.getenv(
        "DATABASE_PATH",
        str(DATA_DIR / "marketing.sqlite3")
    )
)

if not DATABASE_PATH.is_absolute():
    DATABASE_PATH = PROJECT_DIR / DATABASE_PATH


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

