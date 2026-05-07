from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import pandas as pd

uri = "mongodb+srv://oliver:uKQbTX8ebb1zGVFy@cluster0.cvmjitc.mongodb.net/?appName=Cluster0"

client = MongoClient(uri, server_api=ServerApi('1'))

try:
    client.admin.command('ping')
    print("Connected to MongoDB")

    db = client["iot"]
    collection = db["sensordata"]

    docs = collection.find()

    sensor_locations = {}

    for doc in docs:
        device_info = doc.get("deviceInfo", {})
        rx_info = doc.get("rxInfo", [])

        device_name = device_info.get("deviceName")
        dev_eui = device_info.get("devEui")

        lat = None
        lon = None
        alt = None

        if rx_info and "location" in rx_info[0]:
            loc = rx_info[0]["location"]
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            alt = loc.get("altitude")

        if device_name and dev_eui:
            key = dev_eui

            if key not in sensor_locations:
                sensor_locations[key] = {
                    "device_name": device_name,
                    "dev_eui": dev_eui,
                    "latitude": lat,
                    "longitude": lon,
                    "altitude": alt
                }

            else:
                if sensor_locations[key]["latitude"] is None and lat is not None:
                    sensor_locations[key]["latitude"] = lat
                if sensor_locations[key]["longitude"] is None and lon is not None:
                    sensor_locations[key]["longitude"] = lon
                if sensor_locations[key]["altitude"] is None and alt is not None:
                    sensor_locations[key]["altitude"] = alt

    df = pd.DataFrame(sensor_locations.values())
    print(df)

    df.to_csv("sensor_locations.csv", index=False)
    print("Saved sensor_locations.csv")

except Exception as e:
    print("Connection failed:", e)