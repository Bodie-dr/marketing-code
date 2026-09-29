"""Zet de social-media jaarplanning om naar één regel per post.

Elk werkblad is één bedrijf. Per week kan een regel meerdere posts bevatten
(bijvoorbeeld dinsdag en donderdag), elk met een eigen "Soort content"-kolom
direct erna. Dag en kanaal staan in de kolomnaam, zoals
"Post LinkedIn (woensdag)".
"""

import logging
import os
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from excel_normalizer import (
    clean_column_name,
    clean_text,
    clean_week,
    find_week_column,
)


logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

load_dotenv(PROJECT_DIR / ".env")


def standaard_excel_bestand() -> Path:
    """Pad uit CALENDAR_EXCEL_FILE in .env, anders de kopie in deze map."""
    return Path(
        os.getenv("CALENDAR_EXCEL_FILE", "").strip()
        or BASE_DIR / "Jaarplanning social media 2026.xlsx"
    )


# Werkbladnaam -> bedrijfsnaam zoals in de kennisbank van de tekstgenerator.
BEDRIJVEN = {
    "TTI": "Terberg Totaal Installaties",
    "TBN": "Technish beheer Nederland",
    "VR": "Vr Bedrijven",
    "STB": "STB",
    "TVB": "TVB",
    "MVIE": "MVIE",
    "EC": "E-control",
    "VDB": "Van den Broek Loodgietersbedrijf",
    "TVB AC": "TVB academy",
}

DAGEN = {
    "maandag": 1,
    "dinsdag": 2,
    "woensdag": 3,
    "donderdag": 4,
    "vrijdag": 5,
    "zaterdag": 6,
    "zondag": 7,
}

KORTE_DAGEN = ["ma", "di", "wo", "do", "vr", "za", "zo"]

MAANDEN = [
    "jan", "feb", "mrt", "apr", "mei", "jun",
    "jul", "aug", "sep", "okt", "nov", "dec",
]


@dataclass(frozen=True)
class Post:
    bedrijf: str
    bron: str
    week: int
    datum: date
    dag_bekend: bool
    kanaal: str
    onderwerp: str | None
    soort_content: str | None
    bijzonderheden: str | None

    @property
    def datum_tekst(self) -> str:
        if self.dag_bekend:
            return formatteer_datum(self.datum)
        return f"week {self.week} (vanaf {formatteer_datum(self.datum)})"


def formatteer_datum(datum: date) -> str:
    """Bijvoorbeeld: 'di 6 jan 2026'."""
    return (
        f"{KORTE_DAGEN[datum.isoweekday() - 1]} "
        f"{datum.day} {MAANDEN[datum.month - 1]} {datum.year}"
    )


def bepaal_bedrijf(sheet_name: str) -> str:
    sleutel = sheet_name.strip().upper()
    if sleutel not in BEDRIJVEN:
        logger.warning(
            "Onbekend werkblad '%s': voeg het toe aan BEDRIJVEN in planning_posts.py.",
            sheet_name,
        )
        return sheet_name.strip()
    return BEDRIJVEN[sleutel]


def bepaal_kanaal(kolomnaam: str) -> str:
    naam = clean_column_name(kolomnaam)
    if "tiktok" in naam:
        return "TikTok"
    if re.search(r"\bli\b", naam) and "insta" in naam:
        return "LinkedIn + Instagram"
    if "linkedin" in naam:
        return "LinkedIn"
    if "instagram" in naam or "insta" in naam:
        return "Instagram"
    if "nieuwsbrief" in naam:
        return "Nieuwsbrief"
    if "website" in naam:
        return "Website"
    return "Socials"


def bepaal_dag(kolomnaam: str) -> int | None:
    """ISO-weekdag (1 = maandag) uit de kolomnaam, of None als die ontbreekt."""
    naam = clean_column_name(kolomnaam)
    for dagnaam, nummer in DAGEN.items():
        if dagnaam in naam:
            return nummer
    return None


def jaar_uit_bestandsnaam(file_path: Path) -> int | None:
    match = re.search(r"\b(20\d{2})\b", Path(file_path).stem)
    return int(match.group(1)) if match else None


def _groepeer_kolommen(columns):
    """Koppel elke Post-kolom aan de Soort content-kolom die erna komt."""
    groepen = []
    bijzonderheden_kolom = None

    for column in columns:
        naam = clean_column_name(column)
        if naam.startswith("post"):
            groepen.append({"post": column, "soort": None})
        elif naam.startswith("soort content"):
            if groepen and groepen[-1]["soort"] is None:
                groepen[-1]["soort"] = column
            else:
                logger.warning("Kolom '%s' hoort niet bij een Post-kolom en wordt overgeslagen.", column)
        elif naam.startswith("bijzonderheden"):
            bijzonderheden_kolom = column

    return groepen, bijzonderheden_kolom


def _waarde(row, column):
    if column is None:
        return None
    value = clean_text(row[column])
    return None if pd.isna(value) else value


def posts_uit_werkblad(df: pd.DataFrame, sheet_name: str, jaar: int) -> list[Post]:
    week_kolom = find_week_column(df.columns)
    if week_kolom is None:
        raise ValueError(f"Geen weekkolom gevonden in '{sheet_name}'.")

    groepen, bijzonderheden_kolom = _groepeer_kolommen(df.columns)
    if not groepen:
        raise ValueError(f"Geen Post-kolommen gevonden in '{sheet_name}'.")

    bedrijf = bepaal_bedrijf(sheet_name)
    posts = []

    for _, row in df.iterrows():
        week = clean_week(row[week_kolom])
        if pd.isna(week):
            continue

        bijzonderheden = _waarde(row, bijzonderheden_kolom)

        for groep in groepen:
            onderwerp = _waarde(row, groep["post"])
            soort_content = _waarde(row, groep["soort"])
            if onderwerp is None and soort_content is None:
                continue

            dag = bepaal_dag(groep["post"])
            try:
                datum = date.fromisocalendar(jaar, int(week), dag or 1)
            except ValueError:
                logger.warning(
                    "Werkblad '%s': week %s bestaat niet in %s, post overgeslagen.",
                    sheet_name,
                    week,
                    jaar,
                )
                continue

            posts.append(
                Post(
                    bedrijf=bedrijf,
                    bron=sheet_name.strip(),
                    week=int(week),
                    datum=datum,
                    dag_bekend=dag is not None,
                    kanaal=bepaal_kanaal(groep["post"]),
                    onderwerp=onderwerp,
                    soort_content=soort_content,
                    bijzonderheden=bijzonderheden,
                )
            )

    logger.info("Werkblad '%s' (%s): %s posts", sheet_name.strip(), bedrijf, len(posts))
    return posts


def lees_posts(file_path, jaar: int | None = None) -> tuple[list[Post], list[dict]]:
    """Lees alle werkbladen en geef (posts gesorteerd op datum, fouten) terug."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Excel-bestand niet gevonden: {file_path}")

    jaar = jaar or jaar_uit_bestandsnaam(file_path) or date.today().year
    sheets = pd.read_excel(file_path, sheet_name=None, engine="openpyxl")
    logger.info("Excel geladen: %s (%s werkbladen, jaar %s)", file_path.name, len(sheets), jaar)

    posts = []
    fouten = []
    for sheet_name, df in sheets.items():
        try:
            posts.extend(posts_uit_werkblad(df, sheet_name, jaar))
        except Exception as error:
            fouten.append({"tabel": sheet_name, "fout": str(error)})

    posts.sort(key=lambda post: (post.datum, post.bedrijf, post.kanaal))
    return posts, fouten


def posts_naar_dataframe(posts: list[Post]) -> pd.DataFrame:
    rows = [{**asdict(post), "datum_tekst": post.datum_tekst} for post in posts]
    return pd.DataFrame(rows)
