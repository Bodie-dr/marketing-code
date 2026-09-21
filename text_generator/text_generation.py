import os
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI

load_dotenv(Path(__file__).with_name(".env"), override=True)
from database import (
    create_connection,
)
from config import EMBEDDING_MODEL_NAME, PROJECT_NAME


def zoek_relevante_data(
    opdracht: str,
    bedrijf: str = "",
    aantal: int = 5,
) -> str:
    """Zoek de meest relevante opgeslagen documentchunks voor de opdracht."""
    from embedding_service import EmbeddingService

    embedding_service = EmbeddingService()
    zoekopdracht = f"Bedrijf: {bedrijf}\nOpdracht: {opdracht}" if bedrijf else opdracht
    query_embedding = embedding_service.create_embeddings([zoekopdracht])[0]
    connection = create_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT dc.content, e.embedding
                FROM document_chunks AS dc
                JOIN document_versions AS dv ON dv.id = dc.version_id
                JOIN documents AS d ON d.id = dv.document_id
                JOIN projects AS p ON p.id = d.project_id
                JOIN embeddings AS e ON e.chunk_id = dc.id
                WHERE p.name = %s
                  AND d.is_active = TRUE
                  AND dv.version_number = d.current_version
                  AND e.model_name = %s
                """,
                (PROJECT_NAME, EMBEDDING_MODEL_NAME),
            )
            resultaten = cursor.fetchall()
    finally:
        connection.close()

    query_vector = np.asarray(query_embedding, dtype=np.float32)
    query_norm = np.linalg.norm(query_vector)
    scored_results = []

    for content, embedding_bytes in resultaten:
        stored_vector = np.frombuffer(
            embedding_bytes,
            dtype=np.float32,
        )
        stored_norm = np.linalg.norm(stored_vector)

        if query_norm == 0 or stored_norm == 0:
            distance = float("inf")
        else:
            similarity = np.dot(query_vector, stored_vector) / (
                query_norm * stored_norm
            )
            distance = 1 - float(similarity)

        scored_results.append((distance, content))

    scored_results.sort(key=lambda result: result[0])
    return "\n\n---\n\n".join(
        content
        for _, content in scored_results[:aantal]
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

    endpoint = endpoint.strip().rstrip("/")

    if endpoint.endswith("/openai/v1"):
        client = OpenAI(
            api_key=api_key.strip(),
            base_url=f"{endpoint}/",
        )
    else:
        client = AzureOpenAI(
            api_key=api_key.strip(),
            azure_endpoint=endpoint,
            api_version=os.getenv(
                "AZURE_OPENAI_API_VERSION",
                "2024-10-21",
            ),
        )

    documenttekst = lees_document(document) or style_text.strip()
    opgeslagen_data = zoek_relevante_data(nieuwe_opdracht, bedrijf)
    extra_instructie = prompt.strip() or (
        "Volg de stijl en structuur uit het document of de stijltekst."
    )
    aanleiding = aanleiding.strip() or "Niet opgegeven"
    insteek = insteek.strip() or "Niet opgegeven"
    doelgroep = doelgroep.strip() or "Niet opgegeven"
    bedrijf = bedrijf.strip() or "Niet opgegeven"
    kanaal = kanaal.strip() or "LinkedIn"

    taak_instructie = """
Maak een volledig originele tekst. Gebruik de ingevoerde tekst alleen als
achtergrond en inspiratie voor het onderwerp; kopieer of herschrijf die tekst
niet letterlijk en neem geen bronopdracht over in je antwoord.

- Gebruik de stijl, structuur, formaliteit, het detailniveau en de vaktermen
    uit de trainingsvoorbeelden en het document.
- Verzin geen feiten, namen of aantallen die niet in de achtergrondinformatie
    of uitgangspunten staan.
- Geef alleen de nieuwe tekst terug.
"""

    model_prompt = f"""
Je schrijft originele teksten voor een aannemersbedrijf in de bouw.

Gebruik de trainingsvoorbeelden en het geuploade document of de stijltekst als
belangrijkste bron voor schrijfstijl, structuur, formele toon, vaktermen en de
manier waarop werkzaamheden worden beschreven.

OPGESLAGEN DATA UIT DE KENNISBANK:
--------------------
{opgeslagen_data or "Geen relevante opgeslagen data gevonden."}
--------------------

EXTRA DOCUMENT:
--------------------
{documenttekst or "Geen extra document geupload."}
--------------------

Extra instructie van de gebruiker:
{extra_instructie}

Inhoudelijke uitgangspunten:
- Aanleiding: {aanleiding}
- Insteek: {insteek}
- Doelgroep: {doelgroep}
- Bedrijf: {bedrijf}
- Publicatiekanaal: {kanaal}

Zoek in de opgeslagen data en het extra document naar de tone of voice en
kernwaarden van het genoemde bedrijf. Pas die toe op de tekst en stem de
vorm, lengte en stijl af op het publicatiekanaal.

{taak_instructie}

Geef alleen de gegenereerde tekst terug.

Achtergrondinformatie voor de nieuwe tekst:
{nieuwe_opdracht}
"""

    response = client.chat.completions.create(
        model=deployment.strip(),
        messages=[
            {
                "role": "system",
                "content": (
                    "Je bent een specialist in het schrijven "
                    "van factuurteksten voor aannemersbedrijven."
                ),
            },
            {
                "role": "user",
                "content": model_prompt,
            },
        ],
    )

    return response.choices[0].message.content.strip()


