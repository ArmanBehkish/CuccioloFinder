#!/bin/sh
# Download AKC dataset into the data volume if not already present.
AKC_CSV="/app/data/datasets/akc-data-latest.csv"
if [ ! -f "$AKC_CSV" ]; then
    mkdir -p /app/data/datasets
    echo "Downloading AKC dataset..."
    python -c "import urllib.request; urllib.request.urlretrieve('https://raw.githubusercontent.com/tmfilho/akcdata/master/data/akc-data-latest.csv', '$AKC_CSV')"
    echo "AKC dataset downloaded"
fi

exec "$@"
