"""Exporteer posts als .ics-agenda die Outlook kan importeren."""

import hashlib
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from planning_posts import Post


def _escape(tekst: str) -> str:
    return (
        tekst.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _vouw(regel: str) -> list[str]:
    """Knip regels op 75 bytes, zoals de iCalendar-standaard voorschrijft."""
    delen = []
    huidig = ""
    for teken in regel:
        limiet = 75 if not delen else 74  # vervolgregels beginnen met een spatie
        if len((huidig + teken).encode("utf-8")) > limiet:
            delen.append(huidig)
            huidig = teken
        else:
            huidig += teken
    delen.append(huidig)
    return [delen[0]] + [" " + deel for deel in delen[1:]]


def _uid(post: Post, volgnummer: int) -> str:
    # Stabiel bij opnieuw exporteren, zodat Outlook afspraken bijwerkt in
    # plaats van dubbel toevoegt (zolang datum en kanaal gelijk blijven).
    sleutel = f"{post.bron}|{post.datum.isoformat()}|{post.kanaal}|{volgnummer}"
    return f"{hashlib.sha1(sleutel.encode('utf-8')).hexdigest()}@tvb-marketing"


def posts_naar_ics(posts: list[Post], nu: datetime | None = None) -> str:
    tijdstempel = (nu or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    regels = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TVB Marketing//Jaarplanning social media//NL",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Social media planning",
    ]

    tellers = Counter()
    for post in posts:
        sleutel = (post.bron, post.datum, post.kanaal)
        tellers[sleutel] += 1

        if post.dag_bekend:
            start, eind = post.datum, post.datum + timedelta(days=1)
            dag_opmerking = ""
        else:
            # Geen vaste dag: toon de post over de hele werkweek.
            start, eind = post.datum, post.datum + timedelta(days=5)
            dag_opmerking = " (dag vrij)"

        titel = post.onderwerp or post.soort_content or "Post"
        omschrijving = "\n".join(
            regel
            for regel in [
                f"Bedrijf: {post.bedrijf}",
                f"Kanaal: {post.kanaal}",
                f"Onderwerp: {post.onderwerp}" if post.onderwerp else "",
                f"Soort content: {post.soort_content}" if post.soort_content else "",
                f"Bijzonderheden: {post.bijzonderheden}" if post.bijzonderheden else "",
            ]
            if regel
        )

        regels += [
            "BEGIN:VEVENT",
            f"UID:{_uid(post, tellers[sleutel])}",
            f"DTSTAMP:{tijdstempel}",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{eind:%Y%m%d}",
            f"SUMMARY:{_escape(f'{post.bedrijf} – {post.kanaal}: {titel}{dag_opmerking}')}",
            f"DESCRIPTION:{_escape(omschrijving)}",
            f"CATEGORIES:{_escape(post.bedrijf)}",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ]

    regels.append("END:VCALENDAR")
    return "\r\n".join(deel for regel in regels for deel in _vouw(regel)) + "\r\n"


def schrijf_ics(posts: list[Post], pad: Path) -> Path:
    pad = Path(pad)
    pad.parent.mkdir(parents=True, exist_ok=True)
    pad.write_bytes(posts_naar_ics(posts).encode("utf-8"))
    return pad
