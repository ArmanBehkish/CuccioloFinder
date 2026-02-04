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

Scraped data is stored in a local **SQLite** database (`data/db/cucciolofinder.db`) using **SQLAlchemy** ORM.

### Data Flow

```
Spider --> ImagePipeline (downloads images to data/images/) --> DatabasePipeline
                                                                  ├── normalizes field types across spiders
                                                                  ├── upserts dog record (insert or update by source_url)
                                                                  └── links downloaded images with local file paths
```

Each spider has its own image pipeline that runs first, followed by a shared `DatabasePipeline` that normalizes the scraped data and stores it in three tables: `dogs`, `dog_images`, and `field_provenance` (for tracking LLM/image-analysis inferred values).

Under Development...
