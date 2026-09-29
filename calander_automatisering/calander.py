"""Social-media jaarplanning: overzicht, agenda-export en concepten.

"""

import argparse
import logging
from datetime import date, timedelta
from pathlib import Path

from agenda_export import schrijf_ics
from planning_posts import (
    PROJECT_DIR,
    lees_posts,
    posts_naar_dataframe,
    standaard_excel_bestand,
)
from weekplanning import (
    bedrijven_in_planning,
    filter_bedrijf,
    maandag_van,
    posts_in_periode,
    print_weekoverzicht,
)


# ============================================================
# INSTELLINGEN
# ============================================================

# Zet CALENDAR_EXCEL_FILE in .env om direct de versie op OneDrive te lezen.
EXCEL_FILE = standaard_excel_bestand()

OUTPUT_DIR = PROJECT_DIR / "outputs" / "kalender"


# ============================================================
# WAARDE NETJES WEERGEVEN
# ============================================================

def format_value(value):
    """
    Maakt lege waarden netjes leesbaar.
    """

    if value is None:
        return "-"

    value = str(value).strip()

    return value or "-"


# ============================================================
# POSTS TONEN
# ============================================================

def print_posts(posts):
    """
    Toont één regel per post, gesorteerd op datum.
    """

    print("\n====================================")
    print(f"POSTS ({len(posts)})")
    print("====================================")

    if not posts:
        print("Geen posts gevonden.")
        return

    for post in posts:
        regel = (
            f"{post.datum_tekst:<28} | "
            f"{post.bedrijf:<32} | "
            f"{post.kanaal:<20} | "
            f"{format_value(post.onderwerp)} / "
            f"{format_value(post.soort_content)}"
        )
        if post.bijzonderheden:
            regel += f"  [{post.bijzonderheden}]"
        print(regel)


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
        print()
        print(f"Werkblad: {fout.get('tabel', 'Onbekend')}")
        print(f"Reden: {fout.get('fout', 'Onbekende fout')}")


# ============================================================
# EXPORT
# ============================================================

def export_csv(posts, excel_file):
    """
    Slaat de posts op als CSV die Excel direct goed opent.
    """

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"posts_{excel_file.stem}.csv"
    posts_naar_dataframe(posts).to_csv(
        output,
        sep=";",
        index=False,
        encoding="utf-8-sig",
    )
    return output


# ============================================================
# HOOFDPROGRAMMA
# ============================================================

def parse_arguments():
    parser = argparse.ArgumentParser(description="Social-media jaarplanning verwerken.")
    bedrijf_help = "Alleen dit bedrijf: naam of werkblad, bijvoorbeeld 'TVB' of 'TTI'."
    parser.add_argument("--excel", type=Path, default=EXCEL_FILE, help="Pad naar de jaarplanning.")
    parser.add_argument("--bedrijf", default=None, help=bedrijf_help)

    # --bedrijf mag ook ná de opdracht staan; SUPPRESS voorkomt dat de
    # subopdracht een eerder opgegeven waarde overschrijft met None.
    bedrijf_optie = argparse.ArgumentParser(add_help=False)
    bedrijf_optie.add_argument("--bedrijf", default=argparse.SUPPRESS, help=bedrijf_help)

    subparsers = parser.add_subparsers(dest="opdracht")

    week = subparsers.add_parser(
        "week", parents=[bedrijf_optie], help="Toon wat er deze week de deur uit moet."
    )
    week.add_argument("--vanaf", type=date.fromisoformat, default=date.today(), help="JJJJ-MM-DD")
    week.add_argument("--weken", type=int, default=1)

    subparsers.add_parser(
        "excel", parents=[bedrijf_optie], help="Exporteer posts als opgemaakt Excel-bestand."
    )

    subparsers.add_parser(
        "ics", parents=[bedrijf_optie], help="Exporteer posts als agenda (.ics) voor Outlook."
    )

    concepten = subparsers.add_parser(
        "concepten", parents=[bedrijf_optie], help="Maak Word-concepten met de tekstgenerator."
    )
    concepten.add_argument(
        "--vanaf",
        type=date.fromisoformat,
        default=maandag_van(date.today()) + timedelta(weeks=1),
        help="JJJJ-MM-DD (standaard: volgende week)",
    )
    concepten.add_argument("--weken", type=int, default=1)
    concepten.add_argument("--opnieuw", action="store_true", help="Bestaande concepten overschrijven.")

    return parser.parse_args()


def maak_concepten_opdracht(posts, arguments):
    from concepten import maak_concepten

    geselecteerd = posts_in_periode(posts, arguments.vanaf, arguments.weken)

    print_weekoverzicht(geselecteerd, arguments.vanaf, arguments.weken)
    if not geselecteerd:
        return

    print(f"\n{len(geselecteerd)} concept(en) maken (dit gebruikt Azure OpenAI)...")
    resultaten = maak_concepten(geselecteerd, opnieuw=arguments.opnieuw)

    print()
    for resultaat in resultaten:
        print(f"  [{resultaat.status}] {resultaat.pad}")
        if resultaat.fout:
            print(f"      fout: {resultaat.fout}")


def main():
    arguments = parse_arguments()

    try:
        print(f"Excel-bestand:\n{arguments.excel}")
        posts, fouten = lees_posts(arguments.excel)
        print_fouten(fouten)

        if arguments.bedrijf:
            alle_bedrijven = bedrijven_in_planning(posts)
            posts = filter_bedrijf(posts, arguments.bedrijf)
            if not posts:
                print(f"\nGeen posts voor bedrijf '{arguments.bedrijf}'. Kies uit:")
                for naam in alle_bedrijven:
                    print(f"  - {naam}")
                return
            print(f"Bedrijf: {posts[0].bedrijf}")

        if arguments.opdracht == "week":
            print_weekoverzicht(posts, arguments.vanaf, arguments.weken)

        elif arguments.opdracht == "excel":
            from excel_export import schrijf_excel

            achtervoegsel = f" - {posts[0].bedrijf}" if arguments.bedrijf else ""
            pad = schrijf_excel(posts, OUTPUT_DIR / f"planning{achtervoegsel}.xlsx")
            print(f"\n{len(posts)} posts geëxporteerd naar:\n{pad}")

        elif arguments.opdracht == "ics":
            achtervoegsel = f" - {posts[0].bedrijf}" if arguments.bedrijf else ""
            pad = schrijf_ics(posts, OUTPUT_DIR / f"{arguments.excel.stem}{achtervoegsel}.ics")
            print(f"\n{len(posts)} posts geëxporteerd naar:\n{pad}")
            print("Outlook: Bestand > Openen en exporteren > Importeren/exporteren > iCalendar (.ics).")

        elif arguments.opdracht == "concepten":
            maak_concepten_opdracht(posts, arguments)

        else:
            print_posts(posts)
            if posts and not arguments.bedrijf:
                print(f"\nCSV opgeslagen: {export_csv(posts, arguments.excel)}")

    except FileNotFoundError:
        print(f"Bestand niet gevonden: {arguments.excel}")
    except Exception as exc:
        print(f"Fout tijdens verwerken van het Excel-bestand: {exc}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # Geen regel per HTTP-aanroep naar Azure / Hugging Face.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    main()
