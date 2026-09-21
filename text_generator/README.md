# Marketing AI

Gradio-app voor het genereren van marketingteksten.

## Railway deployment

Maak in Railway een Python-service aan vanuit deze repository. Railway gebruikt
de `Procfile` om de app te starten en stelt automatisch de `PORT`-variabele in.

De app luistert op `0.0.0.0` en gebruikt de Railway-poort automatisch.

## Environment variables

Voeg deze waarden toe via de Railway service-instellingen:

- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_OPENAI_API_VERSION` (optioneel, standaard `2024-10-21`)

De SQLite-database staat in de repository. Railway's lokale schijf is standaard
tijdelijk; gebruik een Railway Volume als gegevens na redeploys behouden moeten
blijven.