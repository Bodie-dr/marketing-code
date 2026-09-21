import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AzureOpenAI, OpenAI

load_dotenv(Path(__file__).with_name(".env"), override=True)
from database import (
    create_connection,
)
from config import EMBEDDING_MODEL_NAME, PROJECT_NAME
from embedding_service import EmbeddingService


def zoek_relevante_data(
    opdracht: str,
    bedrijf: str = "",
    aantal: int = 5,
) -> str:
    """Zoek de meest relevante opgeslagen documentchunks voor de opdracht."""
    embedding_service = EmbeddingService()
    zoekopdracht = f"Bedrijf: {bedrijf}\nOpdracht: {opdracht}" if bedrijf else opdracht
    query_embedding = embedding_service.create_embeddings([zoekopdracht])[0]
    connection = create_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT dc.content
                FROM document_chunks AS dc
                JOIN document_versions AS dv ON dv.id = dc.version_id
                JOIN documents AS d ON d.id = dv.document_id
                JOIN projects AS p ON p.id = d.project_id
                JOIN embeddings AS e ON e.chunk_id = dc.id
                WHERE p.name = %s
                  AND d.is_active = TRUE
                  AND dv.version_number = d.current_version
                  AND e.model_name = %s
                ORDER BY e.embedding <=> %s
                LIMIT %s
                """,
                (PROJECT_NAME, EMBEDDING_MODEL_NAME, query_embedding, aantal),
            )
            resultaten = cursor.fetchall()
    finally:
        connection.close()

    return "\n\n---\n\n".join(resultaat[0] for resultaat in resultaten)


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


def genereer_factuurtekst(
    nieuwe_opdracht: str,
    document=None,
    style_text="",
    prompt="",
    modus="Tekst herschrijven",
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

    if modus == "Nieuwe tekst genereren":
        taak_instructie = """
Maak een nieuwe tekst op basis van de opdracht hieronder.

- Gebruik de opdracht als inhoudelijke briefing.
- Gebruik de stijl, structuur, formaliteit, het detailniveau en de vaktermen
    uit de trainingsvoorbeelden en het document.
- Verzin geen feiten, namen of aantallen die niet in de opdracht of
    uitgangspunten staan.
"""
        opdracht_label = "Opdracht voor de nieuwe tekst"
    else:
        taak_instructie = """
Herschrijf de brontekst hieronder in dezelfde schrijfstijl als de
trainingsvoorbeelden en het document.

- Behoud alle feiten, namen, aantallen en betekenis uit de brontekst.
- Verzin geen informatie die niet in de brontekst of uitgangspunten staat.
- Neem de stijl, structuur, formaliteit, het detailniveau en de vaktermen over.
- Verander alleen de formulering zodat die bij de aangeleerde stijl past.
"""
        opdracht_label = "Brontekst die herschreven moet worden"

    model_prompt = f"""
Je herschrijft teksten voor een aannemersbedrijf in de bouw.

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

{opdracht_label}:
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