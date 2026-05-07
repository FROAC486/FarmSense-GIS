from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import psycopg2
import pandas as pd
import json
import time
import os

# =========================
# MONGODB CONFIG
# =========================
URI = "mongodb+srv://oliver:uKQbTX8ebb1zGVFy@cluster0.cvmjitc.mongodb.net/?appName=Cluster"
DB_NAME = "iot"
COLLECTION_NAME = "sensordata"

# =========================
# POSTGIS CONFIG
# =========================
PG_HOST = "localhost"
PG_PORT = "5433"
PG_DBNAME = "farm_project"
PG_USER = "postgres"
PG_PASSWORD = "admin"
PG_SSLMODE = "prefer"

# =========================
# OUTPUT CONFIG
# =========================
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

OUTPUT_GEOJSON = BASE_DIR / "web" / "sensor_latest.geojson"
OUTPUT_CSV = BASE_DIR / "data" / "sensor_latest.csv"

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
        "raw_tags_json": json.dumps(tags)
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
        "raw_hum_sht": parse_float(obj.get("Hum_SHT")),
    }


def extract_tank_fields(obj, device_profile_name):
    if device_profile_name != "DDS75":
        return {
            "tank_distance": None,
            "tank_battery_v": None,
            "tank_temp_c": None,
            "interrupt_flag": None,
            "sensor_flag": None
        }

    return {
        "tank_distance": parse_float(obj.get("Distance")),
        "tank_battery_v": parse_float(obj.get("Bat")),
        "tank_temp_c": parse_float(obj.get("TempC_DS18B20")),
        "interrupt_flag": parse_int(obj.get("Interrupt_flag")),
        "sensor_flag": parse_int(obj.get("Sensor_flag"))
    }


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


def flatten_doc(doc):
    device_info = doc.get("deviceInfo", {}) or {}
    obj = doc.get("object", {}) or {}
    device_profile_name = device_info.get("deviceProfileName")

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
        "device_name": device_info.get("deviceName"),
        "dev_eui": device_info.get("devEui"),
        "device_class": device_info.get("deviceClassEnabled"),

        "dev_addr": doc.get("devAddr"),
        "f_cnt": doc.get("fCnt"),
        "f_port": doc.get("fPort"),
        "confirmed": doc.get("confirmed"),
        "adr": doc.get("adr"),
        "dr": doc.get("dr"),
        "region_config_id": doc.get("regionConfigId"),

        "raw_object_json": json.dumps(obj)
    }

    row.update(extract_tags_location(device_info))
    row.update(extract_gateway_info(doc))
    row.update(extract_environmental_fields(obj, device_profile_name))
    row.update(extract_tank_fields(obj, device_profile_name))
    row.update(extract_sensecap_fields(obj, device_profile_name))

    return row


def fetch_latest_per_device(collection):
    device_names = collection.distinct("deviceInfo.deviceName")
    latest_docs = []

    print(f"Found {len(device_names)} devices")

    for device_name in device_names:
        if not device_name:
            continue

        doc = collection.find_one(
            {"deviceInfo.deviceName": device_name},
            sort=[("time", -1)]
        )

        if doc:
            latest_docs.append(doc)

    return latest_docs


def write_snapshot_csv(df):
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Wrote latest snapshot to {OUTPUT_CSV}")


def write_snapshot_geojson(df):
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

    print(f"Wrote latest GeoJSON to {OUTPUT_GEOJSON}")
    print(f"Features written: {len(features)}")


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
        geom
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s,
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
        geom = EXCLUDED.geom;
    """

    upserted_count = 0

    for _, row in df.iterrows():
        lon = row.get("sensor_longitude")
        lat = row.get("sensor_latitude")

        if lon is None or lat is None:
            print(f"Skipping {row.get('device_name')} - no sensor coordinates")
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
                lon,
                lat
            )
        )

        upserted_count += 1

    pg_conn.commit()
    pg_cur.close()
    pg_conn.close()

    print(f"Upserted {upserted_count} rows into sensor_latest.")


def print_summary(df):
    print("\nDevice profile counts:")
    print(df["device_profile_name"].value_counts(dropna=False).to_string())

    print("\nLatest devices snapshot:")
    print(
        df[[
            "device_name",
            "device_profile_name",
            "site",
            "time",
            "sensor_latitude",
            "sensor_longitude"
        ]]
        .drop_duplicates()
        .sort_values(["device_profile_name", "device_name"])
        .to_string(index=False)
    )


def run_once():
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
    insert_into_postgis_latest(df)
    print_summary(df)


if __name__ == "__main__":
    try:
        run_once()
    except Exception as e:
        print("ETL failed:", e)