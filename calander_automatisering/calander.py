from pathlib import Path

from excel_normalizer import lees_evenementen


# ============================================================
# INSTELLINGEN
# ============================================================

EXCEL_FILE = Path(
    r"C:\Bodie\marketing code"
    r"\calander_automatisering"
    r"\Jaarplanning social media 2026.xlsx"
)


# ============================================================
# WAARDE NETJES WEERGEVEN
# ============================================================

def format_value(value):
    """
    Maakt lege waarden netjes leesbaar.
    """

    if value is None:
        return "-"

    try:
        if value != value:
            return "-"
    except (TypeError, ValueError):
        pass

    value = str(value).strip()

    if not value or value == "<NA>":
        return "-"

    return value


# ============================================================
# EVENEMENTEN TONEN
# ============================================================

def print_evenementen(evenementen):
    """
    Toont alle gegevens dynamisch.

    Alleen 'week' wordt als vaste kolom behandeld.
    Alle andere kolommen kunnen per werkblad verschillen.
    """

    print("\n====================================")
    print("EVENEMENTEN")
    print("====================================")

    if not evenementen:
        print("Geen evenementen gevonden.")
        return

    for nummer, evenement in enumerate(
        evenementen,
        start=1
    ):
        print()
        print("-" * 50)
        print(f"REGEL {nummer}")
        print("-" * 50)

        # ----------------------------------------------------
        # Week eerst tonen
        # ----------------------------------------------------

        print(
            f"Week: "
            f"{format_value(evenement.get('week'))}"
        )

        # ----------------------------------------------------
        # Daarna alle dynamische kolommen
        # ----------------------------------------------------

        for key, value in evenement.items():

            # Week hebben we al weergegeven
            if key == "week":
                continue

            # Mooie naam maken voor uitvoer
            display_name = (
                key
                .replace("_", " ")
                .capitalize()
            )

            print(
                f"{display_name}: "
                f"{format_value(value)}"
            )


# ============================================================
# FOUTEN TONEN
# ============================================================

def print_fouten(fouten):
    """
    Toont werkbladen die niet verwerkt konden worden.
    """

    if not fouten:
        return

    print()
    print("====================================")
    print("NIET HERKENDE WERKBLADEN")
    print("====================================")

    for fout in fouten:

        sheet_name = fout.get(
            "tabel",
            "Onbekend"
        )

        foutmelding = fout.get(
            "fout",
            "Onbekende fout"
        )

        print()
        print(
            f"Werkblad: {sheet_name}"
        )

        print(
            f"Reden: {foutmelding}"
        )


# ============================================================
# HOOFDPROGRAMMA
# ============================================================

def main():
    """
    Start het importproces.
    """

    try:

        print(
            f"Excel-bestand:\n"
            f"{EXCEL_FILE}"
        )

        # ----------------------------------------------------
        # Excel normaliseren
        # ----------------------------------------------------

        evenementen, fouten = lees_evenementen(EXCEL_FILE)

        print_evenementen(evenementen)
        print_fouten(fouten)

    except FileNotFoundError:
        print(f"Bestand niet gevonden: {EXCEL_FILE}")
    except Exception as exc:
        print(f"Fout tijdens verwerken van het Excel-bestand: {exc}")


if __name__ == "__main__":
    main()