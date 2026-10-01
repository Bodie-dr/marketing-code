import socket
import unittest
from unittest.mock import MagicMock, patch

import requests

import app
import web_reader


def _openbaar_adres(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def _antwoord(status=200, soort="text/html; charset=utf-8", inhoud=b"", headers=None):
    antwoord = MagicMock()
    antwoord.status_code = status
    antwoord.is_redirect = status in {301, 302, 303, 307, 308}
    antwoord.headers = {"Content-Type": soort, **(headers or {})}
    antwoord.encoding = "utf-8"
    antwoord.apparent_encoding = "utf-8"
    antwoord.iter_content.return_value = [inhoud]
    antwoord.__enter__.return_value = antwoord
    return antwoord


PAGINA = b"""
<html><head><title>Nieuwe monteur gezocht</title><script>var x = 1;</script></head>
<body>
  <nav>Home | Over ons | Contact</nav>
  <main>
    <h1>Nieuwe monteur gezocht</h1>
    <p>Wij zoeken een ervaren monteur voor onze projecten in de regio Eindhoven.</p>
    <p>Je werkt aan installaties in ziekenhuizen en kantoren, samen met een vast team.</p>
    <ul><li>Vast contract</li><li>Eigen bus</li></ul>
  </main>
  <footer>Copyright 2026</footer>
</body></html>
"""


class HtmlNaarTekstTests(unittest.TestCase):
    def test_hoofdinhoud_zonder_menu_en_scripts(self):
        tekst = web_reader.html_naar_tekst(PAGINA.decode())
        self.assertIn("ervaren monteur", tekst)
        self.assertIn("Eigen bus", tekst)
        self.assertNotIn("Over ons", tekst)
        self.assertNotIn("var x", tekst)
        self.assertNotIn("Copyright", tekst)
        self.assertEqual(tekst.count("Nieuwe monteur gezocht"), 1)

    def test_zonder_main_wordt_hele_body_gebruikt(self):
        tekst = web_reader.html_naar_tekst("<body><p>Alinea een.</p><p>Alinea twee.</p></body>")
        self.assertEqual(tekst, "Alinea een.\n\nAlinea twee.")


class ControleerUrlTests(unittest.TestCase):
    def test_https_wordt_aangevuld(self):
        with patch.object(web_reader.socket, "getaddrinfo", _openbaar_adres):
            self.assertEqual(web_reader.controleer_url("tvb.eu/nieuws"), "https://tvb.eu/nieuws")

    def test_ander_protocol_geweigerd(self):
        with self.assertRaises(ValueError):
            web_reader.controleer_url("ftp://tvb.eu/bestand")

    def test_interne_adressen_geweigerd(self):
        for adres in ("127.0.0.1", "10.0.0.5", "192.168.1.10", "169.254.169.254"):
            uitkomst = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (adres, 0))]
            with patch.object(web_reader.socket, "getaddrinfo", return_value=uitkomst):
                with self.assertRaises(ValueError, msg=adres):
                    web_reader.controleer_url("http://intern.local")


class LeesWebpaginaTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(web_reader.socket, "getaddrinfo", _openbaar_adres)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pagina_wordt_tekst(self):
        with patch.object(web_reader.requests, "get", return_value=_antwoord(inhoud=PAGINA)):
            tekst = web_reader.lees_webpagina("https://tvb.eu/vacature")
        self.assertIn("ervaren monteur", tekst)

    def test_doorverwijzing_naar_intern_adres_geweigerd(self):
        doorverwijzing = _antwoord(status=302, headers={"Location": "http://127.0.0.1/admin"})
        intern = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
        with patch.object(web_reader.requests, "get", return_value=doorverwijzing), patch.object(
            web_reader.socket, "getaddrinfo", side_effect=[_openbaar_adres(), intern]
        ):
            with self.assertRaises(ValueError):
                web_reader.lees_webpagina("https://tvb.eu/link")

    def test_geblokkeerde_site_geeft_uitleg(self):
        with patch.object(web_reader.requests, "get", return_value=_antwoord(status=403)):
            with self.assertRaisesRegex(ValueError, "plak"):
                web_reader.lees_webpagina("https://tvb.eu/afgeschermd")

    def test_pdf_link_verwijst_naar_upload(self):
        with patch.object(
            web_reader.requests, "get", return_value=_antwoord(soort="application/pdf")
        ):
            with self.assertRaisesRegex(ValueError, "Upload"):
                web_reader.lees_webpagina("https://tvb.eu/brochure.pdf")

    def test_timeout_geeft_uitleg(self):
        with patch.object(web_reader.requests, "get", side_effect=requests.Timeout()):
            with self.assertRaisesRegex(ValueError, "reageert niet"):
                web_reader.lees_webpagina("https://tvb.eu/traag")


class AppKoppelingTests(unittest.TestCase):
    def test_webtekst_gaat_als_bestaande_tekst_naar_model(self):
        with patch.object(app, "lees_webpagina", return_value="Tekst van de site"), patch.object(
            app, "generate_text", return_value="Resultaat"
        ) as genereer, patch.object(app, "save_generated_word", return_value=None), patch.object(
            app.gr, "Info"
        ):
            updates = app.validate_and_generate(
                None, "", "", "Tekst herschrijven", "", "", "", "", "LinkedIn",
                "https://tvb.eu/nieuws",
            )
            self.assertEqual(next(updates), ("Resultaat", None))
        self.assertEqual(genereer.call_args.kwargs["style_text"], "Tekst van de site")

    def test_fout_bij_ophalen_wordt_melding(self):
        with patch.object(app, "lees_webpagina", side_effect=ValueError("Deze pagina bestaat niet")):
            updates = app.validate_and_generate(
                None, "", "", "Tekst herschrijven", "", "", "", "", "LinkedIn",
                "https://tvb.eu/weg",
            )
            with self.assertRaisesRegex(app.gr.Error, "bestaat niet"):
                next(updates)

    def test_link_zet_modus_op_herschrijven(self):
        self.assertEqual(app.update_modus_from_bron("", "https://tvb.eu"), "Tekst herschrijven")
        self.assertEqual(app.update_modus_from_bron("", ""), "Nieuwe tekst genereren")


if __name__ == "__main__":
    unittest.main()
