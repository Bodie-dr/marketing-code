"""Regressietests zonder modeldownloads of betaalde API-aanvragen."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

import app
import text_generation as generation


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        generation._query_embedding.cache_clear()
        self.addCleanup(generation._query_embedding.cache_clear)

    def connection(self, result_sets):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = result_sets
        return connection

    def test_empty_database_skips_embedding_model(self):
        connection = self.connection([[], []])
        with patch.object(generation, "create_connection", return_value=connection), patch.object(
            generation, "_query_embedding"
        ) as embed:
            self.assertEqual(generation.zoek_relevante_data("opdracht"), "")
            embed.assert_not_called()
            connection.close.assert_called_once()

    def test_repeated_query_reuses_embedding_but_refreshes_documents(self):
        vector = np.array([1, 0], dtype=np.float32)
        connection = self.connection([
            [("Oude inhoud", vector.tobytes())],
            [("Nieuwe inhoud", vector.tobytes())],
        ])
        service = MagicMock()
        service.return_value.create_embeddings.return_value = [vector]
        with patch.object(generation, "create_connection", return_value=connection), patch.dict(
            sys.modules, {"embedding_service": SimpleNamespace(EmbeddingService=service)}
        ):
            self.assertEqual(generation.zoek_relevante_data("opdracht"), "Oude inhoud")
            self.assertEqual(generation.zoek_relevante_data("opdracht"), "Nieuwe inhoud")
            service.return_value.create_embeddings.assert_called_once()

    def test_fallback_and_ranking(self):
        rows = [
            ("Minder relevant", np.array([0, 1], dtype=np.float32).tobytes()),
            ("Relevant", np.array([1, 0], dtype=np.float32).tobytes()),
        ]
        for channel, results in [("Website", [[], [], rows]), ("Overig", [rows])]:
            with self.subTest(channel=channel), patch.object(
                generation, "create_connection", return_value=self.connection(results)
            ), patch.object(generation, "_query_embedding", return_value=[1, 0]):
                self.assertEqual(generation.zoek_relevante_data("opdracht", kanaal=channel, aantal=1), "Relevant")

    def test_text_is_visible_before_word_export(self):
        with patch.object(app, "generate_text", return_value="Resultaat"), patch.object(
            app, "save_generated_word", return_value="resultaat.docx"
        ) as export:
            updates = app.validate_and_generate(None, "", "", "Nieuwe tekst genereren", "Bouw", "", "", "", "LinkedIn")
            self.assertEqual(next(updates), ("Resultaat", None))
            export.assert_not_called()
            self.assertEqual(next(updates), ("Resultaat", "resultaat.docx"))
            self.assertEqual(list(updates), [])

    def test_export_failure_preserves_generated_text(self):
        with patch.object(app, "generate_text", return_value="Resultaat"), patch.object(
            app, "save_generated_word", side_effect=OSError("Test")
        ), patch.object(app.gr, "Warning") as warning, patch.object(app.logger, "exception"):
            updates = app.validate_and_generate(None, "", "", "Nieuwe tekst genereren", "Bouw", "", "", "", "LinkedIn")
            self.assertEqual(list(updates), [("Resultaat", None)])
            warning.assert_called_once()

    def test_schema_created_once(self):
        with patch.object(app, "_database_ready", False), patch.object(app, "create_connection"), patch.object(
            app, "create_schema"
        ) as schema:
            app.initialize_database()
            app.initialize_database()
            schema.assert_called_once()


if __name__ == "__main__":
    unittest.main()
