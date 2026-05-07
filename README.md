# FarmSense GIS

Cloud-based GIS web application for monitoring IoT farm sensor data.

## Workflow

MongoDB Atlas → Python ETL → PostGIS → GeoJSON → CesiumJS Web Map

## Outputs

- `data/sensor_latest.csv`
- `web/sensor_latest.geojson`
- `web/index.html`

## Run ETL

Set MongoDB URI:

```powershell
$env:MONGODB_URI="mongodb+srv://USERNAME:PASSWORD@cluster0.cvmjitc.mongodb.net/?appName=Cluster"
```

Run ETL:

```powershell
& ".\.venv\Scripts\python.exe" ".\scripts\etl_mongo_to_outputs.py"
```

## Run Web Map

Open:

```text
web/index.html
```

with Live Server.