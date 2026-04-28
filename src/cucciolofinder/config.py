from dataclasses import dataclass

@dataclass
class ShelterSite:
    url: str

# Scrapers URLs for Pidemont Region
SHELTER_SITES: dict[str, ShelterSite] = {
    "quattrozampeinfamiglia": ShelterSite(url="https://www.quattrozampeinfamiglia.it/search/?geodir_search=1&saz=&stype=gd_animali&spost_category%5B%5D=47&sregion%5B%5D=Piemonte&s=&snear=&ssesso%5B%5D=&staglia%5B%5D=&set%5B%5D=&srazza%5B%5D=&srazza_gatto%5B%5D=&sgeo_lat=&sgeo_lon="),
    "empethy":ShelterSite(url="https://www.empethy.it/organizzazioni/rifugio-impronta-creativa-torino"),
    "alberodimais":ShelterSite(url="https://alberodimais.it/cani"),
    "enpatorino":ShelterSite(url="https://www.voltoweb.it/enpasezionetorino/"),
    "canileoasi":ShelterSite(url="https://canileoasi.it/adozioni/"),
}

# Quick-test scrape limit. 
# Integer for limited number
# None for Production
SCRAPE_LIMIT_PER_SPIDER: int | None = 3