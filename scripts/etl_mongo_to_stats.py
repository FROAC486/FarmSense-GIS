from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
from datetime import datetime, timedelta, timezone
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
# OUTPUT CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent

WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"


# =========================
# TIME PERIOD CONFIG
# =========================
PERIODS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "6m": timedelta(days=182),
    "12m": timedelta(days=365),
    "all": None
}


# =========================
# BASIC PARSING HELPERS
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


def valid_humidity(value):
    h = parse_float(value)

    if h is None:
        return None

    if 0 <= h <= 100:
        return h

    return None


def safe_json_dumps(value):
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return None


def clean_for_json(value):
    if pd.isna(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if isinstance(value, datetime):
        return value.isoformat()

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass

    return value


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

        except Exception:
            pass

    if lat is None or lon is None:
        if tag_lat is not None and tag_lon is not None:
            lat = tag_lat
            lon = tag_lon
            alt = tag_alt

    return {
        "site": site,
        "sensor_latitude": lat,
        "sensor_longitude": lon,
        "sensor_altitude": alt,
        "raw_tags_json": safe_json_dumps(tags)
    }


def extract_gateway_info(doc):
    rx_info = doc.get("rxInfo", [])

    gateway_id = None
    rssi = None
    snr = None

    if rx_info and isinstance(rx_info, list):
        first_rx = rx_info[0]

        gateway_id = first_rx.get("gatewayId")
        rssi = parse_float(first_rx.get("rssi"))
        snr = parse_float(first_rx.get("snr"))

    return {
        "gateway_id": gateway_id,
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
def extract_tank_fields(obj, device_profile_name):
    is_tank = device_profile_name and "DDS75" in device_profile_name

    empty_tank_fields = {
        "tank_air_gap_mm": None,
        "tank_air_gap_m": None,
        "tank_distance": None,
        "tank_battery_v": None,
        "tank_temp_c": None,
        "interrupt_flag": None,
        "sensor_flag": None
    }

    if not is_tank:
        return empty_tank_fields

    distance = parse_float(obj.get("Distance"))

    if distance is None:
        distance = parse_float(obj.get("distance"))

    if distance is None:
        distance = parse_float(obj.get("Distance_mm"))

    if distance is None:
        distance = parse_float(obj.get("distance_mm"))

    return {
        "tank_air_gap_mm": distance,
        "tank_air_gap_m": distance / 1000 if distance is not None else None,
        "tank_distance": distance,
        "tank_battery_v": parse_float(obj.get("Bat")),
        "tank_temp_c": parse_float(obj.get("TempC_DS18B20")),
        "interrupt_flag": parse_int(obj.get("Interrupt_flag")),
        "sensor_flag": parse_int(obj.get("Sensor_flag"))
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

        "raw_object_json": safe_json_dumps(obj)
    }

    row.update(extract_tags_location(device_info))
    row.update(extract_gateway_info(doc))
    row.update(extract_environmental_fields(obj, device_profile_name))
    row.update(extract_tank_fields(obj, device_profile_name))
    row.update(extract_sensecap_fields(obj, device_profile_name))

    return row


# =========================
# MONGODB QUERY
# =========================
def build_time_query(period_delta):
    if period_delta is None:
        return {}

    now_utc = datetime.now(timezone.utc)
    start_time = now_utc - period_delta

    return {
        "time": {
            "$gte": start_time.isoformat()
        }
    }


def fetch_period_records(collection, period_name, period_delta):
    print(f"\nFetching records for: {period_name}")

    if period_delta is None:
        print("Time filter: whole record")
    else:
        now_utc = datetime.now(timezone.utc)
        start_time = now_utc - period_delta

        print(f"Start time UTC: {start_time.isoformat()}")
        print(f"End time UTC:   {now_utc.isoformat()}")

    query = build_time_query(period_delta)

    # Important:
    # Do NOT sort in MongoDB for long date ranges.
    # MongoDB can hit its 32MB memory sort limit.
    # We fetch first, then sort later in Pandas.
    docs = list(collection.find(query))

    print(f"Records found for {period_name}: {len(docs)}")

    return docs

# =========================
# LONG PERIOD DOWNSAMPLING
# =========================
def downsample_long_record(df):
    if df.empty:
        return df

    if "time" not in df.columns:
        return df

    if len(df) <= 5000:
        print("Long-period dataset is small enough. Keeping raw records.")
        return df

    print("Long-period dataset is large. Downsampling to hourly averages per sensor...")

    df = df.copy()

    df["parsed_time"] = pd.to_datetime(df["time"], errors="coerce", utc=True)
    df = df.dropna(subset=["parsed_time"])

    if df.empty:
        return df.drop(columns=["parsed_time"], errors="ignore")

    df["hour"] = df["parsed_time"].dt.floor("h")

    graphable_columns = [
        "temperature_c",
        "humidity",
        "air_temperature",
        "air_humidity",
        "pressure",
        "wind_speed",
        "wind_direction",
        "wind_gust",
        "rain_gauge",
        "rain_accumulation",
        "tank_air_gap_mm",
        "tank_distance",
        "tank_temp_c",
        "battery_v",
        "tank_battery_v",
        "rssi",
        "snr"
    ]

    existing_graphable_columns = [
        col for col in graphable_columns
        if col in df.columns
    ]

    metadata_columns = [
        "mongo_id",
        "time",
        "iso",
        "ts",
        "topic",
        "deduplication_id",
        "tenant_name",
        "application_name",
        "device_profile_name",
        "dev_eui",
        "device_class",
        "dev_addr",
        "f_cnt",
        "f_port",
        "confirmed",
        "adr",
        "dr",
        "region_config_id",
        "site",
        "sensor_latitude",
        "sensor_longitude",
        "sensor_altitude",
        "raw_tags_json",
        "gateway_id",
        "door_status",
        "digital_status",
        "work_mode",
        "raw_object_json",
        "sensecap_payload_valid",
        "sensecap_payload_hex",
        "sensecap_err"
    ]

    existing_metadata_columns = [
        col for col in metadata_columns
        if col in df.columns
    ]

    for col in existing_graphable_columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    grouped_numeric = (
        df
        .groupby(["device_name", "hour"], dropna=False)[existing_graphable_columns]
        .mean()
        .reset_index()
    )

    grouped_meta = (
        df
        .sort_values("parsed_time")
        .groupby(["device_name", "hour"], dropna=False)[existing_metadata_columns]
        .last()
        .reset_index()
    )

    result = pd.merge(
        grouped_meta,
        grouped_numeric,
        on=["device_name", "hour"],
        how="left"
    )

    result["time"] = result["hour"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")

    result = result.drop(columns=["hour"], errors="ignore")

    return result


# =========================
# OUTPUT WRITERS
# =========================
def write_history_csv(df, period_name):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    output_csv = DATA_DIR / f"sensor_history_{period_name}.csv"

    df.to_csv(output_csv, index=False)

    print(f"Wrote history CSV to {output_csv}")


def write_history_json(df, period_name):
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    output_json = WEB_DIR / f"sensor_history_{period_name}.json"

    records = []

    for _, row in df.iterrows():
        item = {}

        for col in df.columns:
            item[col] = clean_for_json(row[col])

        records.append(item)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print(f"Wrote history JSON to {output_json}")
    print(f"JSON records written: {len(records)}")


def write_empty_outputs(period_name):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    output_csv = DATA_DIR / f"sensor_history_{period_name}.csv"
    output_json = WEB_DIR / f"sensor_history_{period_name}.json"

    pd.DataFrame().to_csv(output_csv, index=False)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump([], f, indent=2)

    print(f"Wrote empty CSV to {output_csv}")
    print(f"Wrote empty JSON to {output_json}")


# =========================
# CONSOLE SUMMARY
# =========================
def print_summary(df, period_name):
    if df.empty:
        print(f"No data available for summary: {period_name}")
        return

    print(f"\nSummary for {period_name}")

    if "device_profile_name" in df.columns:
        print("\nDevice profile counts:")
        print(df["device_profile_name"].value_counts(dropna=False).to_string())

    if "device_name" in df.columns:
        print("\nRecords per device:")
        print(df["device_name"].value_counts(dropna=False).to_string())

    print("\nPreview of graphable fields:")

    cols = [
        "device_name",
        "device_profile_name",
        "site",
        "time",
        "temperature_c",
        "humidity",
        "air_temperature",
        "air_humidity",
        "pressure",
        "wind_speed",
        "wind_gust",
        "rain_gauge",
        "rain_accumulation",
        "tank_air_gap_mm",
        "tank_distance",
        "tank_temp_c",
        "battery_v",
        "tank_battery_v",
        "rssi",
        "snr"
    ]

    existing_cols = [col for col in cols if col in df.columns]

    print(
        df[existing_cols]
        .head(20)
        .to_string(index=False)
    )


# =========================
# PERIOD PROCESSOR
# =========================
def process_period(collection, period_name, period_delta):
    docs = fetch_period_records(collection, period_name, period_delta)

    if not docs:
        print(f"No records found for {period_name}.")
        write_empty_outputs(period_name)
        return

    rows = [flatten_doc(doc) for doc in docs]
    df = pd.DataFrame(rows)

    if not df.empty and "time" in df.columns:
        df = df.sort_values(["device_name", "time"], ascending=True)

    if period_name in ["6m", "12m", "all"]:
        df = downsample_long_record(df)

    write_history_csv(df, period_name)
    write_history_json(df, period_name)
    print_summary(df, period_name)


# =========================
# MAIN RUNNER
# =========================
def run_once():
    if not URI:
        raise ValueError(
            "MONGODB_URI environment variable is not set. "
            "Set it before running this script."
        )

    client = MongoClient(URI, server_api=ServerApi("1"))
    client.admin.command("ping")

    print("Connected to MongoDB")

    db = client[DB_NAME]
    collection = db[COLLECTION_NAME]

    for period_name, period_delta in PERIODS.items():
        process_period(collection, period_name, period_delta)

    print("\nFinished writing all sensor history outputs.")


if __name__ == "__main__":
    try:
        run_once()
    except Exception as e:
        print("ETL stats failed:", e)