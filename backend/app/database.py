from pymongo import ASCENDING, MongoClient
from pymongo.server_api import ServerApi

from .config import MONGODB_DATABASE, MONGODB_URI

client = MongoClient(MONGODB_URI, server_api=ServerApi("1"), serverSelectionTimeoutMS=10000)
database = client[MONGODB_DATABASE]
users = database["users"]


def initialize_database() -> None:
    client.admin.command("ping")
    users.create_index([("username_key", ASCENDING)], unique=True)
    users.create_index([("email_key", ASCENDING)], unique=True)
