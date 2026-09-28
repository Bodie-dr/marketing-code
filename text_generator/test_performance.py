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

    @staticmethod
    def row(doc_id, pad, tekst, vector, bedrijf="Klik"):
        return (doc_id, bedrijf, pad, tekst, np.array(vector, dtype=np.float32).tobytes())

    def test_repeated_query_reuses_embedding_but_refreshes_documents(self):
        connection = self.connection([
            [self.row("a", "social_media_teksten/x.docx", "Oude inhoud", [1, 0]),
             self.row("b", "social_media_teksten/y.docx", "Andere", [0, 1])],
            [self.row("a", "social_media_teksten/x.docx", "Nieuwe inhoud", [1, 0]),
             self.row("b", "social_media_teksten/y.docx", "Andere", [0, 1])],
        ])
        service = MagicMock()
        service.return_value.create_embeddings.return_value = [np.array([1, 0], dtype=np.float32)]
        with patch.object(generation, "create_connection", return_value=connection), patch.dict(
            sys.modules, {"embedding_service": SimpleNamespace(EmbeddingService=service)}
        ):
            self.assertIn("Oude inhoud", generation.zoek_relevante_data("opdracht", "Klik", aantal=1))
            self.assertIn("Nieuwe inhoud", generation.zoek_relevante_data("opdracht", "Klik", aantal=1))
            service.return_value.create_embeddings.assert_called_once()

    def test_channel_folder_first_then_similarity(self):
        rows = [
            self.row("a", "social_media_teksten/verhaal.docx", "Social", [1, 0]),
            self.row("b", "website_vacatuur_teksten/minder.docx", "Minder relevant", [0, 1]),
            self.row("c", "website_vacatuur_teksten/beter.docx", "Relevant", [1, 0]),
        ]
        with patch.object(generation, "create_connection", return_value=self.connection([rows])), patch.object(
            generation, "_query_embedding", return_value=[1, 0]
        ):
            resultaat = generation.zoek_relevante_data("opdracht", "Klik", kanaal="Website", aantal=2)
        self.assertLess(resultaat.index("Relevant"), resultaat.index("Minder relevant"))
        self.assertNotIn("Social", resultaat)

    def test_full_document_text_is_returned(self):
        tekst = "Opening.\n\nWat ga je doen?\n- Taak\n\nSolliciteer direct!"
        rows = [self.row("a", "website_vacatuur_teksten/v.docx", tekst, [1, 0])] * 2
        with patch.object(generation, "create_connection", return_value=self.connection([rows])):
            self.assertIn(tekst, generation.zoek_relevante_data("opdracht", "Klik", kanaal="Website"))

    def test_other_companies_used_when_company_has_no_texts(self):
        rows = [self.row("a", "social_media_teksten/v.docx", "Verhaal", [1, 0], bedrijf="STB")]
        eigen = [self.row("b", "website_vacatuur_teksten/vac.docx", "Eigen vacature", [1, 0])]
        for eigen_rows in ([], eigen):
            with self.subTest(eigen=bool(eigen_rows)), patch.object(
                generation, "create_connection", return_value=self.connection([eigen_rows, rows])
            ):
                resultaat = generation.zoek_relevante_data("opdracht", "Klik", kanaal="LinkedIn")
            self.assertIn("Verhaal", resultaat)
            self.assertIn("ander bedrijf", resultaat)
            if eigen_rows:
                self.assertIn("Eigen vacature", resultaat)

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
