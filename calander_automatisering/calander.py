from pathlib import Path

from excel_normalizer import lees_evenementen


EXCEL_FILE = Path(
    r"C:\Bodie\marketing code"
    r"\calander_automatisering"
    r"\Jaarplanning social media 2026.xlsx"
)


def print_evenementen(evenementen):
    print("\n====================================")
    print("EVENEMENTEN")
    print("====================================")

    if not evenementen:
        print("Geen evenementen gevonden.")
        return

    for evenement in evenementen:

        print(
            "\n"
            f"Week: {evenement.get('week')}\n"
            f"Dag: {evenement.get('dag')}\n"
            f"Activiteit: {evenement.get('activiteit')}\n"
            f"Soort content: {evenement.get('soort_content')}\n"
            f"Post content: {evenement.get('post_content')}\n"
            f"Kanaal: {evenement.get('kanaal')}\n"
            f"Bron: {evenement.get('bron')}"
        )


def main():
    try:

        evenementen, fouten = lees_evenementen(
            EXCEL_FILE
        )

        print(
            f"\nAantal evenementen: "
            f"{len(evenementen)}"
        )

        print_evenementen(
            evenementen
        )

        if fouten:

            print("\n====================================")
            print("NIET HERKENDE WERKBLADEN")
            print("====================================")

            for fout in fouten:

                print(
                    f"{fout['tabel']}: "
                    f"{fout['fout']}"
                )

    except FileNotFoundError as error:
        print(
            f"Bestandsfout: {error}"
        )

    except Exception as error:
        print(
            f"Onverwachte fout: {error}"
        )


if __name__ == "__main__":
    main()