import pandas as pd

df = pd.read_csv("sensor_observations.csv")

print("\n--- UNIQUE SITES ---")
print(df["site"].dropna().unique())

print("\n--- DEVICE COUNT ---")
print(df["device_name"].nunique(), "devices")

print("\n--- DEVICE → SITE ---")
print(df[["device_name", "site"]].drop_duplicates().to_string(index=False))

print("\n--- LOCATION CHECK ---")
print(df[["device_name", "sensor_latitude", "sensor_longitude"]]
      .drop_duplicates()
      .to_string(index=False))

print("\n--- TEMPERATURE DATA ---")
print(df[df["temperature_c"].notna()][
    ["device_name", "temperature_c"]
].head())

print("\n--- HUMIDITY DATA ---")
print(df[df["humidity"].notna()][
    ["device_name", "humidity"]
].head())

print("\n--- TANK DATA (DDS75) ---")
print(df[df["tank_distance"].notna()][
    ["device_name", "tank_distance"]
].head())