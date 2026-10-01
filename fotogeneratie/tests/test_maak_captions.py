"""Tests voor maak_captions (zonder API-aanroepen).

Start: python -m unittest discover -s fotogeneratie/tests -t fotogeneratie -p test_maak_captions.py -v
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

import maak_captions as mc
import qwen_backend as qb


class FilterTests(unittest.TestCase):
    def test_stijlwoorden_weg_inhoud_blijft(self):
        ruw = (
            "A cozy office lounge with soft natural lighting, two blue booth sofas "
            "and a wooden table, cinematic and moody, shallow depth of field."
        )
        self.assertEqual(
            mc.filter_stijlwoorden(ruw),
            "an office lounge, two blue booth sofas and a wooden table.",
        )

    def test_hele_woorden_niet_binnen_andere_woorden(self):
        # "calm" mag niet uit "calmer" en "grainy" niet uit een ander woord gehaald worden.
        self.assertEqual(mc.filter_stijlwoorden("A calmer street with grain silos"), "a calmer street with grain silos")

    def test_inleiding_en_extra_woorden(self):
        tekst = mc.filter_stijlwoorden("This image shows a meeting room in TVB style.", extra=["in TVB style"])
        self.assertEqual(tekst, "a meeting room.")

    def test_caption_begint_met_trigger(self):
        caption = mc.maak_caption('  "A warm light office\n with desks."  ', "tvbstijl")
        self.assertEqual(caption, "tvbstijl, an office with desks.")


class NaamTests(unittest.TestCase):
    def test_dubbele_namen_uit_submappen(self):
        namen = mc.doelnamen([Path("a/foto.jpg"), Path("b/foto.png"), Path("c/Foto.jpg"), Path("d/x.jpg")])
        self.assertEqual(list(namen.values()), ["foto", "foto_2", "Foto_3", "x"])


class VerwerkTests(unittest.TestCase):
    def test_maakt_dataset_en_slaat_bestaande_over(self):
        with tempfile.TemporaryDirectory() as folder:
            bron = Path(folder) / "bron"
            (bron / "sub").mkdir(parents=True)
            Image.new("RGB", (4000, 3000), "gray").save(bron / "a.jpg")
            Image.new("RGBA", (800, 600)).save(bron / "sub" / "b.png")
            uit = Path(folder) / "dataset"

            antwoord = mock.Mock(return_value="A moody office with a desk.")
            with mock.patch.object(qb, "kies_backend", return_value="cloud"), \
                    mock.patch.object(qb, "_analyseer_cloud", antwoord), \
                    mock.patch("builtins.print"):
                eerste = mc.verwerk([str(bron)], "tvbstijl", uit, max_zijde=1024)
                tweede = mc.verwerk([str(bron)], "tvbstijl", uit)
                opnieuw = mc.verwerk([str(bron)], "tvbstijl", uit, max_zijde=1024, opnieuw=True)

            self.assertEqual(eerste, {"gemaakt": 2, "overgeslagen": 0, "mislukt": 0})
            self.assertEqual(tweede, {"gemaakt": 0, "overgeslagen": 2, "mislukt": 0})
            self.assertEqual(opnieuw["gemaakt"], 2)
            self.assertEqual(antwoord.call_count, 4)
            self.assertIn("training an image model", antwoord.call_args[0][1])

            self.assertEqual(sorted(p.name for p in uit.iterdir()), ["a.jpg", "a.txt", "b.jpg", "b.txt"])
            self.assertEqual((uit / "a.txt").read_text(encoding="utf-8"), "tvbstijl, an office with a desk.\n")
            with Image.open(uit / "a.jpg") as kopie:
                self.assertEqual(kopie.size, (1024, 768))

    def test_fout_bij_een_foto_stopt_de_rest_niet(self):
        with tempfile.TemporaryDirectory() as folder:
            bron = Path(folder)
            Image.new("RGB", (100, 100)).save(bron / "a.jpg")
            Image.new("RGB", (100, 100)).save(bron / "b.jpg")
            with mock.patch.object(qb, "kies_backend", return_value="cloud"), \
                    mock.patch.object(qb, "_analyseer_cloud", side_effect=[RuntimeError("API weg"), "A desk."]), \
                    mock.patch("builtins.print"):
                telling = mc.verwerk([str(bron)], "tvbstijl", bron / "uit")
            self.assertEqual(telling, {"gemaakt": 1, "overgeslagen": 0, "mislukt": 1})


if __name__ == "__main__":
    unittest.main()
