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

Scraped data is stored in a local **SQLite** database using **SQLAlchemy** ORM across four tables: `dogs`, `dog_images`, `field_provenance`, and `breeds`.

### Data Flow

```
Scrape --> Normalize --> Store --> Enrich
```

1. **Scrape** — Spiders collect dog profiles and images from each shelter website.
2. **Normalize** — Per-source pipelines clean and standardize the data (merging descriptions, parsing dates, removing boilerplate). Images are downloaded locally.
3. **Store** — A shared database pipeline upserts records by source URL. If an Italian field changes on re-scrape, its English counterpart is automatically cleared for re-translation.
4. **Enrich** — The translation pipeline adds English versions of all translatable fields, followed by breed detection.

### Breeds Reference Table

A `breeds` table serves as the canonical reference for all breed names, populated at database initialization from the **AKC dataset** (277 breeds). Each breed record includes a `vit_label` column that maps the ViT image classifier's Stanford Dogs labels (120 classes, snake_case) to their canonical AKC names. `Dog.breed_en` is a foreign key referencing `breeds.name`, ensuring all stored breed values are consistent and validated.


## Translation & Enrichment

All shelter data is originally in Italian. An enrichment pipeline translates 12 field pairs (description, gender, age, size, breed, fur, medical status, compatibility, etc.) into English.

Translation uses a hybrid approach:
- **Static mappings** for common shelter vocabulary (gender, size, medical terms) to ensure consistent, accurate translations of domain-specific terms.
- **ML fallback** using Helsinki-NLP's `opus-mt-it-en` transformer model for simple fields and unmapped values.
- **Mistral 7B Instruct** (GGUF, 4-bit quantized) for dog descriptions — translates the full description as a whole with prompt engineering tailored for shelter adoption tone, context-aware phrasing, and Italian shelter-specific terminology (canile, staffetta, box, etc.). The worker calls the API container's `/api/translate/description` endpoint to reuse the already-loaded Mistral model without duplicating it in memory.

Every enriched field is tracked in a **field provenance** table recording the method, model, and confidence — providing a full audit trail of what was translated and how.


## Breed Detection

Most shelter dogs are mixed-breed and listed without breed information. A three-stage pipeline infers the most likely breed for each dog by combining visual and textual signals. Some shelters might mention dog breed in descriptions. This can be their guess and is interesting to compare to our system's inference.

### 1. Image Classification

Each dog's photos are passed through a **Vision Transformer** (ViT) fine-tuned on dog breed classification (`wesleyacheng/dog-breeds-multiclass-image-classification-with-vit`). The model returns the top-3 predicted breeds per image. Across all images of the same dog, breed probabilities are max-pooled (keeping the highest confidence seen for each breed).

Before selection, ViT labels are filtered against the `vit_to_akc.json` mapping — only labels with a valid AKC breed mapping are considered. Garbage labels from the Stanford Dogs dataset (e.g., `"black"`, `"flat"`, `"dingo"`) are skipped, and the next valid candidate takes their place. The top 2 valid breeds are then resolved to their canonical AKC names and carried forward.

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

Since both image and text signals are now resolved to canonical AKC names before merging, candidates from both sources share the same key space and their scores combine correctly. The final score is `alpha * image_score + (1 - alpha) * text_score`. The top-ranked breed is stored in `breed_en` (as a FK to the breeds table).

Full provenance is stored for each signal: image 1st and 2nd place (breed name + probability), text top match (breed name + similarity score), and the combined result (alpha value + combined confidence). This breakdown is displayed on the dog detail page in the frontend.


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
| `/api/dogs/{id}` | GET | Full dog profile with all fields, images, and breed detection breakdown (image/text/combined) |
| `/api/dogs/search` | POST | Natural language search — LLM extracts structured filters from free text, validates against known values and breeds table, then queries the DB |
| `/api/translate/description` | POST | Italian → English description translation using Mistral 7B (called by worker during enrichment) |
| `/api/worker/status` | GET | Check if the worker pipeline is currently running |
| `/api/worker/status` | POST | Set worker busy/ready status (called by worker at pipeline start/end, auto-clears after 3 hours) |

### Features

- In-memory caching for enums and stats, refreshable by the worker after each scrape cycle
- Natural language search powered by LLM-based filter extraction with post-processing validation (strips invalid values like "any"/"none", validates fields against known value sets, resolves breed names against the breeds table)
- Locally served dog images with fallback to original URLs
- Worker status signaling — the frontend shows a maintenance banner on the smart search page when the worker pipeline is running, since the Mistral model is shared between translation and search
- Configurable CORS


## AI-Powered Pipeline

The goal in this project is to only use local models so it can be used without the need of providing commercial API key. Since this is an experimental project, and the compute resources are limited, the models are choosen accordingly.
The entire data flow — from raw Italian shelter listings to a searchable, English-language adoption platform — is driven by five pretrained transformer models. They handle translation, breed identification, behavioral profiling, and natural language search without any manual labeling or fine-tuning.

| Model | Purpose |
|-------|---------|
| [Helsinki-NLP/opus-mt-it-en](https://huggingface.co/Helsinki-NLP/opus-mt-it-en) | Italian → English translation of simple shelter fields (gender, size, fur, medical status) |
| [Mistral 7B Instruct v0.3](https://huggingface.co/MaziyarPanahi/Mistral-7B-Instruct-v0.3-GGUF) | Description translation (IT→EN) with shelter-tone prompt engineering, and natural language search filter extraction (GGUF Q4_K_M, ~4.4GB) |
| [facebook/bart-large-mnli](https://huggingface.co/facebook/bart-large-mnli) | Zero-shot classification of behavioral traits (energy, trainability, temperament) from descriptions |
| [wesleyacheng/dog-breeds-multiclass-image-classification-with-vit](https://huggingface.co/wesleyacheng/dog-breeds-multiclass-image-classification-with-vit) | Image-based breed detection via Vision Transformer (120 Stanford Dogs classes → mapped to AKC canonical names) |
| [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | Sentence embeddings for breed profile similarity matching against AKC standards |

All models run on CPU. The Mistral model runs as a 4-bit quantized GGUF file via `llama-cpp-python`, loaded once in the API container and shared between description translation and smart search. All models are configurable via environment variables.


Under Development...
