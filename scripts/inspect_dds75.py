from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import pprint

URI = "mongodb+srv://oliver:uKQbTX8ebb1zGVFy@cluster0.cvmjitc.mongodb.net/?appName=Cluster0"

client = MongoClient(URI, server_api=ServerApi("1"))
db = client["iot"]
collection = db["sensordata"]

doc = collection.find_one({"deviceInfo.deviceProfileName": "DDS75"})

print("DDS75 sample object:")
pprint.pprint(doc.get("object", {}))