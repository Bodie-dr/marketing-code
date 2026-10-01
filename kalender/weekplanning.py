"""Posts per week selecteren en tonen."""

from datetime import date, timedelta

import pandas as pd

from planning_posts import MAANDEN, Post


ALLE_BEDRIJVEN = "Alle bedrijven"


def bedrijven_in_planning(posts: list[Post]) -> list[str]:
    return sorted({post.bedrijf for post in posts}, key=str.casefold)


def filter_bedrijf(posts: list[Post], bedrijf: str | None) -> list[Post]:
    """Filter op bedrijfsnaam of werkbladnaam (bijv. 'TTI'); leeg = alles."""
    if not bedrijf or bedrijf == ALLE_BEDRIJVEN:
        return posts
    gezocht = bedrijf.strip().casefold()
    return [
        post for post in posts
        if gezocht in {post.bedrijf.casefold(), post.bron.casefold()}
    ]


def maandag_van(datum: date) -> date:
    return datum - timedelta(days=datum.weekday())


def posts_in_periode(posts: list[Post], vanaf: date, weken: int = 1) -> list[Post]:
    """Posts vanaf de maandag van de week van `vanaf`, voor `weken` weken."""
    start = maandag_van(vanaf)
    eind = start + timedelta(weeks=max(weken, 1))
    return [post for post in posts if start <= post.datum < eind]


def week_label(maandag: date) -> str:
    """Bijvoorbeeld: 'Week 41 · 5 okt – 11 okt 2026'."""
    zondag = maandag + timedelta(days=6)
    week = maandag.isocalendar().week
    return (
        f"Week {week} · {maandag.day} {MAANDEN[maandag.month - 1]} – "
        f"{zondag.day} {MAANDEN[zondag.month - 1]} {zondag.year}"
    )


def weken_in_planning(posts: list[Post]) -> list[tuple[str, str]]:
    """Keuzelijst (label, maandag als ISO-datum) van alle weken met posts."""
    maandagen = sorted({maandag_van(post.datum) for post in posts})
    return [(week_label(maandag), maandag.isoformat()) for maandag in maandagen]


def standaard_week(posts: list[Post], vandaag: date | None = None) -> str | None:
    """Deze week als die posts heeft, anders de eerstvolgende week met posts."""
    huidige = maandag_van(vandaag or date.today())
    maandagen = sorted({maandag_van(post.datum) for post in posts})
    for maandag in maandagen:
        if maandag >= huidige:
            return maandag.isoformat()
    return maandagen[-1].isoformat() if maandagen else None


def posts_tabel(posts: list[Post]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Datum": post.datum_tekst,
                "Bedrijf": post.bedrijf,
                "Kanaal": post.kanaal,
                "Onderwerp": post.onderwerp or "",
                "Soort content": post.soort_content or "",
                "Bijzonderheden": post.bijzonderheden or "",
            }
            for post in posts
        ],
        columns=["Datum", "Bedrijf", "Kanaal", "Onderwerp", "Soort content", "Bijzonderheden"],
    )


def print_weekoverzicht(posts: list[Post], vanaf: date, weken: int = 1) -> None:
    """Wat moet er deze week de deur uit?"""
    geselecteerd = posts_in_periode(posts, vanaf, weken)
    start = maandag_van(vanaf)

    for week_nummer in range(max(weken, 1)):
        maandag = start + timedelta(weeks=week_nummer)
        week_posts = posts_in_periode(geselecteerd, maandag, 1)

        print()
        print("=" * 60)
        print(week_label(maandag).upper())
        print("=" * 60)

        if not week_posts:
            print("Geen posts gepland.")
            continue

        for post in week_posts:
            onderwerp = " / ".join(
                deel for deel in [post.onderwerp, post.soort_content] if deel
            )
            print(f"  {post.datum_tekst:<28} {post.bedrijf:<32} {post.kanaal:<20} {onderwerp}")
            if post.bijzonderheden:
                print(f"  {'':<28} ↳ {post.bijzonderheden}")
