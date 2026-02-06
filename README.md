# CuccioloFinder

Find A Puppy You Love


## Data Sources

Dog profiles are scraped from the following shelter websites in the Torino/Piedmont region:

| Website | Description |
|---------|-------------|
| [Quattro Zampe in Famiglia](https://www.quattrozampeinfamiglia.it) | Pet adoption directory listing dogs available across Piedmont shelters |
| [Empethy](https://www.empethy.it) | National pet adoption platform; we scrape listings from Rifugio Impronta Creativa in Turin |
| [Albero di Mais](https://alberodimais.it) | Dog rescue association based in Piedmont |
| [ENPA Torino](https://www.voltoweb.it/enpasezionetorino/) | Turin branch of the Italian National Animal Protection Agency |
| [Canile Oasi](https://canileoasi.it) | Dog shelter in Alpignano (Turin), listing dogs available for adoption |


## Database

Scraped data is stored in a local **SQLite** database using **SQLAlchemy** ORM across three tables: `dogs`, `dog_images`, and `field_provenance`.

### Data Flow

```
Scrape --> Normalize --> Store --> Enrich
```

1. **Scrape** — Spiders collect dog profiles and images from each shelter website.
2. **Normalize** — Per-source pipelines clean and standardize the data (merging descriptions, parsing dates, removing boilerplate). Images are downloaded locally.
3. **Store** — A shared database pipeline upserts records by source URL. If an Italian field changes on re-scrape, its English counterpart is automatically cleared for re-translation.
4. **Enrich** — The translation pipeline adds English versions of all translatable fields.


## Translation & Enrichment

All shelter data is originally in Italian. An enrichment pipeline translates 12 field pairs (description, gender, age, size, breed, fur, medical status, compatibility, etc.) into English.

Translation uses a hybrid approach:
- **Static mappings** for common shelter vocabulary (gender, size, medical terms) to ensure consistent, accurate translations of domain-specific terms.
- **ML fallback** using Helsinki-NLP's `opus-mt-it-en` transformer model for free-text and unmapped values. Runs via HuggingFace Inference API in development or as a local model in production.

Every enriched field is tracked in a **field provenance** table recording the method, model, and confidence — providing a full audit trail of what was translated and how.


Under Development...
