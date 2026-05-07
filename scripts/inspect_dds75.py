from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi
import pprint
import os

URI = os.getenv("MONGODB_URI")
DB_NAME = "iot"
COLLECTION_NAME = "sensordata"

client = MongoClient(URI, server_api=ServerApi("1"))
db = client["iot"]
collection = db["sensordata"]

doc = collection.find_one({"deviceInfo.deviceProfileName": "DDS75"})

print("DDS75 sample object:")
pprint.pprint(doc.get("object", {}))