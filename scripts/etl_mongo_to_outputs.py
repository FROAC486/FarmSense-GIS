from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import psycopg2
import pandas as pd
import json
import os
from pathlib import Path


# =========================
# MONGODB CONFIG
# =========================
URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB", "iot")
COLLECTION_NAME = os.getenv("MONGODB_COLLECTION", "sensordata")


# =========================
# POSTGIS CONFIG
# =========================
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DBNAME = os.getenv("PG_DBNAME", "farmsense")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "admin")
PG_SSLMODE = os.getenv("PG_SSLMODE", "prefer")


# =========================
# OUTPUT CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_GEOJSON = BASE_DIR / "web" / "sensor_latest.geojson"
OUTPUT_CSV = BASE_DIR / "data" / "sensor_latest.csv"


# =========================
# PARSING HELPERS
# =========================
def parse_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def parse_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


def safe_json_dumps(value):
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return None


def first_valid_float(*values):
    for value in values:
        parsed = parse_float(value)
        if parsed is not None:
            return parsed
    return None


def build_geojson_point(lon, lat, alt=None):
    if lon is None or lat is None:
        return None

    coords = [lon, lat]

    if alt is not None:
        coords.append(alt)

    return json.dumps({
        "type": "Point",
        "coordinates": coords
    })


def valid_humidity(value):
    h = parse_float(value)

    if h is None:
        return None

    if 0 <= h <= 100:
        return h

    return None


# =========================
# LOCATION EXTRACTION
# =========================
def extract_tags_location(device_info):
    tags = device_info.get("tags", {}) or {}

    site = tags.get("site")

    tag_lat = parse_float(tags.get("lat"))
    tag_lon = parse_float(tags.get("lon"))
    tag_alt = parse_float(tags.get("alt"))

    geojson_raw = tags.get("geojson")

    geojson_clean = None
    lat = None
    lon = None
    alt = None

    if geojson_raw:
        try:
            geo = json.loads(geojson_raw)
            coords = geo.get("coordinates", [])

            if len(coords) >= 2:
                lon = parse_float(coords[0])
                lat = parse_float(coords[1])

                if len(coords) >= 3:
                    alt = parse_float(coords[2])

                geojson_clean = json.dumps(geo)

        except Exception:
            pass

    if lat is None or lon is None:
        if tag_lat is not None and tag_lon is not None:
            lat = tag_lat
            lon = tag_lon
            alt = tag_alt
            geojson_clean = build_geojson_point(lon, lat, alt)

    return {
        "site": site,
        "sensor_latitude": lat,
        "sensor_longitude": lon,
        "sensor_altitude": alt,
        "sensor_geojson": geojson_clean,
        "raw_tags_json": safe_json_dumps(tags)
    }


def extract_gateway_info(doc):
    rx_info = doc.get("rxInfo", [])

    gateway_id = None
    gateway_lat = None
    gateway_lon = None
    gateway_alt = None
    rssi = None
    snr = None

    if rx_info and isinstance(rx_info, list):
        first_rx = rx_info[0]

        gateway_id = first_rx.get("gatewayId")
        rssi = first_rx.get("rssi")
        snr = first_rx.get("snr")

        loc = first_rx.get("location", {}) or {}

        gateway_lat = parse_float(loc.get("latitude"))
        gateway_lon = parse_float(loc.get("longitude"))
        gateway_alt = parse_float(loc.get("altitude"))

    return {
        "gateway_id": gateway_id,
        "gateway_latitude": gateway_lat,
        "gateway_longitude": gateway_lon,
        "gateway_altitude": gateway_alt,
        "gateway_geojson": build_geojson_point(gateway_lon, gateway_lat, gateway_alt),
        "rssi": rssi,
        "snr": snr
    }


# =========================
# ENVIRONMENTAL SENSOR FIELDS
# =========================
def extract_environmental_fields(obj, device_profile_name):
    temp_c = None
    humidity = None

    if device_profile_name == "LSN50-V2":
        temp1 = parse_float(obj.get("TempC1"))
        temp_sht = parse_float(obj.get("TempC_SHT"))

        temp_c = temp1 if temp1 is not None and temp1 != 0 else temp_sht
        humidity = valid_humidity(obj.get("Hum_SHT"))

    elif device_profile_name == "LSN50v2-S31":
        temp_c = parse_float(obj.get("TempC_SHT"))
        humidity = valid_humidity(obj.get("Hum_SHT"))

    else:
        temp_sht = parse_float(obj.get("TempC_SHT"))
        temp1 = parse_float(obj.get("TempC1"))

        if temp_sht is not None and temp_sht != 0:
            temp_c = temp_sht
        elif temp1 is not None and temp1 != 0:
            temp_c = temp1

        humidity = valid_humidity(obj.get("Hum_SHT"))

    return {
        "temperature_c": temp_c,
        "humidity": humidity,
        "battery_v": parse_float(obj.get("BatV")),
        "door_status": obj.get("Door_status"),
        "adc_ch0v": parse_float(obj.get("ADC_CH0V")),
        "digital_status": obj.get("Digital_IStatus"),
        "work_mode": obj.get("Work_mode"),
        "raw_tempc1": parse_float(obj.get("TempC1")),
        "raw_tempc_sht": parse_float(obj.get("TempC_SHT")),
        "raw_hum_sht": parse_float(obj.get("Hum_SHT"))
    }


# =========================
# TANK SENSOR FIELDS
# =========================
def extract_tank_fields(obj, device_profile_name, site=None, device_name=None):
    has_distance = any(
        key in obj
        for key in [
            "Distance",
            "distance",
            "Distance_mm",
            "distance_mm",
            "distance_mm_value"
        ]
    )

    is_tank = (
        has_distance
        or (device_profile_name and "DDS75" in str(device_profile_name))
        or (site and "tank" in str(site).lower())
        or (device_name and "tank" in str(device_name).lower())
    )

    empty_tank_fields = {
        "tank_air_gap_mm": None,
        "tank_air_gap_m": None,
        "tank_distance": None,
        "tank_battery_v": None,
        "tank_temp_c": None,
        "interrupt_flag": None,
        "sensor_flag": None,
        "raw_distance": None,
        "raw_tank_object_json": None
    }

    if not is_tank:
        return empty_tank_fields

    # FIXED VERSION
    distance = parse_float(obj.get("Distance"))

    if distance is None:
        distance = parse_float(obj.get("distance"))

    if distance is None:
        distance = parse_float(obj.get("Distance_mm"))

    if distance is None:
        distance = parse_float(obj.get("distance_mm"))

    if distance is None:
        distance = parse_float(obj.get("distance_mm_value"))

    return {
        "tank_air_gap_mm": distance,
        "tank_air_gap_m": distance / 1000 if distance is not None else None,
        "tank_distance": distance,
        "tank_battery_v": first_valid_float(obj.get("Bat"), obj.get("BatV"), obj.get("battery")),
        "tank_temp_c": first_valid_float(obj.get("TempC_DS18B20"), obj.get("TempC1")),
        "interrupt_flag": parse_int(obj.get("Interrupt_flag")),
        "sensor_flag": parse_int(obj.get("Sensor_flag")),
        "raw_distance": obj.get("Distance"),
        "raw_tank_object_json": safe_json_dumps(obj)
    }


# =========================
# SENSECAP WEATHER SENSOR FIELDS
# =========================
def extract_sensecap_fields(obj, device_profile_name):
    result = {
        "air_temperature": None,
        "air_humidity": None,
        "light_intensity": None,
        "uv_index": None,
        "wind_speed": None,
        "wind_direction": None,
        "rain_gauge": None,
        "rain_accumulation": None,
        "pressure": None,
        "wind_gust": None,
        "sensecap_payload_valid": None,
        "sensecap_payload_hex": None,
        "sensecap_err": None
    }

    if device_profile_name != "SenseCAP S2120":
        return result

    result["sensecap_payload_valid"] = obj.get("valid")
    result["sensecap_payload_hex"] = obj.get("payload")
    result["sensecap_err"] = obj.get("err")

    messages = obj.get("messages", [])

    if not isinstance(messages, list):
        return result

    for group in messages:
        if not isinstance(group, list):
            continue

        for item in group:
            if not isinstance(item, dict):
                continue

            m_type = item.get("type")
            value = item.get("measurementValue")

            if m_type == "Air Temperature":
                result["air_temperature"] = parse_float(value)
            elif m_type == "Air Humidity":
                result["air_humidity"] = parse_float(value)
            elif m_type == "Light Intensity":
                result["light_intensity"] = parse_float(value)
            elif m_type == "UV Index":
                result["uv_index"] = parse_float(value)
            elif m_type == "Wind Speed":
                result["wind_speed"] = parse_float(value)
            elif m_type == "Wind Direction Sensor":
                result["wind_direction"] = parse_float(value)
            elif m_type == "Rain Gauge":
                result["rain_gauge"] = parse_float(value)
            elif m_type == "Rain Accumulation":
                result["rain_accumulation"] = parse_float(value)
            elif m_type == "Barometric Pressure":
                result["pressure"] = parse_float(value)
            elif m_type == "Peak Wind Gust":
                result["wind_gust"] = parse_float(value)

    return result


# =========================
# DOCUMENT FLATTENING
# =========================
def flatten_doc(doc):
    device_info = doc.get("deviceInfo", {}) or {}
    obj = doc.get("object", {}) or {}
    tags = device_info.get("tags", {}) or {}

    device_profile_name = device_info.get("deviceProfileName")
    device_name = device_info.get("deviceName")
    site = tags.get("site")

    row = {
        "mongo_id": str(doc.get("_id")),
        "time": doc.get("time"),
        "iso": doc.get("iso"),
        "ts": doc.get("ts"),
        "topic": doc.get("topic"),
        "deduplication_id": doc.get("deduplicationId"),

        "tenant_name": device_info.get("tenantName"),
        "application_name": device_info.get("applicationName"),
        "device_profile_name": device_profile_name,
        "device_name": device_name,
        "dev_eui": device_info.get("devEui"),
        "device_class": device_info.get("deviceClassEnabled"),

        "dev_addr": doc.get("devAddr"),
        "f_cnt": doc.get("fCnt"),
        "f_port": doc.get("fPort"),
        "confirmed": doc.get("confirmed"),
        "adr": doc.get("adr"),
        "dr": doc.get("dr"),
        "region_config_id": doc.get("regionConfigId"),

        "raw_object_json": safe_json_dumps(obj)
    }

    row.update(extract_tags_location(device_info))
    row.update(extract_gateway_info(doc))
    row.update(extract_environmental_fields(obj, device_profile_name))
    row.update(extract_tank_fields(obj, device_profile_name, site, device_name))
    row.update(extract_sensecap_fields(obj, device_profile_name))

    return row


# =========================
# MONGODB LATEST PER DEVICE
# =========================
def fetch_latest_per_device(collection):
    device_names = collection.distinct("deviceInfo.deviceName")
    latest_docs = []

    print(f"Found {len(device_names)} devices")

    for device_name in device_names:
        if not device_name:
            continue

        doc = collection.find_one(
            {"deviceInfo.deviceName": device_name},
            sort=[
                ("time", -1),
                ("_id", -1)
            ]
        )

        if doc:
            latest_docs.append(doc)

    return latest_docs


# =========================
# OUTPUT WRITERS
# =========================
def write_snapshot_csv(df):
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote latest snapshot CSV to {OUTPUT_CSV}")


def clean_value_for_geojson(value):
    if pd.isna(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    return value


def write_snapshot_geojson(df):
    OUTPUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)

    features = []

    for _, row in df.iterrows():
        lat = row.get("sensor_latitude")
        lon = row.get("sensor_longitude")

        if pd.isna(lat) or pd.isna(lon):
            print(f"Skipping GeoJSON feature for {row.get('device_name')} - missing coordinates")
            continue

        properties = {}

        for col in df.columns:
            value = row[col]
            properties[col] = clean_value_for_geojson(value)

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

    print(f"Wrote latest GeoJSON to {OUTPUT_GEOJSON}")
    print(f"GeoJSON features written: {len(features)}")


# =========================
# POSTGIS LOADER
# =========================
def create_or_update_postgis_table(pg_cur):
    pg_cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    pg_cur.execute("""
    CREATE TABLE IF NOT EXISTS sensor_latest (
        device_name TEXT PRIMARY KEY,
        mongo_id TEXT,
        time TIMESTAMPTZ,
        site TEXT,
        device_profile TEXT,
        temperature_c DOUBLE PRECISION,
        humidity DOUBLE PRECISION,
        pressure DOUBLE PRECISION,
        battery_v DOUBLE PRECISION,
        geom geometry(Point, 4326)
    );
    """)

    alter_query = """
    ALTER TABLE sensor_latest
    ADD COLUMN IF NOT EXISTS tank_air_gap_mm DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS tank_air_gap_m DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS tank_distance DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS tank_battery_v DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS tank_temp_c DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS air_temperature DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS air_humidity DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS wind_speed DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS wind_direction DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS wind_gust DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS rain_gauge DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS rain_accumulation DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS rssi DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS snr DOUBLE PRECISION;
    """

    pg_cur.execute(alter_query)


def insert_into_postgis_latest(df):
    if df.empty:
        print("No rows to insert into PostGIS.")
        return

    pg_conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DBNAME,
        user=PG_USER,
        password=PG_PASSWORD,
        sslmode=PG_SSLMODE
    )

    pg_cur = pg_conn.cursor()

    create_or_update_postgis_table(pg_cur)

    upsert_query = """
    INSERT INTO sensor_latest (
        device_name,
        mongo_id,
        time,
        site,
        device_profile,
        temperature_c,
        humidity,
        pressure,
        battery_v,
        tank_air_gap_mm,
        tank_air_gap_m,
        tank_distance,
        tank_battery_v,
        tank_temp_c,
        air_temperature,
        air_humidity,
        wind_speed,
        wind_direction,
        wind_gust,
        rain_gauge,
        rain_accumulation,
        rssi,
        snr,
        geom
    )
    VALUES (
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s,
        ST_SetSRID(ST_MakePoint(%s, %s), 4326)
    )
    ON CONFLICT (device_name)
    DO UPDATE SET
        mongo_id = EXCLUDED.mongo_id,
        time = EXCLUDED.time,
        site = EXCLUDED.site,
        device_profile = EXCLUDED.device_profile,
        temperature_c = EXCLUDED.temperature_c,
        humidity = EXCLUDED.humidity,
        pressure = EXCLUDED.pressure,
        battery_v = EXCLUDED.battery_v,
        tank_air_gap_mm = EXCLUDED.tank_air_gap_mm,
        tank_air_gap_m = EXCLUDED.tank_air_gap_m,
        tank_distance = EXCLUDED.tank_distance,
        tank_battery_v = EXCLUDED.tank_battery_v,
        tank_temp_c = EXCLUDED.tank_temp_c,
        air_temperature = EXCLUDED.air_temperature,
        air_humidity = EXCLUDED.air_humidity,
        wind_speed = EXCLUDED.wind_speed,
        wind_direction = EXCLUDED.wind_direction,
        wind_gust = EXCLUDED.wind_gust,
        rain_gauge = EXCLUDED.rain_gauge,
        rain_accumulation = EXCLUDED.rain_accumulation,
        rssi = EXCLUDED.rssi,
        snr = EXCLUDED.snr,
        geom = EXCLUDED.geom;
    """

    upserted_count = 0

    for _, row in df.iterrows():
        lon = row.get("sensor_longitude")
        lat = row.get("sensor_latitude")

        if lon is None or lat is None or pd.isna(lon) or pd.isna(lat):
            print(f"Skipping PostGIS insert for {row.get('device_name')} - no sensor coordinates")
            continue

        pg_cur.execute(
            upsert_query,
            (
                row.get("device_name"),
                row.get("mongo_id"),
                row.get("time"),
                row.get("site"),
                row.get("device_profile_name"),

                row.get("temperature_c"),
                row.get("humidity"),
                row.get("pressure"),
                row.get("battery_v"),

                row.get("tank_air_gap_mm"),
                row.get("tank_air_gap_m"),
                row.get("tank_distance"),
                row.get("tank_battery_v"),
                row.get("tank_temp_c"),

                row.get("air_temperature"),
                row.get("air_humidity"),
                row.get("wind_speed"),
                row.get("wind_direction"),
                row.get("wind_gust"),
                row.get("rain_gauge"),
                row.get("rain_accumulation"),

                row.get("rssi"),
                row.get("snr"),

                lon,
                lat
            )
        )

        upserted_count += 1

    pg_conn.commit()
    pg_cur.close()
    pg_conn.close()

    print(f"Upserted {upserted_count} rows into PostGIS table sensor_latest.")


# =========================
# CONSOLE SUMMARY
# =========================
def print_summary(df):
    if df.empty:
        print("No data available for summary.")
        return

    print("\nDevice profile counts:")
    print(df["device_profile_name"].value_counts(dropna=False).to_string())

    print("\nTank debug check:")
    tank_cols = [
        "device_name",
        "device_profile_name",
        "site",
        "time",
        "tank_air_gap_mm",
        "tank_air_gap_m",
        "tank_temp_c",
        "tank_battery_v",
        "raw_distance"
    ]

    existing_tank_cols = [col for col in tank_cols if col in df.columns]

    print(
        df[existing_tank_cols]
        .loc[
            df["site"].astype(str).str.contains("tank", case=False, na=False)
            | df["device_profile_name"].astype(str).str.contains("DDS75", case=False, na=False)
            | df["tank_air_gap_mm"].notna()
        ]
        .to_string(index=False)
    )

    print("\nLatest devices snapshot:")

    cols = [
        "device_name",
        "device_profile_name",
        "site",
        "time",
        "sensor_latitude",
        "sensor_longitude",
        "temperature_c",
        "humidity",
        "air_temperature",
        "air_humidity",
        "pressure",
        "wind_speed",
        "rain_gauge",
        "tank_air_gap_mm",
        "tank_air_gap_m",
        "tank_temp_c",
        "tank_battery_v",
        "rssi",
        "snr"
    ]

    existing_cols = [col for col in cols if col in df.columns]

    print(
        df[existing_cols]
        .drop_duplicates()
        .sort_values(["device_profile_name", "device_name"], na_position="last")
        .to_string(index=False)
    )


# =========================
# MAIN RUNNER
# =========================
def run_once():
    if not URI:
        raise ValueError(
            "MONGODB_URI environment variable is not set. "
            "Set it before running the script."
        )

    client = MongoClient(URI, server_api=ServerApi("1"))
    client.admin.command("ping")

    print("Connected to MongoDB")

    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    docs = fetch_latest_per_device(collection)

    if not docs:
        print("No latest records found.")
        return

    rows = [flatten_doc(doc) for doc in docs]
    df = pd.DataFrame(rows)

    df = df.drop_duplicates(subset=["device_name"])

    if not df.empty and "time" in df.columns:
        df = df.sort_values("time", ascending=False)

    write_snapshot_csv(df)
    write_snapshot_geojson(df)

    try:
        insert_into_postgis_latest(df)
    except Exception as e:
        print("PostGIS upload skipped/failed:")
        print(e)

    print_summary(df)


if __name__ == "__main__":
    try:
        run_once()
    except Exception as e:
        print("ETL failed:", e)