"""Tests voor de LoRA-hulpscripts, LUT en logo (zonder GPU of API).

Start: python -m unittest discover -s fotogeneratie/tests -t fotogeneratie -p test_lora_tools.py -v
"""

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lora"))

import maak_captions as mc  # noqa: E402
import maak_pakket  # noqa: E402
import pas_lut_toe as lut  # noqa: E402
import selecteer_fotos as sf  # noqa: E402
import vergelijk_checkpoints as vc  # noqa: E402
import voeg_logo_toe as logo  # noqa: E402


def testfoto(seed: int, grootte=(1024, 800)) -> Image.Image:
    """Willekeurige, scherpe foto met een paar vlakken in eigen kleuren."""
    rng = np.random.default_rng(seed)
    beeld = Image.new("RGB", grootte, tuple(int(v) for v in rng.integers(0, 255, 3)))
    teken = ImageDraw.Draw(beeld)
    for _ in range(12):
        x0, y0 = int(rng.integers(0, max(1, grootte[0] - 50))), int(rng.integers(0, max(1, grootte[1] - 50)))
        x1, y1 = x0 + int(rng.integers(20, 400)), y0 + int(rng.integers(20, 400))
        teken.rectangle((x0, y0, x1, y1), fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    return beeld


class SelecteerTests(unittest.TestCase):
    def test_wazig_dubbel_en_klein_worden_afgekeurd(self):
        with tempfile.TemporaryDirectory() as tmp:
            map_ = Path(tmp)
            for i in range(8):
                testfoto(i).save(map_ / f"foto{i}.jpg", quality=95)
            testfoto(0).save(map_ / "kopie.jpg", quality=80)
            testfoto(1).filter(ImageFilter.GaussianBlur(12)).save(map_ / "wazig.jpg")
            testfoto(2, (600, 400)).save(map_ / "klein.jpg")

            fotos = [sf.analyseer(p) for p in sf.verzamel(map_)]
            gekozen = sf.selecteer(fotos, aantal=5)
            status = {f.pad.name: (f.status, f.reden) for f in fotos}

        self.assertEqual(len(gekozen), 5)
        self.assertTrue(status["wazig.jpg"][1].startswith("wazig"))
        self.assertTrue(status["klein.jpg"][1].startswith("te klein"))
        dubbel = [n for n in ("foto0.jpg", "kopie.jpg") if status[n][1].startswith("bijna-dubbel")]
        self.assertEqual(len(dubbel), 1)
        self.assertEqual(sum(s == "gekozen" for s, _ in status.values()), 5)

    def test_kiest_alles_als_er_weinig_zijn(self):
        kandidaten = [sf.Foto(Path(f"{i}.jpg"), scherpte=i, kenmerken=np.full(3, i)) for i in range(3)]
        self.assertEqual(len(sf.kies_gevarieerd(kandidaten, 10)), 3)

    def test_kies_gevarieerd_neemt_uitersten(self):
        punten = [0.0, 0.1, 0.2, 5.0, 10.0]
        kandidaten = [sf.Foto(Path(f"{i}.jpg"), scherpte=p, kenmerken=np.array([p])) for i, p in enumerate(punten)]
        gekozen = {f.kenmerken[0] for f in sf.kies_gevarieerd(kandidaten, 3)}
        self.assertEqual(gekozen, {0.0, 5.0, 10.0})


class ProductCaptionTests(unittest.TestCase):
    def test_triggerwoord_vooraan_en_kwaliteitswoorden_weg(self):
        caption = mc.maak_product_caption(
            "This image shows a professional photo of it being carried by a man, on a construction site, "
            "seen from the side, overcast daylight.",
            "tvbprod",
        )
        self.assertEqual(
            caption, "tvbprod, it being carried by a man, on a construction site, seen from the side, overcast daylight"
        )

    def test_licht_blijft_staan(self):
        caption = mc.maak_product_caption("standing on a workbench, close-up, warm indoor light", "tvbprod")
        self.assertIn("warm indoor light", caption)

    def test_geen_dubbel_triggerwoord(self):
        self.assertEqual(mc.maak_product_caption("tvbprod, on a table", "tvbprod"), "tvbprod, on a table")

    def test_instructie_noemt_product(self):
        self.assertIn("a cordless drill", mc.product_instructie("a cordless drill"))
        self.assertNotIn("{", mc.product_instructie())

    def test_verboden_woorden_lezen(self):
        with tempfile.TemporaryDirectory() as tmp:
            pad = Path(tmp) / "v.txt"
            pad.write_text("# commentaar\nlogo\n\nred\n", encoding="utf-8")
            self.assertEqual(mc.lees_verboden_woorden(pad), ["logo", "red"])


def schrijf_cube(pad: Path, grootte: int, functie) -> None:
    regels = ['TITLE "test"', f"LUT_3D_SIZE {grootte}"]
    for b in range(grootte):
        for g in range(grootte):
            for r in range(grootte):
                waarde = functie(np.array([r, g, b]) / (grootte - 1))
                regels.append(" ".join(f"{v:.6f}" for v in waarde))
    pad.write_text("\n".join(regels), encoding="utf-8")


class LutTests(unittest.TestCase):
    def test_identiteit_verandert_niets(self):
        with tempfile.TemporaryDirectory() as tmp:
            pad = Path(tmp) / "id.cube"
            schrijf_cube(pad, 5, lambda rgb: rgb)
            tabel, lo, hi = lut.lees_cube(pad)
        foto = testfoto(3, (64, 48))
        uit = lut.pas_toe(foto, tabel, lo, hi)
        verschil = np.abs(np.asarray(uit, dtype=int) - np.asarray(foto, dtype=int)).max()
        self.assertLessEqual(verschil, 1)

    def test_kanaalvolgorde_rood_loopt_snelst(self):
        with tempfile.TemporaryDirectory() as tmp:
            pad = Path(tmp) / "wissel.cube"
            schrijf_cube(pad, 3, lambda rgb: rgb[::-1])  # rood <-> blauw
            tabel, lo, hi = lut.lees_cube(pad)
        uit = lut.pas_toe(Image.new("RGB", (2, 2), (255, 0, 0)), tabel, lo, hi)
        self.assertEqual(uit.getpixel((0, 0)), (0, 0, 255))

    def test_sterkte_nul_is_origineel(self):
        with tempfile.TemporaryDirectory() as tmp:
            pad = Path(tmp) / "zwart.cube"
            schrijf_cube(pad, 2, lambda rgb: np.zeros(3))
            tabel, lo, hi = lut.lees_cube(pad)
        foto = Image.new("RGB", (2, 2), (120, 60, 30))
        self.assertEqual(lut.pas_toe(foto, tabel, lo, hi, sterkte=0).getpixel((0, 0)), (120, 60, 30))

    def test_verkeerd_aantal_waarden(self):
        with tempfile.TemporaryDirectory() as tmp:
            pad = Path(tmp) / "kapot.cube"
            pad.write_text("LUT_3D_SIZE 2\n0 0 0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "verwacht 8"):
                lut.lees_cube(pad)


class LogoTests(unittest.TestCase):
    def setUp(self):
        self.jpg_logo = Image.new("RGB", (100, 60), (35, 45, 80))
        ImageDraw.Draw(self.jpg_logo).rectangle((30, 20, 70, 40), fill=(255, 255, 255))

    def test_achtergrond_wordt_transparant_en_bijgesneden(self):
        los = logo.maak_transparant(self.jpg_logo)
        self.assertEqual(los.mode, "RGBA")
        self.assertLessEqual(los.width, 45)
        self.assertEqual(los.getpixel((los.width // 2, los.height // 2))[:3], (255, 255, 255))

    def test_badge_behoudt_achtergrondkleur(self):
        badge = logo.maak_badge(self.jpg_logo)
        self.assertEqual(badge.getpixel((badge.width // 2, 3))[:3], (35, 45, 80))
        self.assertEqual(badge.getpixel((0, 0))[3], 0)  # afgeronde hoek

    def test_rechtsonder_met_marge(self):
        foto = Image.new("RGB", (1000, 500), (0, 200, 0))
        rood = Image.new("RGBA", (50, 25), (255, 0, 0, 255))
        uit, factor = logo.plaats_logo(foto, rood, "rechtsonder", breedte=0.1, marge=0.04)
        self.assertEqual(factor, 2.0)
        # Logo: 100x50, marge 20 px -> rechtsonder op x 880-979, y 430-479
        self.assertEqual(uit.getpixel((930, 455))[:3], (255, 0, 0))
        self.assertEqual(uit.getpixel((990, 490))[:3], (0, 200, 0))
        self.assertEqual(uit.getpixel((50, 50))[:3], (0, 200, 0))

    def test_onbekende_positie(self):
        with self.assertRaises(ValueError):
            logo.plaats_logo(Image.new("RGB", (10, 10)), Image.new("RGBA", (2, 2)), "midden")

    def test_meegeleverd_logo_bestaat(self):
        self.assertTrue(logo.STANDAARD_LOGO.exists())


class CheckpointTests(unittest.TestCase):
    def test_raster_per_prompt_en_stap(self):
        with tempfile.TemporaryDirectory() as tmp:
            map_ = Path(tmp)
            for stap in (0, 250, 500):
                for prompt in range(3):
                    Image.new("RGB", (64, 64)).save(map_ / f"1727780000_{stap:09d}_{prompt}.jpg")
            (map_ / "notities.txt").write_text("x")
            samples = vc.lees_samples(map_)
            self.assertEqual(sorted(samples), [0, 1, 2])
            self.assertEqual(sorted(samples[0]), [0, 250, 500])
            raster = vc.maak_raster(samples, tegel=100, vanaf=250)
        self.assertEqual(raster.size, (60 + 2 * 100, 36 + 3 * 100))

    def test_leeg_bereik(self):
        with self.assertRaises(ValueError):
            vc.maak_raster({0: {250: Path("x.jpg")}}, vanaf=1000)


class PakketTests(unittest.TestCase):
    def test_naam_alleen_bij_de_run(self):
        tekst = 'config:\n  name: "oud_v1"\nmeta:\n  name: "[name]"\n'
        nieuw = maak_pakket.zet_naam(tekst, "nieuw_v2")
        self.assertIn('name: "nieuw_v2"', nieuw)
        self.assertIn('name: "[name]"', nieuw)
        self.assertEqual(maak_pakket.config_naam(nieuw), "nieuw_v2")

    def test_zip_bevat_dataset_config_en_lf_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp) / "set"
            dataset.mkdir()
            Image.new("RGB", (8, 8)).save(dataset / "a.jpg")
            (dataset / "a.txt").write_text("tvbprod, on a table")
            (dataset / "rapport.csv").write_text("x")
            doel = Path(tmp) / "uit" / "p.zip"
            aantal = maak_pakket.maak_zip(dataset, 'name: "x"', doel)
            with zipfile.ZipFile(doel) as archief:
                namen = set(archief.namelist())
                script = archief.read("runpod_train.sh")
        self.assertEqual(aantal, 2)
        self.assertEqual(namen, {"dataset/a.jpg", "dataset/a.txt", "ai_toolkit_product.yaml", "runpod_train.sh"})
        self.assertNotIn(b"\r\n", script)

    def test_config_is_geldige_yaml_met_dataset(self):
        tekst = maak_pakket.CONFIG.read_text(encoding="utf-8")
        self.assertIn('folder_path: "/workspace/dataset"', tekst)
        self.assertIn('arch: "qwen_image"', tekst)
        self.assertEqual(maak_pakket.config_naam(tekst), "tvbprod_qwen_image_v1")


if __name__ == "__main__":
    unittest.main()
