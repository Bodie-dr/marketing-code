import unittest
from unittest import mock

from PIL import Image

import qwen_backend as qb

STIJL = {
    "samenvatting": "Warm en zonnig.",
    "kleurpalet": ["#222D4F", "#38B5A8"],
    "belichting": "Zacht zijlicht",
    "compositie": "Centraal",
    "sfeer": "Vrolijk",
    "nabewerking": "Lichte korrel",
    "stijl_prompt": "warm golden-hour light, soft film grain.",
}


class TestLeesStijlJson(unittest.TestCase):
    def test_json_in_codeblok(self):
        tekst = "Hier is het profiel:\n```json\n" + qb.json.dumps(STIJL) + "\n```"
        self.assertEqual(qb.lees_stijl_json(tekst), STIJL)

    def test_geen_json(self):
        with self.assertRaises(ValueError):
            qb.lees_stijl_json("Sorry, dat kan ik niet.")

    def test_ontbrekend_veld(self):
        onvolledig = {k: v for k, v in STIJL.items() if k != "stijl_prompt"}
        with self.assertRaisesRegex(ValueError, "stijl_prompt"):
            qb.lees_stijl_json(qb.json.dumps(onvolledig))


class TestBouwEditPrompt(unittest.TestCase):
    def test_alleen_instructie(self):
        self.assertEqual(qb.bouw_edit_prompt("Maak de lucht blauw.", None), "Maak de lucht blauw")

    def test_alleen_stijl(self):
        prompt = qb.bouw_edit_prompt("", STIJL)
        self.assertIn("Restyle this photo", prompt)
        self.assertIn("warm golden-hour light, soft film grain.", prompt)
        self.assertIn("#38B5A8", prompt)

    def test_instructie_en_stijl(self):
        prompt = qb.bouw_edit_prompt("Voeg een koffiekop toe", STIJL)
        self.assertTrue(prompt.startswith("Voeg een koffiekop toe. Apply this visual style"))

    def test_niets(self):
        with self.assertRaises(ValueError):
            qb.bouw_edit_prompt("  ", None)


class TestOverig(unittest.TestCase):
    def test_verklein_houdt_verhouding(self):
        klein = qb.verklein(Image.new("RGB", (4000, 2000)))
        self.assertEqual(klein.size, (1024, 512))

    def test_veilige_naam(self):
        self.assertEqual(qb.veilige_naam("TVB zomer/2026!"), "TVB_zomer2026")
        self.assertEqual(qb.veilige_naam("???"), "stijl")

    def test_kies_backend(self):
        with mock.patch.object(qb, "_cuda_beschikbaar", return_value=False):
            self.assertEqual(qb.kies_backend("auto"), "cloud")
        with mock.patch.object(qb, "_cuda_beschikbaar", return_value=True):
            self.assertEqual(qb.kies_backend("auto"), "lokaal")
        self.assertEqual(qb.kies_backend("cloud"), "cloud")

    def test_stijl_opslaan_en_laden(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(qb, "STIJL_DIR", Path(tmp)):
            qb.sla_stijl_op("Mijn stijl", STIJL, 3, "cloud")
            self.assertEqual(qb.stijl_namen(), ["Mijn_stijl"])
            geladen = qb.laad_stijl("Mijn_stijl")
            self.assertEqual(geladen["stijl_prompt"], STIJL["stijl_prompt"])
            self.assertEqual(geladen["_meta"]["aantal_fotos"], 3)

    def test_lokaal_zonder_gpu_geeft_duidelijke_fout(self):
        with mock.patch.object(qb, "_cuda_beschikbaar", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "NVIDIA"):
                qb.analyseer_stijl([Image.new("RGB", (10, 10))], backend="lokaal")


class HfFoutTests(unittest.TestCase):
    def test_ongeldige_token_geeft_duidelijke_melding(self):
        fout = qb._vertaal_hf_fout(Exception(
            "Client error '401 Unauthorized' for url 'https://router.huggingface.co/v1/chat/completions'"
            "\n\nInvalid username or password."
        ))
        self.assertIsInstance(fout, PermissionError)
        self.assertIn("nieuwe token", str(fout))

    def test_ontbrekende_permissie_en_tegoed(self):
        self.assertIn(
            "Make calls to Inference Providers",
            str(qb._vertaal_hf_fout(Exception("403 Forbidden: Inference Providers niet toegestaan"))),
        )
        self.assertIn("tegoed", str(qb._vertaal_hf_fout(Exception("402 Payment Required"))))

    def test_andere_fout_blijft_ongewijzigd(self):
        origineel = Exception("500 Server Error")
        self.assertIs(qb._vertaal_hf_fout(origineel), origineel)


if __name__ == "__main__":
    unittest.main()
