"""Tests voor excel_normalizer.

Start: cd calander_automatisering; python -m unittest test_excel_normalizer -v
"""

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from excel_normalizer import (
    clean_week,
    find_week_column,
    lees_evenementen,
    make_safe_column_name,
    make_unique_column_name,
    normalize_sheet,
)


EXCEL_FILE = Path(__file__).resolve().parent / "Jaarplanning social media 2026.xlsx"


class CleanWeekTests(unittest.TestCase):
    def test_valid_notations(self):
        for value in [40, 40.0, "40", "Week 40", "week 40", "WK40", " 40 "]:
            with self.subTest(value=value):
                self.assertEqual(clean_week(value), 40)

    def test_invalid_values(self):
        for value in [
            None, float("nan"), "", "geen week", 0, 54, "Week 99",
            "Start Q1 2026 (1 jan t/m 31 maart)",
        ]:
            with self.subTest(value=value):
                self.assertIs(clean_week(value), pd.NA)


class ColumnNameTests(unittest.TestCase):
    def test_find_week_column(self):
        self.assertEqual(find_week_column(["Week ", "Post"]), "Week ")
        self.assertEqual(find_week_column(["Week-Nummer", "Post"]), "Week-Nummer")
        self.assertEqual(find_week_column(["WK", "Post"]), "WK")
        self.assertEqual(find_week_column(["Post", "Weekplanning"]), "Weekplanning")
        self.assertIsNone(find_week_column(["Post", "Soort content"]))

    def test_make_safe_column_name(self):
        self.assertEqual(make_safe_column_name("Soort content "), "soort_content")
        self.assertEqual(make_safe_column_name("Bijzonderheden/inhakers/etc."), "bijzonderheden_inhakers_etc")
        self.assertEqual(make_safe_column_name("Post socials (dinsdag)"), "post_socials_dinsdag")
        self.assertEqual(make_safe_column_name("Post / content"), "post_content")

    def test_make_unique_column_name(self):
        self.assertEqual(make_unique_column_name("content", ["week"]), "content")
        self.assertEqual(make_unique_column_name("content", ["content"]), "content_2")
        self.assertEqual(make_unique_column_name("content", ["content", "content_2"]), "content_3")


class NormalizeSheetTests(unittest.TestCase):
    def test_keeps_all_columns_and_drops_rows_without_week(self):
        df = pd.DataFrame({
            "Week ": [1, "Week 2", None, "x"],
            "Post socials (dinsdag)": ["Vacature", None, "Zonder week", "Ongeldig"],
            "Soort content ": ["Werving", "Branding", None, None],
            "Soort content": ["A", "B", None, None],
        })
        result = normalize_sheet(df, "TTI")

        self.assertEqual(result["week"].tolist(), [1, 2])
        self.assertEqual(
            list(result.columns),
            ["week", "post_socials_dinsdag", "soort_content", "soort_content_2", "bron"],
        )
        self.assertEqual(result.loc[0, "post_socials_dinsdag"], "Vacature")
        self.assertTrue(pd.isna(result.loc[1, "post_socials_dinsdag"]))
        self.assertEqual(set(result["bron"]), {"TTI"})

    def test_missing_week_column_raises(self):
        with self.assertRaisesRegex(ValueError, "Geen weekkolom"):
            normalize_sheet(pd.DataFrame({"Post": ["x"]}), "Leeg")

    def test_empty_sheet_raises(self):
        with self.assertRaisesRegex(ValueError, "geen gegevens"):
            normalize_sheet(pd.DataFrame({"Week": [None]}), "Leeg")


class LeesEvenementenTests(unittest.TestCase):
    def test_multiple_sheets_sorted_by_week_with_errors_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "planning.xlsx"
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                pd.DataFrame({"Week": [3, 1], "Post (woensdag)": ["C", "A"]}).to_excel(
                    writer, sheet_name="EC", index=False
                )
                pd.DataFrame({"Weeknr": [2], "Post LinkedIn": ["B"]}).to_excel(
                    writer, sheet_name="TVB", index=False
                )
                pd.DataFrame({"Onderwerp": ["geen week"]}).to_excel(
                    writer, sheet_name="Fout", index=False
                )

            evenementen, fouten = lees_evenementen(path)

        self.assertEqual([e["week"] for e in evenementen], [1, 2, 3])
        self.assertEqual([e["bron"] for e in evenementen], ["EC", "TVB", "EC"])
        self.assertEqual(evenementen[1]["post_linkedin"], "B")
        self.assertEqual([f["tabel"] for f in fouten], ["Fout"])

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            lees_evenementen("bestaat_niet.xlsx")

    @unittest.skipUnless(EXCEL_FILE.exists(), "Jaarplanning-Excel niet aanwezig")
    def test_real_planning_reads_all_sheets(self):
        """Waarschuwt als een werkblad in de echte planning niet meer herkend wordt."""
        evenementen, fouten = lees_evenementen(EXCEL_FILE)

        self.assertEqual(fouten, [])
        self.assertTrue(evenementen)
        self.assertTrue(all(1 <= e["week"] <= 53 for e in evenementen))


if __name__ == "__main__":
    unittest.main()
