"""Leesbare tekst ophalen van een webpagina, zodat de AI die kan herschrijven."""

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

TIMEOUT = 15
MAX_BYTES = 3 * 1024 * 1024
MAX_REDIRECTS = 5
# Langere pagina's worden ingekort; meer heeft het model niet nodig.
MAX_TEKENS = 20000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
    "Accept-Language": "nl,en;q=0.8",
}

# Onderdelen van een pagina die geen inhoud zijn.
OVERSLAAN = {
    "script", "style", "noscript", "template", "svg", "iframe", "form",
    "nav", "header", "footer", "aside", "button", "select",
}
# Na deze elementen begint een nieuwe regel.
BLOKKEN = {
    "p", "div", "section", "article", "main", "br", "li", "ul", "ol",
    "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "blockquote", "figcaption",
}
# Void-elementen hebben geen sluittag en mogen de teller niet verhogen.
ZONDER_SLUITTAG = {"br", "img", "input", "meta", "link", "hr", "source", "wbr"}


class _TekstParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.overslaan = 0
        self.in_hoofdinhoud = 0
        self.in_titel = False
        self.titel = ""
        self.alle_tekst = []
        self.hoofdinhoud = []

    def handle_starttag(self, tag, attrs):
        if tag in ZONDER_SLUITTAG:
            if tag == "br":
                self._nieuwe_regel()
            return
        if tag in OVERSLAAN:
            self.overslaan += 1
        elif tag in {"main", "article"}:
            self.in_hoofdinhoud += 1
        elif tag == "title":
            self.in_titel = True
        if tag in BLOKKEN:
            self._nieuwe_regel()

    def handle_endtag(self, tag):
        if tag in OVERSLAAN:
            self.overslaan = max(0, self.overslaan - 1)
        elif tag in {"main", "article"}:
            self.in_hoofdinhoud = max(0, self.in_hoofdinhoud - 1)
        elif tag == "title":
            self.in_titel = False
        if tag in BLOKKEN:
            self._nieuwe_regel()

    def handle_data(self, data):
        if self.in_titel:
            self.titel += data
            return
        if self.overslaan:
            return
        self.alle_tekst.append(data)
        if self.in_hoofdinhoud:
            self.hoofdinhoud.append(data)

    def _nieuwe_regel(self):
        self.alle_tekst.append("\n")
        if self.in_hoofdinhoud:
            self.hoofdinhoud.append("\n")


def _opschonen(delen):
    regels = []
    for regel in "".join(delen).splitlines():
        regel = re.sub(r"\s+", " ", regel).strip()
        if regel:
            regels.append(regel)
    return "\n\n".join(regels)


def html_naar_tekst(html):
    """Haal de leesbare tekst uit HTML; <main>/<article> gaat voor als die er is."""
    parser = _TekstParser()
    parser.feed(html)
    parser.close()

    hoofdinhoud = _opschonen(parser.hoofdinhoud)
    tekst = hoofdinhoud if len(hoofdinhoud) >= 200 else _opschonen(parser.alle_tekst)
    titel = re.sub(r"\s+", " ", parser.titel).strip()
    if titel and not tekst.startswith(titel):
        tekst = f"{titel}\n\n{tekst}"
    return tekst


def controleer_url(url):
    """Geef een nette URL terug, of een ValueError met uitleg voor de gebruiker."""
    url = (url or "").strip()
    if url and "://" not in url:
        url = f"https://{url}"
    onderdelen = urlparse(url)
    if onderdelen.scheme not in {"http", "https"} or not onderdelen.hostname:
        raise ValueError("Dit is geen geldige link. Begin met https://")

    # De app kan openbaar gedeeld zijn: laat hem niet bij interne servers komen.
    try:
        adressen = {info[4][0] for info in socket.getaddrinfo(onderdelen.hostname, None)}
    except socket.gaierror as fout:
        raise ValueError(
            f"De website {onderdelen.hostname} is niet gevonden. Controleer de link."
        ) from fout
    for adres in adressen:
        ip = ipaddress.ip_address(adres.split("%")[0])
        if not ip.is_global:
            raise ValueError("Links naar interne of lokale adressen worden niet opgehaald.")
    return url


def lees_webpagina(url):
    """Haal een webpagina op en geef de leesbare tekst terug."""
    huidige_url = controleer_url(url)

    try:
        for _ in range(MAX_REDIRECTS + 1):
            antwoord = requests.get(
                huidige_url,
                headers=HEADERS,
                timeout=TIMEOUT,
                stream=True,
                allow_redirects=False,
            )
            if antwoord.is_redirect:
                # Elke doorverwijzing opnieuw controleren op interne adressen.
                huidige_url = controleer_url(urljoin(huidige_url, antwoord.headers["Location"]))
                antwoord.close()
                continue
            break
        else:
            raise ValueError("De link verwijst te vaak door. Plak de uiteindelijke link.")

        with antwoord:
            if antwoord.status_code in {401, 403}:
                raise ValueError(
                    "Deze website laat de pagina niet automatisch ophalen. "
                    "Kopieer de tekst en plak hem in het tekstveld."
                )
            if antwoord.status_code == 404:
                raise ValueError("Deze pagina bestaat niet (404). Controleer de link.")
            if antwoord.status_code >= 400:
                raise ValueError(
                    f"De website gaf een foutmelding ({antwoord.status_code}). "
                    "Probeer het later opnieuw of plak de tekst zelf."
                )

            soort = antwoord.headers.get("Content-Type", "").lower()
            if "html" not in soort and "text/plain" not in soort:
                raise ValueError(
                    "Deze link is geen webpagina. Upload een bestand (zoals een pdf) "
                    "via het uploadveld."
                )

            inhoud = b""
            for blok in antwoord.iter_content(64 * 1024):
                inhoud += blok
                if len(inhoud) > MAX_BYTES:
                    raise ValueError("Deze pagina is te groot om op te halen.")

            codering = antwoord.encoding if "charset" in soort else antwoord.apparent_encoding
            html = inhoud.decode(codering or "utf-8", errors="replace")
    except requests.Timeout as fout:
        raise ValueError("De website reageert niet. Probeer het later opnieuw.") from fout
    except requests.RequestException as fout:
        raise ValueError("De pagina kon niet worden opgehaald. Controleer de link.") from fout

    tekst = html if "text/plain" in soort else html_naar_tekst(html)
    if len(tekst) < 50:
        raise ValueError(
            "Op deze pagina staat geen leesbare tekst. Sommige websites laden hun "
            "tekst pas in de browser; kopieer de tekst dan en plak hem in het tekstveld."
        )
    return tekst[:MAX_TEKENS]
