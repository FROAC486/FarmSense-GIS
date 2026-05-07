import json
import pandas as pd

INPUT_CSV = "sensor_latest.csv"
OUTPUT_GEOJSON = "sensor_latest.geojson"

df = pd.read_csv(INPUT_CSV)

features = []

for _, row in df.iterrows():
    lat = row.get("sensor_latitude")
    lon = row.get("sensor_longitude")

    if pd.isna(lat) or pd.isna(lon):
        continue

    properties = {}

    for col in df.columns:
        value = row[col]
        if pd.isna(value):
            properties[col] = None
        else:
            properties[col] = value

    feature = {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [float(lon), float(lat)]
        },
        "properties": properties
    }

    features.append(feature)

geojson = {
    "type": "FeatureCollection",
    "features": features
}

with open(OUTPUT_GEOJSON, "w", encoding="utf-8") as f:
    json.dump(geojson, f, indent=2, ensure_ascii=False)

print(f"Created {OUTPUT_GEOJSON}")
print(f"Features written: {len(features)}")python csv_to_geojson.py