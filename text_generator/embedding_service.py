import numpy as np

from config import (
    EMBEDDING_MODEL_NAME,
    EMBEDDING_DIMENSION,
)


class EmbeddingService:
    _model = None

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        if EmbeddingService._model is None:
            print(
                "Embeddingmodel laden:",
                EMBEDDING_MODEL_NAME,
            )
            EmbeddingService._model = SentenceTransformer(
                EMBEDDING_MODEL_NAME
            )

        self.model = EmbeddingService._model

        actual_dimension = (
            self.model
            .get_sentence_embedding_dimension()
        )

        if actual_dimension != EMBEDDING_DIMENSION:
            raise RuntimeError(
                "Verkeerde embeddingdimensie. "
                f"Model gebruikt {actual_dimension}, "
                f"maar de database verwacht "
                f"{EMBEDDING_DIMENSION}."
            )

    def create_embeddings(
        self,
        texts: list[str],
        batch_size: int = 32,
    ) -> np.ndarray:

        if not texts:
            return np.empty(
                (
                    0,
                    EMBEDDING_DIMENSION
                ),
                dtype=np.float32
            )

        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=(
                len(texts) > batch_size
            ),
            normalize_embeddings=True,
            convert_to_numpy=True,
        )

        if embeddings.ndim != 2:
            raise RuntimeError(
                "Het embeddingmodel heeft een "
                "ongeldig resultaat teruggegeven."
            )

        if embeddings.shape[1] != EMBEDDING_DIMENSION:
            raise RuntimeError(
                "Embeddingdimensie komt niet overeen "
                "met de database."
            )

        return embeddings.astype(
            np.float32
        )


