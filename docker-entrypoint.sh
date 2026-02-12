#!/bin/sh
# Download AKC dataset into the data volume if not already present.
AKC_CSV="/app/data/datasets/akc-data-latest.csv"
if [ ! -f "$AKC_CSV" ]; then
    mkdir -p /app/data/datasets
    echo "Downloading AKC dataset..."
    wget -q -O "$AKC_CSV" \
        "https://raw.githubusercontent.com/tmfilho/akcdata/master/data/akc-data-latest.csv"
    echo "AKC dataset downloaded"
fi

exec "$@"
