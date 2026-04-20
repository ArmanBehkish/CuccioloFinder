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


## Breed Detection

Most shelter dogs are mixed-breed and listed without breed information. A three-stage pipeline infers the most likely breed for each dog by combining visual and textual signals. Some shelters might mention dog breed in descriptions. This can be their guess and is interesting to compare to our system's inference.

### 1. Image Classification

Each dog's photos are passed through a **Vision Transformer** (ViT) fine-tuned on dog breed classification (`wesleyacheng/dog-breeds-multiclass-image-classification-with-vit`). The model returns the top-3 predicted breeds per image. Across all images of the same dog, breed probabilities are max-pooled (keeping the highest confidence seen for each breed) and the top 2 candidates are carried forward.

### 2. Text Profile Embedding & Similarity Search

AKCdata is a dataset of information about 277 dog breeds extracted from the American Kennel Club website. It contains 20 features of different dog breeds. We want to transform extracted textual data as much as possible to vectors with similar features and then use embeddings to find the closest breed in this dataset to detect the dog breed. This is solely experimental as some of the shelter provide very little textual information which makes building these features almost impossible.

Structured fields from the shelter listing (size, fur, weight) are normalized into a shared vocabulary aligned with AKC breed standards. Behavioral traits — energy level, trainability, demeanor, and temperament — are inferred from the dog's English description and compatibility fields using **zero-shot NLI classification** (`facebook/bart-large-mnli`).

All normalized traits are formatted into a standardized profile string (e.g. `"temperament: Friendly, Loyal. energy_level: Energetic. size: large. coat: short"`). This profile is embedded with a **sentence-transformer** (`all-MiniLM-L6-v2`) and compared via cosine similarity against a pre-built index of ~280 AKC breed profiles derived from the same template.

### 3. Fusion

Image and text signals are combined using a **dynamic alpha blending** strategy, where alpha is the weight given to the image signal:

| Image top-1 confidence | Alpha | Reasoning |
|------------------------|-------|-----------|
| > 0.70 | 0.80 | Image is confident, trust it heavily |
| 0.40 - 0.70 | 0.50 | Moderate confidence, balanced blend |
| < 0.40 | 0.30 | Image is unsure, lean on text profile |
| No images available | 0.00 | Text only |
| No text profile | 1.00 | Image only |

All candidates from both signals are pooled, and the final score is `alpha * image_score + (1 - alpha) * text_score`. The top-ranked breed is stored in `breed_en` with full provenance (method, alpha value, combined confidence).


## API

A FastAPI application serves the processed data to the frontend. The API container runs independently (`restart: unless-stopped`) while the worker populates the database on a schedule.

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check — returns server, DB, and search model readiness |
| `/api/enums` | GET | Distinct values for all filterable fields (for frontend dropdowns) |
| `/api/stats` | GET | Row-level dog data for frontend analytics and charts |
| `/api/stats/refresh` | POST | Reload enums + stats caches from DB (called by worker after each scrape cycle) |
| `/api/filter-dogs` | GET | Structured search with optional filters (source, gender, size, breed, age, fur, weight, medical status, compatibility, dates) — all AND'd |
| `/api/dogs/{id}` | GET | Full dog profile with all fields and images |
| `/api/dogs/search` | POST | Natural language search — LLM extracts structured filters from free text, then queries the DB |

### Features

- In-memory caching for enums and stats, refreshable by the worker after each scrape cycle
- Natural language search powered by LLM-based filter extraction
- Locally served dog images with fallback to original URLs
- Configurable CORS


## AI-Powered Pipeline

The goal in this project is to only use local models so it can be used without the need of providing commercial API key. Since this is an experimental project, and the compute resources are limited, the models are choosen accordingly.
The entire data flow — from raw Italian shelter listings to a searchable, English-language adoption platform — is driven by five pretrained transformer models. They handle translation, breed identification, behavioral profiling, and natural language search without any manual labeling or fine-tuning.

| Model | Purpose |
|-------|---------|
| [Helsinki-NLP/opus-mt-it-en](https://huggingface.co/Helsinki-NLP/opus-mt-it-en) | Italian → English translation of shelter fields |
| [facebook/bart-large-mnli](https://huggingface.co/facebook/bart-large-mnli) | Zero-shot classification of behavioral traits (energy, trainability, temperament) from descriptions |
| [wesleyacheng/dog-breeds-multiclass-image-classification-with-vit](https://huggingface.co/wesleyacheng/dog-breeds-multiclass-image-classification-with-vit) | Image-based breed detection via Vision Transformer |
| [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | Sentence embeddings for breed profile similarity matching against AKC standards |
| [google/flan-t5-xl](https://huggingface.co/google/flan-t5-xl) | Natural language search query → structured filter extraction (float16, ~3GB) |

All models run on CPU and are configurable via environment variables.


Under Development...
