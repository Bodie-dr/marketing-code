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


class FotoMapTests(unittest.TestCase):
    def test_map_met_submappen_alleen_fotos(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "sub").mkdir()
            for naam in ["b.JPG", "a.png", "sub/c.webp", "notitie.txt", "~$tijdelijk.jpg", ".verborgen.png"]:
                (root / naam).write_bytes(b"x")
            los = root / "los.jpeg"
            los.write_bytes(b"x")

            gevonden = qb.verzamel_fotos([str(root), f'"{los}"', None, ""])

        self.assertEqual([p.name for p in gevonden], ["a.png", "b.JPG", "los.jpeg", "c.webp"])

    def test_zelfde_foto_niet_dubbel(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            foto = Path(folder) / "a.jpg"
            foto.write_bytes(b"x")
            self.assertEqual(len(qb.verzamel_fotos([folder, str(foto)])), 1)

    def test_verdeelde_selectie(self):
        paden = list(range(40))
        self.assertEqual(qb.kies_verdeeld(paden, 4), [0, 10, 20, 30])
        self.assertEqual(qb.kies_verdeeld(paden[:5], 12), [0, 1, 2, 3, 4])
        self.assertEqual(len(qb.kies_verdeeld(paden, 12)), 12)
        self.assertEqual(qb.kies_verdeeld(paden, 0), paden)


class KleurpaletTests(unittest.TestCase):
    def foto(self, vlakken):
        """Foto met verticale banen: [(kleur, breedte), ...]."""
        breedte = sum(w for _, w in vlakken)
        foto = Image.new("RGB", (breedte, 50))
        x = 0
        for kleur, w in vlakken:
            foto.paste(kleur, (x, 0, x + w, 50))
            x += w
        return foto

    def test_echte_kleuren_en_aandelen(self):
        import kleurpalet as kp

        foto = self.foto([((60, 60, 60), 70), ((200, 200, 200), 20), ((30, 90, 200), 10)])
        palet = kp.extraheer_palet([foto], aantal=3, accenten=2)

        hoofd = {k["hex"]: k["aandeel"] for k in palet if k["soort"] == "hoofd"}
        self.assertEqual(set(hoofd), {"#3C3C3C", "#C8C8C8", "#1E5AC8"})
        self.assertAlmostEqual(hoofd["#3C3C3C"], 0.7, places=2)
        accenten = [k for k in palet if k["soort"] == "accent"]
        self.assertEqual([k["hex"] for k in accenten], ["#1E5AC8"])  # alleen het blauw is gekleurd

    def test_klein_accent_wordt_gevonden_naast_grote_grijze_vlakken(self):
        import kleurpalet as kp

        foto = self.foto([((120, 120, 120), 97), ((20, 110, 220), 3)])
        palet = kp.extraheer_palet([foto], aantal=1, accenten=1)

        self.assertEqual([k["soort"] for k in palet], ["hoofd", "accent"])
        self.assertEqual(palet[1]["hex"], "#146EDC")

    def test_grijze_foto_heeft_geen_accenten(self):
        import kleurpalet as kp

        palet = kp.extraheer_palet([self.foto([((90, 90, 90), 50), ((180, 180, 180), 50)])])
        self.assertFalse([k for k in palet if k["soort"] == "accent"])

    def test_lab_omzetting_heen_en_terug(self):
        import numpy as np

        import kleurpalet as kp

        rgb = np.array([[0, 0, 0], [255, 255, 255], [34, 45, 79], [56, 181, 168]], dtype=float)
        self.assertTrue(np.array_equal(kp.lab_naar_rgb(kp.rgb_naar_lab(rgb)), rgb.astype(int)))

    def test_analyse_gebruikt_gemeten_kleuren_niet_die_van_het_model(self):
        import json

        model_antwoord = json.dumps({**STIJL, "kleurpalet": ["#1ABC9C", "#E74C3C", "#8E44AD"]})
        foto = self.foto([((60, 60, 60), 80), ((30, 90, 200), 20)])
        with mock.patch.object(qb, "_analyseer_cloud", return_value=model_antwoord) as analyse:
            stijl, _ = qb.analyseer_stijl([foto], backend="cloud")

        self.assertNotIn("#1ABC9C", stijl["kleurpalet"])
        self.assertIn("#3C3C3C", stijl["kleurpalet"])
        self.assertEqual(stijl["kleurpalet"], [k["hex"] for k in stijl["kleurpalet_details"]])
        instructie = analyse.call_args[0][1]
        self.assertIn("Gemeten kleuren", instructie)
        self.assertIn("#3C3C3C", instructie)


class UploadTests(unittest.TestCase):
    def test_grote_foto_wordt_verkleind_tot_jpeg(self):
        import io

        foto = Image.new("RGB", (6779, 4512), (40, 80, 160))
        data = qb.upload_bytes(foto, max_zijde=2048)

        with Image.open(io.BytesIO(data)) as resultaat:
            self.assertEqual(resultaat.format, "JPEG")
            self.assertEqual(max(resultaat.size), 2048)
            self.assertEqual(resultaat.size, (2048, 1363))  # verhouding blijft gelijk
        self.assertEqual(foto.size, (6779, 4512), "origineel mag niet veranderen")

    def test_kleine_foto_wordt_niet_vergroot_en_rgba_werkt(self):
        import io

        data = qb.upload_bytes(Image.new("RGBA", (800, 600)), max_zijde=2048)
        with Image.open(io.BytesIO(data)) as resultaat:
            self.assertEqual(resultaat.size, (800, 600))

    def test_doelformaat_houdt_verhouding(self):
        for invoer in [(6779, 4512), (4512, 6779), (1000, 1000), (1920, 1080)]:
            with self.subTest(invoer=invoer):
                breedte, hoogte = qb.doelformaat(*invoer)
                self.assertEqual((breedte % 16, hoogte % 16), (0, 0))
                self.assertAlmostEqual(breedte / hoogte, invoer[0] / invoer[1], delta=0.03)
                self.assertAlmostEqual(breedte * hoogte / 1e6, 1.6, delta=0.1)

    def test_413_geeft_duidelijke_melding(self):
        fout = qb._vertaal_hf_fout(Exception("Client error '413 Payload Too Large' for url ..."))
        self.assertIn("QWEN_MAX_EDIT_ZIJDE", str(fout))


class VerwijderStijlTests(unittest.TestCase):
    def test_stijl_gaat_naar_prullenbak_en_verdwijnt_uit_lijst(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            stijlen = Path(folder)
            with mock.patch.object(qb, "STIJL_DIR", stijlen), \
                    mock.patch.object(qb, "PRULLENBAK_DIR", stijlen / "_prullenbak"):
                qb.sla_stijl_op("Zomer campagne", STIJL, 3, "cloud")
                qb.sla_stijl_op("Winter", STIJL, 2, "cloud")

                eerste = qb.verwijder_stijl("Zomer_campagne")
                qb.sla_stijl_op("Zomer campagne", STIJL, 3, "cloud")
                tweede = qb.verwijder_stijl("Zomer_campagne")

                self.assertEqual(qb.stijl_namen(), ["Winter"])
                self.assertTrue(eerste.exists() and tweede.exists())
                self.assertNotEqual(eerste, tweede, "eerder verwijderde versie niet overschrijven")
                with self.assertRaisesRegex(ValueError, "bestaat niet"):
                    qb.verwijder_stijl("Bestaat niet")


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
