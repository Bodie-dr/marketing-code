import logging
import re
from pathlib import Path

import pandas as pd


logger = logging.getLogger(__name__)


# ============================================================
# WEEK IS DE ENIGE VASTE KOLOM
# ============================================================

WEEK_ALIASES = {
    "week",
    "weeknummer",
    "week nummer",
    "weeknr",
    "week nr",
    "wk",
}


# ============================================================
# KOLOMNAAM OPSCHONEN
# ============================================================

def clean_column_name(column):
    """
    Maakt een kolomnaam geschikt voor vergelijking.

    Voorbeelden:
        ' Week ' -> 'week'
        'Week_Nummer' -> 'week nummer'
        'Week-Nummer' -> 'week nummer'
    """

    value = str(column).strip().lower()

    value = value.replace("_", " ")
    value = value.replace("-", " ")

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    return value.strip()


# ============================================================
# TEKST OPSCHONEN
# ============================================================

def clean_text(value):
    """
    Schoont normale Excel-waarden op.
    """

    if pd.isna(value):
        return pd.NA

    value = str(value).strip()

    if not value:
        return pd.NA

    return value


# ============================================================
# WEEKNUMMER OPSCHONEN
# ============================================================

def clean_week(value):
    """
    Zet verschillende weeknotaties om naar een weeknummer.

    Ondersteunt bijvoorbeeld:

        40
        40.0
        "40"
        "Week 40"
        "week 40"
        "WK40"

    Resultaat:
        40
    """

    if pd.isna(value):
        return pd.NA

    # --------------------------------------------------------
    # Numerieke waarde
    # --------------------------------------------------------

    if isinstance(value, (int, float)):

        try:
            week = int(value)

            if 1 <= week <= 53:
                return week

        except (ValueError, TypeError):
            pass

        return pd.NA

    # --------------------------------------------------------
    # Tekstwaarde
    # --------------------------------------------------------

    value = str(value).strip()

    # Alleen een weeknotatie als geheel accepteren, zodat kopregels zoals
    # "Start Q1 2026 (1 jan t/m 31 maart)" geen nep-week 1 opleveren.
    match = re.fullmatch(
        r"(?:week|wk)?\s*(?:nr\.?|nummer)?\s*(\d{1,2})(?:\.0)?",
        value,
        flags=re.IGNORECASE,
    )

    if match is None:
        return pd.NA

    week = int(
        match.group(1)
    )

    if 1 <= week <= 53:
        return week

    return pd.NA


# ============================================================
# WEEKKOLOM ZOEKEN
# ============================================================

def find_week_column(columns):
    """
    Zoekt de weekkolom.

    Bijvoorbeeld:
        Week
        WEEK
        Weeknummer
        Week nr
        Week-Nummer
    """

    cleaned_columns = {
        clean_column_name(column): column
        for column in columns
    }

    # Exact zoeken
    for alias in WEEK_ALIASES:

        clean_alias = clean_column_name(
            alias
        )

        if clean_alias in cleaned_columns:

            return cleaned_columns[
                clean_alias
            ]

    # --------------------------------------------------------
    # Gedeeltelijk zoeken
    # --------------------------------------------------------

    for cleaned_name, original_name in cleaned_columns.items():

        if "week" in cleaned_name:
            return original_name

    return None


# ============================================================
# VEILIGE NIEUWE KOLOMNAAM MAKEN
# ============================================================

def make_safe_column_name(column):
    """
    Zet iedere Excel-kolomnaam om naar een consistente Python-naam.

    Voorbeelden:

    'Soort content'
        -> 'soort_content'

    'Bijzonderheden'
        -> 'bijzonderheden'

    'Inhakers/etc.'
        -> 'inhakers_etc'

    'Post / content'
        -> 'post_content'
    """

    name = str(column).strip().lower()

    # Verschillende scheidingstekens behandelen als spatie
    name = re.sub(
        r"[/\\&\-]+",
        " ",
        name
    )

    # Speciale tekens verwijderen
    name = re.sub(
        r"[^a-zA-Z0-9\s_]",
        "",
        name
    )

    # Meerdere spaties naar één spatie
    name = re.sub(
        r"\s+",
        " ",
        name
    )

    # Spaties naar underscores
    name = name.strip().replace(
        " ",
        "_"
    )

    # Meerdere underscores samenvoegen
    name = re.sub(
        r"_+",
        "_",
        name
    )

    return name


# ============================================================
# DUBBELE KOLOMNAMEN VOORKOMEN
# ============================================================

def make_unique_column_name(
    column_name,
    existing_columns
):
    """
    Voorkomt dubbele kolomnamen.

    Bijvoorbeeld:

        content
        content

    wordt:

        content
        content_2
    """

    if column_name not in existing_columns:
        return column_name

    counter = 2

    while (
        f"{column_name}_{counter}"
        in existing_columns
    ):

        counter += 1

    return f"{column_name}_{counter}"


# ============================================================
# EEN WERKBLAD NORMALISEREN
# ============================================================

def normalize_sheet(
    df,
    sheet_name
):
    """
    Normaliseert één Excel-werkblad.

    Alleen de weekkolom is verplicht.

    Alle andere kolommen worden automatisch meegenomen.
    """

    df = df.copy()

    # --------------------------------------------------------
    # Lege rijen verwijderen
    # --------------------------------------------------------

    df = df.dropna(
        how="all"
    )

    # --------------------------------------------------------
    # Lege kolommen verwijderen
    # --------------------------------------------------------

    df = df.dropna(
        axis=1,
        how="all"
    )

    if df.empty:

        raise ValueError(
            f"Werkblad '{sheet_name}' "
            f"bevat geen gegevens."
        )

    # --------------------------------------------------------
    # Weekkolom zoeken
    # --------------------------------------------------------

    week_column = find_week_column(
        df.columns
    )

    logger.debug(
        "Werkblad '%s', kolommen: %s",
        sheet_name,
        list(df.columns),
    )

    # --------------------------------------------------------
    # Geen week gevonden
    # --------------------------------------------------------

    if week_column is None:

        raise ValueError(
            f"Geen weekkolom gevonden in "
            f"'{sheet_name}'. "
            f"Kolommen: {list(df.columns)}"
        )

    logger.debug(
        "Werkblad '%s', weekkolom: %s",
        sheet_name,
        week_column,
    )

    # ========================================================
    # NIEUWE DATAFRAME
    # ========================================================

    normalized = pd.DataFrame(
        index=df.index
    )

    # --------------------------------------------------------
    # WEEK NORMALISEREN
    # --------------------------------------------------------

    normalized["week"] = (
        df[week_column]
        .apply(clean_week)
        .astype("Int64")
    )

    # ========================================================
    # ALLE ANDERE KOLOMMEN BEWAREN
    # ========================================================

    for original_column in df.columns:

        # Week hebben we al verwerkt
        if original_column == week_column:
            continue

        # --------------------------------------------
        # Kolomnaam schoonmaken
        # --------------------------------------------

        new_column_name = (
            make_safe_column_name(
                original_column
            )
        )

        # Geen bruikbare naam?
        if not new_column_name:
            continue

        # --------------------------------------------
        # Dubbele namen voorkomen
        # --------------------------------------------

        new_column_name = (
            make_unique_column_name(
                new_column_name,
                normalized.columns
            )
        )

        # --------------------------------------------
        # Data toevoegen
        # --------------------------------------------

        normalized[
            new_column_name
        ] = (
            df[original_column]
            .apply(clean_text)
        )

    # --------------------------------------------------------
    # BRON TOEVOEGEN
    # --------------------------------------------------------

    normalized["bron"] = (
        sheet_name
    )

    # --------------------------------------------------------
    # RIJEN ZONDER GELDIGE WEEK VERWIJDEREN
    # --------------------------------------------------------

    rows_before = len(
        normalized
    )

    normalized = (
        normalized.dropna(
            subset=["week"]
        )
    )

    rows_after = len(
        normalized
    )

    removed_rows = (
        rows_before
        - rows_after
    )

    logger.info(
        "Werkblad '%s': %s geldige regels",
        sheet_name,
        rows_after,
    )

    if removed_rows > 0:

        logger.info(
            "Werkblad '%s': %s regels zonder weeknummer overgeslagen",
            sheet_name,
            removed_rows,
        )

    return (
        normalized.reset_index(
            drop=True
        )
    )


# ============================================================
# EXCEL-BESTAND LEZEN
# ============================================================

def lees_evenementen(
    file_path
):
    """
    Leest alle werkbladen.

    Alleen de weekkolom is verplicht.

    Andere kolommen mogen per werkblad volledig verschillen.
    """

    file_path = Path(
        file_path
    )

    # --------------------------------------------------------
    # Bestaat bestand?
    # --------------------------------------------------------

    if not file_path.exists():

        raise FileNotFoundError(
            f"Excel-bestand niet gevonden: "
            f"{file_path}"
        )

    # --------------------------------------------------------
    # Excel openen
    # --------------------------------------------------------

    sheets = pd.read_excel(
        file_path,
        sheet_name=None,
        engine="openpyxl"
    )

    logger.info(
        "Excel geladen: %s (%s werkbladen)",
        file_path.name,
        len(sheets),
    )

    normalized_sheets = []

    fouten = []

    # ========================================================
    # ALLE SHEETS VERWERKEN
    # ========================================================

    for sheet_name, df in sheets.items():

        try:

            normalized = (
                normalize_sheet(
                    df,
                    sheet_name
                )
            )

            if not normalized.empty:

                normalized_sheets.append(
                    normalized
                )

        except Exception as error:

            fouten.append(
                {
                    "tabel": sheet_name,
                    "fout": str(error)
                }
            )

    # ========================================================
    # GEEN GELDIGE SHEETS
    # ========================================================

    if not normalized_sheets:

        return (
            [],
            fouten
        )

    # ========================================================
    # SHEETS COMBINEREN
    # ========================================================

    result = pd.concat(
        normalized_sheets,
        ignore_index=True,
        sort=False
    )

    # ========================================================
    # SORTEREN OP WEEK
    # ========================================================

    result["_week_sort"] = (
        pd.to_numeric(
            result["week"],
            errors="coerce"
        )
    )

    result = (
        result.sort_values(
            by="_week_sort",
            na_position="last"
        )
    )

    result = result.drop(
        columns=[
            "_week_sort"
        ]
    )

    result = (
        result.reset_index(
            drop=True
        )
    )

    # ========================================================
    # DATAFRAME -> LIST OF DICTS
    # ========================================================

    evenementen = (
        result.to_dict(
            orient="records"
        )
    )

    return (
        evenementen,
        fouten
    )