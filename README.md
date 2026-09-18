---
title: Marketing AI
emoji: "📣"
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 5.49.1
app_file: app.py
pinned: false
---

# Marketing AI

Gradio-app voor het genereren van marketingteksten en het bewerken van foto's.

## Space secrets

Voeg deze waarden toe via **Settings > Secrets and variables** in Hugging Face:

- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_DEPLOYMENT`
- `AZURE_OPENAI_API_VERSION` (optioneel, standaard `2024-10-21`)

De meegeleverde SQLite-database en model-checkpoint worden tijdens het starten
van de Space gebruikt. Hugging Face Spaces heeft geen permanente lokale opslag
zonder een gekoppelde Storage upgrade.