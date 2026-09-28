import os
from pathlib import Path
from functools import lru_cache

import numpy as np
from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
from database import (
    create_connection,
)
from config import EMBEDDING_MODEL_NAME, PROJECT_NAME


@lru_cache(maxsize=32)
def _query_embedding(zoekopdracht: str):
    """Hergebruik alleen de zoekvector; haal kennisbankinhoud altijd opnieuw op."""
    from embedding_service import EmbeddingService

    return EmbeddingService().create_embeddings([zoekopdracht])[0]


# Submap per publicatiekanaal binnen elke bedrijfsmap.
KANAAL_MAPPEN = {
    "linkedin": "social_media_teksten",
    "instagram": "social_media_teksten",
    "website": "website_vacatuur_teksten",
}

# Maximale lengte van alle voorbeeldteksten samen in de prompt.
MAX_VOORBEELD_TEKENS = 15000


def _haal_documenten(connection, project_name=None, map_naam=None):
    """Haal actieve Word-documenten op met de embeddings van hun chunks."""
    query = """
        SELECT d.id, p.name, d.relative_path, dv.full_text, e.embedding
        FROM document_chunks AS dc
        JOIN document_versions AS dv ON dv.id = dc.version_id
        JOIN documents AS d ON d.id = dv.document_id
        JOIN projects AS p ON p.id = d.project_id
        JOIN embeddings AS e ON e.chunk_id = dc.id
        WHERE d.is_active = TRUE
          AND d.file_type = 'docx'
          AND dv.version_number = d.current_version
          AND e.model_name = %s
    """
    parameters = [EMBEDDING_MODEL_NAME]
    if project_name:
        query += " AND p.name = %s"
        parameters.append(project_name)
    if map_naam:
        query += " AND lower(d.relative_path) LIKE lower(%s)"
        parameters.append(f"{map_naam}/%")

    with connection.cursor() as cursor:
        cursor.execute(query, parameters)
        rows = cursor.fetchall()

    documenten = {}
    for document_id, bedrijfsnaam, pad, tekst, embedding in rows:
        document = documenten.setdefault(
            document_id,
            {"bedrijf": bedrijfsnaam, "pad": pad, "tekst": tekst, "vectoren": []},
        )
        document["vectoren"].append(np.frombuffer(embedding, dtype=np.float32))
    return list(documenten.values())


def _gelijkenis(query_vector, vectoren) -> float:
    """Hoogste cosinusgelijkenis tussen de zoekvraag en de chunks van een document."""
    query_norm = np.linalg.norm(query_vector)
    beste = -1.0
    for vector in vectoren:
        norm = np.linalg.norm(vector)
        if query_norm and norm:
            beste = max(beste, float(np.dot(query_vector, vector) / (query_norm * norm)))
    return beste


def zoek_relevante_data(
    opdracht: str,
    bedrijf: str = "",
    kanaal: str = "LinkedIn",
    aantal: int = 3,
) -> str:
    """Geef complete voorbeeldteksten uit de kennisbank terug.

    Volledige teksten (in plaats van losse fragmenten) laten het model de
    opbouw, lengte en tone of voice van echte publicaties overnemen. Teksten
    van het gekozen bedrijf uit de map van het kanaal gaan voor; heeft het
    bedrijf geen teksten, dan worden teksten van andere bedrijven voor
    hetzelfde kanaal gebruikt als voorbeeld van de opbouw.
    """
    if aantal <= 0:
        return ""
    project_name = bedrijf.strip() or PROJECT_NAME
    kanaal_map = KANAAL_MAPPEN.get(kanaal.strip().casefold())

    def in_kanaalmap(document):
        return bool(kanaal_map) and document["pad"].casefold().startswith(
            f"{kanaal_map}/".casefold()
        )

    connection = create_connection()
    try:
        documenten = _haal_documenten(connection, project_name=project_name)
        if kanaal_map and not any(in_kanaalmap(document) for document in documenten):
            documenten += [
                document
                for document in _haal_documenten(connection, map_naam=kanaal_map)
                if document["bedrijf"] != project_name
            ]
    finally:
        connection.close()

    if not documenten:
        return ""

    # Het zoekmodel is alleen nodig als er meer kandidaten zijn dan plekken.
    if len(documenten) > aantal:
        zoekopdracht = f"Bedrijf: {bedrijf}\nOpdracht: {opdracht}" if bedrijf else opdracht
        query_vector = np.asarray(_query_embedding(zoekopdracht), dtype=np.float32)
        for document in documenten:
            document["score"] = _gelijkenis(query_vector, document["vectoren"])
    documenten.sort(
        key=lambda document: (not in_kanaalmap(document), -document.get("score", 0.0))
    )

    blokken = []
    resterend = MAX_VOORBEELD_TEKENS
    for nummer, document in enumerate(documenten[:aantal], start=1):
        if resterend <= 0:
            break
        herkomst = (
            "" if document["bedrijf"] == project_name
            else " (ander bedrijf, alleen voor de opbouw)"
        )
        tekst = document["tekst"][:resterend]
        resterend -= len(tekst)
        blokken.append(
            f"### Voorbeeld {nummer}: {document['bedrijf']} - {document['pad']}{herkomst}\n\n{tekst}"
        )
    return "\n\n".join(blokken)


@lru_cache(maxsize=4)
def _openai_client(api_key: str, endpoint: str, api_version: str):
    """Hergebruik de client, zodat de HTTPS-verbinding open blijft tussen aanvragen."""
    if endpoint.endswith("/openai/v1"):
        return OpenAI(api_key=api_key, base_url=f"{endpoint}/")
    return AzureOpenAI(
        api_key=api_key,
        azure_endpoint=endpoint,
        api_version=api_version,
    )


def lees_document(document):
    """Lees tekst uit een uploadbestand of accepteer een platte stijltekst."""
    if not document:
        return ""

    if isinstance(document, str):
        if document.strip() and os.path.exists(document):
            bestandspad = Path(document)
            extensie = bestandspad.suffix.lower()

            if extensie in {".txt", ".md", ".csv"}:
                return bestandspad.read_text(encoding="utf-8")

            if extensie == ".pdf":
                from pypdf import PdfReader

                return "\n".join(
                    pagina.extract_text() or ""
                    for pagina in PdfReader(str(bestandspad)).pages
                )

            if extensie == ".docx":
                from docx import Document

                return "\n".join(
                    alinea.text
                    for alinea in Document(str(bestandspad)).paragraphs
                )

            raise ValueError("Gebruik een .txt, .md, .csv, .pdf of .docx-bestand.")

        if document.strip():
            return document.strip()

    return ""


def generate_text(
    nieuwe_opdracht: str,
    document=None,
    style_text="",
    prompt="",
    modus="Nieuwe tekst genereren",
    aanleiding="",
    insteek="",
    doelgroep="",
    bedrijf="",
    kanaal="LinkedIn",
):
    return genereer_factuurtekst(
        nieuwe_opdracht,
        document=document,
        style_text=style_text,
        prompt=prompt,
        modus=modus,
        aanleiding=aanleiding,
        insteek=insteek,
        doelgroep=doelgroep,
        bedrijf=bedrijf,
        kanaal=kanaal,
    )


def genereer_factuurtekst(
    nieuwe_opdracht: str,
    document=None,
    style_text="",
    prompt="",
    modus="Nieuwe tekst genereren",
    aanleiding="",
    insteek="",
    doelgroep="",
    bedrijf="",
    kanaal="LinkedIn",
):

    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

    if not api_key or not endpoint or not deployment:
        return (
            "Azure OpenAI-configuratie ontbreekt. Stel "
            "AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT en "
            "AZURE_OPENAI_DEPLOYMENT in."
        )

    client = _openai_client(
        api_key.strip(),
        endpoint.strip().rstrip("/"),
        os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
    )

    documenttekst = lees_document(document) or style_text.strip()
    opgeslagen_data = zoek_relevante_data(
        nieuwe_opdracht,
        bedrijf,
        kanaal,
    )
    extra_instructie = prompt.strip() or "Geen."
    aanleiding = aanleiding.strip() or "Niet opgegeven"
    insteek = insteek.strip() or "Niet opgegeven"
    doelgroep = doelgroep.strip() or "Niet opgegeven"
    bedrijf = bedrijf.strip() or "Niet opgegeven"
    kanaal = kanaal.strip() or "LinkedIn"

    if modus == "Tekst herschrijven":
        taak_instructie = """
Herschrijf de ORIGINELE TEKST hieronder in de stijl van de voorbeeldteksten.
Behoud de feitelijke inhoud en voeg geen nieuwe feiten toe.
"""
    else:
        taak_instructie = """
Schrijf een nieuwe tekst over de opdracht hieronder. Gebruik de ORIGINELE
TEKST (als die er is) alleen als inhoudelijke achtergrond.
"""

    if opgeslagen_data:
        voorbeelden = f"""
Hieronder staan echte, eerder gepubliceerde teksten. Dit is je belangrijkste
bron: de nieuwe tekst moet klinken alsof dezelfde schrijver hem heeft gemaakt.
Neem daaruit over:
- de tone of voice en aanspreekvorm (je/jij of u);
- de opbouw: openingszin, volgorde van onderdelen, tussenkopjes, opsommingen
  en de afsluiter met call-to-action;
- de lengte, zinslengte en typische formuleringen en vaktermen.
Neem GEEN feiten over die bij een ander onderwerp horen, zoals namen,
functies, projecten, salarissen of aantallen.

=== VOORBEELDTEKSTEN ===
{opgeslagen_data}
=== EINDE VOORBEELDTEKSTEN ===
"""
    else:
        voorbeelden = (
            "Er zijn geen voorbeeldteksten van dit bedrijf in de kennisbank. "
            "Schrijf in een heldere, persoonlijke toon."
        )

    originele_tekst = (
        f"=== ORIGINELE TEKST ===\n{documenttekst}\n=== EINDE ORIGINELE TEKST ==="
        if documenttekst
        else ""
    )

    model_prompt = f"""
{voorbeelden}

{originele_tekst}

OPDRACHT
- Bedrijf: {bedrijf}
- Publicatiekanaal: {kanaal}
- Aanleiding: {aanleiding}
- Insteek: {insteek}
- Doelgroep: {doelgroep}
- Extra instructie: {extra_instructie}

{taak_instructie}
Verzin geen feiten, namen of aantallen die niet in de opdracht of de originele
tekst staan. Geef alleen de tekst terug, zonder toelichting.
"""

    response = client.chat.completions.create(
        model=deployment.strip(),
        messages=[
            {
                "role": "system",
                "content": (
                    "Je bent de vaste copywriter van de bedrijven binnen "
                    "Technische Verenigde Bedrijven (TVB). Je schrijft "
                    "vacatureteksten en medewerkersverhalen voor website en "
                    "social media, precies in de stijl van de bestaande "
                    "teksten van het bedrijf."
                ),
            },
            {
                "role": "user",
                "content": model_prompt,
            },
        ],
    )

    return response.choices[0].message.content.strip()


