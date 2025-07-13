import qdrant_client
from qdrant_client.http.models import Distance, VectorParams, PointStruct
import os
from dotenv import load_dotenv

load_dotenv()

class QdrantHandler:
    def __init__(self):
        self.host = os.getenv("QDRANT_HOST")
        self.port = os.getenv("QDRANT_PORT")
        self.client = qdrant_client.QdrantClient(host=self.host, port=self.port)
        self.collection_name = "newsfeed"

    def setup_collection(self):
        """Creates the collection in Qdrant if it doesn't exist."""
        try:
            self.client.get_collection(collection_name=self.collection_name)
            print(f"Collection '{self.collection_name}' already exists.")
        except Exception:
            self.client.recreate_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=1536, distance=Distance.COSINE), # Assuming OpenAI embeddings size
            )
            print(f"Collection '{self.collection_name}' created.")

    def add_points(self, points: list[PointStruct]):
        """Adds points to the collection."""
        self.client.upsert(
            collection_name=self.collection_name,
            wait=True,
            points=points
        )
        print(f"Upserted {len(points)} points to collection '{self.collection_name}'.")
