"""Tests voor planning_posts.

Start: python -m unittest discover -s kalender/tests -t kalender -p test_planning_posts.py -v
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from planning_posts import (
    JAARPLANNING_BESTAND,
    bepaal_bedrijf,
    bepaal_dag,
    bepaal_kanaal,
    formatteer_datum,
    jaar_uit_bestandsnaam,
    lees_posts,
    posts_naar_dataframe,
    posts_uit_werkblad,
)


EXCEL_FILE = JAARPLANNING_BESTAND


class KolomnaamTests(unittest.TestCase):
    def test_kanaal(self):
        cases = {
            "Post socials (dinsdag)": "Socials",
            "Post dinsdag": "Socials",
            "Post (woensdag)": "Socials",
            "Post LinkedIn (woensdag)": "LinkedIn",
            "Post Instagram (woensdag)": "Instagram",
            "Post LI en Insta (donderdag)": "LinkedIn + Instagram",
            "Post TikTok (wisselend)": "TikTok",
            "Post nieuwsbrief DGC": "Nieuwsbrief",
            "Post website": "Website",
        }
        for kolom, kanaal in cases.items():
            with self.subTest(kolom=kolom):
                self.assertEqual(bepaal_kanaal(kolom), kanaal)

    def test_dag(self):
        self.assertEqual(bepaal_dag("Post socials (dinsdag)"), 2)
        self.assertEqual(bepaal_dag("Post socials (donderdag )"), 4)
        self.assertEqual(bepaal_dag("Post dinsdag"), 2)
        self.assertIsNone(bepaal_dag("Post TikTok (wisselend)"))
        self.assertIsNone(bepaal_dag("Post website"))

    def test_bedrijf(self):
        self.assertEqual(bepaal_bedrijf("TTI"), "Terberg Totaal Installaties")
        self.assertEqual(bepaal_bedrijf("TBN "), "Technish beheer Nederland")
        self.assertEqual(bepaal_bedrijf("TVB Ac"), "TVB academy")
        with self.assertLogs("planning_posts", "WARNING"):
            self.assertEqual(bepaal_bedrijf(" Nieuw "), "Nieuw")

    def test_jaar_en_datum(self):
        self.assertEqual(jaar_uit_bestandsnaam(Path("Jaarplanning social media 2026.xlsx")), 2026)
        self.assertIsNone(jaar_uit_bestandsnaam(Path("planning.xlsx")))
        self.assertEqual(formatteer_datum(date(2026, 1, 6)), "di 6 jan 2026")


class WerkbladTests(unittest.TestCase):
    def werkblad(self):
        # Opbouw zoals het TTI-blad: twee posts per week, elk met eigen Soort content.
        return pd.DataFrame({
            "Week ": ["Start Q1 2026 (1 jan t/m 31 maart)", 2, 3, 4],
            "Post socials (dinsdag)": [None, "Employer branding", None, None],
            "Soort content ": [None, "Carriere verhaal", None, None],
            "Post socials (donderdag )": [None, "Project TTIR", "Overig", None],
            "Soort content": [None, "Projectupdate met foto's", None, None],
            "Post TikTok": [None, None, None, "Trend"],
            "Bijzonderheden/inhakers/etc.": [None, "Inhaker", None, None],
        })

    def test_een_regel_per_post_met_juiste_soort_content(self):
        posts = posts_uit_werkblad(self.werkblad(), "TTI", 2026)

        self.assertEqual(
            [(p.week, p.kanaal, p.onderwerp, p.soort_content) for p in posts],
            [
                (2, "Socials", "Employer branding", "Carriere verhaal"),
                (2, "Socials", "Project TTIR", "Projectupdate met foto's"),
                (3, "Socials", "Overig", None),
                (4, "TikTok", "Trend", None),
            ],
        )
        self.assertTrue(all(p.bedrijf == "Terberg Totaal Installaties" for p in posts))

    def test_datum_uit_week_en_dag(self):
        posts = posts_uit_werkblad(self.werkblad(), "TTI", 2026)

        self.assertEqual(posts[0].datum, date(2026, 1, 6))  # dinsdag week 2
        self.assertEqual(posts[1].datum, date(2026, 1, 8))  # donderdag week 2
        self.assertTrue(posts[1].dag_bekend)
        self.assertEqual(posts[3].datum, date(2026, 1, 19))  # maandag week 4
        self.assertFalse(posts[3].dag_bekend)
        self.assertEqual(posts[3].datum_tekst, "week 4 (vanaf ma 19 jan 2026)")

    def test_bijzonderheden_gelden_voor_alle_posts_van_de_week(self):
        posts = posts_uit_werkblad(self.werkblad(), "TTI", 2026)

        self.assertEqual([p.bijzonderheden for p in posts], ["Inhaker", "Inhaker", None, None])

    def test_kwartaalkop_en_lege_weken_overgeslagen(self):
        posts = posts_uit_werkblad(self.werkblad(), "TTI", 2026)

        self.assertNotIn(1, [p.week for p in posts])
        self.assertEqual(len(posts), 4)

    def test_week_53_bestaat_niet_in_elk_jaar(self):
        df = pd.DataFrame({"Week": [53], "Post (woensdag)": ["Project"]})

        self.assertEqual(len(posts_uit_werkblad(df, "EC", 2026)), 1)
        with self.assertLogs("planning_posts", "WARNING"):
            self.assertEqual(posts_uit_werkblad(df, "EC", 2027), [])

    def test_blad_zonder_post_kolommen_geeft_fout(self):
        with self.assertRaisesRegex(ValueError, "Geen Post-kolommen"):
            posts_uit_werkblad(pd.DataFrame({"Week": [1], "Notitie": ["x"]}), "EC", 2026)


class LeesPostsTests(unittest.TestCase):
    def test_gesorteerd_op_datum_en_fouten_gemeld(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "Planning 2026.xlsx"
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                pd.DataFrame({"Week": [3], "Post (woensdag)": ["Later"]}).to_excel(
                    writer, sheet_name="EC", index=False
                )
                pd.DataFrame({"Week": [2], "Post LinkedIn (woensdag)": ["Eerder"]}).to_excel(
                    writer, sheet_name="TVB", index=False
                )
                pd.DataFrame({"Onderwerp": ["x"]}).to_excel(writer, sheet_name="Fout", index=False)

            posts, fouten = lees_posts(path)

        self.assertEqual([p.onderwerp for p in posts], ["Eerder", "Later"])
        self.assertEqual([f["tabel"] for f in fouten], ["Fout"])
        self.assertIn("datum_tekst", posts_naar_dataframe(posts).columns)

    @unittest.skipUnless(EXCEL_FILE.exists(), "Jaarplanning-Excel niet aanwezig")
    def test_echte_planning(self):
        posts, fouten = lees_posts(EXCEL_FILE)

        self.assertEqual(fouten, [])
        self.assertEqual(
            {p.bron for p in posts},
            {"TTI", "TBN", "VR", "STB", "TVB", "MVIE", "EC", "VDB", "TVB Ac"},
        )
        self.assertTrue(all(p.onderwerp or p.soort_content for p in posts))
        self.assertTrue(all(1 <= p.week <= 53 for p in posts))


if __name__ == "__main__":
    unittest.main()
