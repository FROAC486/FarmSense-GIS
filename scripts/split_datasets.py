import pandas as pd

# Read the master ETL output
df = pd.read_csv("sensor_observations.csv")

# Known bad / legacy sensor to exclude from clean environmental output
bad_sensor = "LST25598095"

# Make sure expected columns exist
expected_cols = [
    "device_name", "dev_eui", "device_profile_name", "site",
    "sensor_latitude", "sensor_longitude", "sensor_altitude", "sensor_geojson",
    "time", "iso", "ts",
    "temperature_c", "humidity", "battery_v",
    "tank_distance", "tank_battery_v", "tank_temp_c",
    "air_temperature", "air_humidity", "light_intensity", "uv_index",
    "wind_speed", "wind_direction", "rain_gauge", "rain_accumulation",
    "pressure", "wind_gust"
]

for col in expected_cols:
    if col not in df.columns:
        df[col] = pd.NA

# 1. Sensor inventory
sensor_inventory = (
    df[
        [
            "device_name",
            "dev_eui",
            "device_profile_name",
            "site",
            "sensor_latitude",
            "sensor_longitude",
            "sensor_altitude",
            "sensor_geojson",
        ]
    ]
    .drop_duplicates()
    .sort_values(["device_profile_name", "device_name"], na_position="last")
    .reset_index(drop=True)
)

# 2. Environmental data
environmental_data = df[
    [
        "time",
        "iso",
        "ts",
        "device_name",
        "dev_eui",
        "device_profile_name",
        "site",
        "sensor_latitude",
        "sensor_longitude",
        "sensor_altitude",
        "sensor_geojson",
        "temperature_c",
        "humidity",
        "battery_v",
    ]
].copy()

environmental_data = environmental_data[
    environmental_data["temperature_c"].notna() | environmental_data["humidity"].notna()
]

environmental_data = environmental_data[
    environmental_data["device_name"] != bad_sensor
].reset_index(drop=True)

# 3. Tank data
tank_data = df[
    [
        "time",
        "iso",
        "ts",
        "device_name",
        "dev_eui",
        "device_profile_name",
        "site",
        "sensor_latitude",
        "sensor_longitude",
        "sensor_altitude",
        "sensor_geojson",
        "tank_distance",
        "tank_battery_v",
        "tank_temp_c",
    ]
].copy()

tank_data = tank_data[tank_data["tank_distance"].notna()].reset_index(drop=True)

# 4. Weather data
weather_data = df[
    [
        "time",
        "iso",
        "ts",
        "device_name",
        "dev_eui",
        "device_profile_name",
        "site",
        "sensor_latitude",
        "sensor_longitude",
        "sensor_altitude",
        "sensor_geojson",
        "air_temperature",
        "air_humidity",
        "light_intensity",
        "uv_index",
        "wind_speed",
        "wind_direction",
        "rain_gauge",
        "rain_accumulation",
        "pressure",
        "wind_gust",
    ]
].copy()

weather_measurement_cols = [
    "air_temperature",
    "air_humidity",
    "light_intensity",
    "uv_index",
    "wind_speed",
    "wind_direction",
    "rain_gauge",
    "rain_accumulation",
    "pressure",
    "wind_gust",
]

weather_data = weather_data[
    weather_data[weather_measurement_cols].notna().any(axis=1)
].reset_index(drop=True)

# Write the 4 CSV files
sensor_inventory.to_csv("sensor_inventory.csv", index=False)
environmental_data.to_csv("environmental_data.csv", index=False)
tank_data.to_csv("tank_data.csv", index=False)
weather_data.to_csv("weather_data.csv", index=False)

# Print summary
print("Created files successfully:")
print(f"sensor_inventory.csv: {len(sensor_inventory)} rows")
print(f"environmental_data.csv: {len(environmental_data)} rows")
print(f"tank_data.csv: {len(tank_data)} rows")
print(f"weather_data.csv: {len(weather_data)} rows")