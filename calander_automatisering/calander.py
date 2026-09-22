import pandas as pd
from pathlib import Path


def lees_evenementen(file_path):
    """
    Leest alle werkbladen uit het Excel-bestand
    en haalt de gegevens per rij op.

    Verwachte kolommen zijn ongeveer:
    Week | Soort content | Post content | Dag | Activiteit | Kanaal
    """

    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"Excel-bestand niet gevonden: {file_path}"
        )

    # Lees alle werkbladen
    sheets = pd.read_excel(
        file_path,
        sheet_name=None,
        engine="openpyxl"
    )

    evenementen = []

    for sheet_name, df in sheets.items():

        # Kolomnamen opschonen
        df.columns = [
            str(column).strip().lower()
            for column in df.columns
        ]

        for _, row in df.iterrows():

            evenement = {
                "week": row.get("week"),
                "soort_content": row.get("soort content"),
                "post_content": row.get("post content"),
                "dag": row.get("dag"),
                "activiteit": row.get("activiteit"),
                "kanaal": row.get("kanaal"),
                "bron": sheet_name,
            }

            # Alleen regels toevoegen waar daadwerkelijk
            # een activiteit staat
            if pd.notna(evenement["activiteit"]):
                evenementen.append(evenement)

    return evenementen


if __name__ == "__main__":

    excel_file = (
        r"C:\Bodie\marketing code\calander_automatisering"
        r"\Jaarplanning social media 2026.xlsx"
    )

    evenementen = lees_evenementen(excel_file)

    print(f"Aantal evenementen: {len(evenementen)}")

    for evenement in evenementen:
        print(evenement)
        