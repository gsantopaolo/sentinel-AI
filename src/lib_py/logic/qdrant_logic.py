import logging
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class QdrantLogic:
    def __init__(self, host: str, port: int, collection_name: str, embedding_model_name: str):
        self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection_name
        self.model = SentenceTransformer(embedding_model_name)
        self.vector_size = self.model.get_sentence_embedding_dimension()
        logger.info(f"🗄️ QdrantLogic initialized for collection '{collection_name}' with model '{embedding_model_name}'.")

    def ensure_collection_exists(self):
        logger.info(f"🗄️ Ensuring collection '{self.collection_name}' exists...")
        try:
            self.client.recreate_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(size=self.vector_size, distance=models.Distance.COSINE),
            )
            logger.info(f"✅ Collection '{self.collection_name}' ensured to exist.")
        except Exception as e:
            logger.error(f"❌ Error ensuring Qdrant collection exists: {e}")
            raise

    def search_events(self, query_text: str, limit: int = 10, offset: int = 0, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        logger.info(f"🗄️ Searching Qdrant for query: '{query_text}' in collection '{self.collection_name}'.")
        query_embedding = self.model.encode(query_text).tolist()

        qdrant_filters = None
        if filters:
            # Example of converting a simple dict filter to Qdrant Filter
            # This needs to be expanded based on actual filter requirements
            must_conditions = []
            for key, value in filters.items():
                must_conditions.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
            qdrant_filters = models.Filter(must=must_conditions)

        try:
            search_result = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                query_args=models.QueryParams(consistency=models.ReadConsistency.STRONG),
                limit=limit,
                offset=offset,
                query_filter=qdrant_filters
            )
            logger.info(f"✅ Found {len(search_result)} results for query '{query_text}'.")
            return [{"id": hit.id, "score": hit.score, "payload": hit.payload.dict()} for hit in search_result]
        except Exception as e:
            logger.error(f"❌ Error searching Qdrant: {e}")
            raise

    def retrieve_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        logger.info(f"🗄️ Retrieving event with ID: '{event_id}' from collection '{self.collection_name}'.")
        try:
            # Qdrant's retrieve method expects a list of IDs
            result = self.client.retrieve(
                collection_name=self.collection_name,
                ids=[event_id],
                with_payload=True,
                with_vectors=False
            )
            if result:
                logger.info(f"✅ Event with ID '{event_id}' retrieved successfully.")
                return result[0].payload.dict()
            else:
                logger.warning(f"⚠️ Event with ID '{event_id}' not found.")
                return None
        except Exception as e:
            logger.error(f"❌ Error retrieving event by ID from Qdrant: {e}")
            raise

    def get_all_events(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        logger.info(f"🗄️ Retrieving all events from collection '{self.collection_name}'. Limit: {limit}, Offset: {offset}")
        try:
            scroll_result, _ = self.client.scroll(
                collection_name=self.collection_name,
                limit=limit,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )
            logger.info(f"✅ Retrieved {len(scroll_result)} events from Qdrant.")
            return [point.payload.dict() for point in scroll_result]
        except Exception as e:
            logger.error(f"❌ Error retrieving all events from Qdrant: {e}")
            raise

    def upsert_event(self, event_data: Dict[str, Any]):
        logger.info(f"🗄️ Upserting event with ID: '{event_data.get("id", "N/A")}' to collection '{self.collection_name}'.")
        try:
            # Ensure 'text' key exists for embedding
            if "content" not in event_data:
                logger.warning(f"⚠️ Event {event_data.get("id", "N/A")} missing 'content' field, skipping embedding.")
                raise ValueError("Event data must contain a 'content' field for embedding.")

            embedding = self.model.encode(event_data["content"]).tolist()
            point = models.PointStruct(
                id=event_data["id"],  # Assuming 'id' is always present and unique
                vector=embedding,
                payload=event_data
            )
            self.client.upsert(
                collection_name=self.collection_name,
                wait=True,
                points=[point]
            )
            logger.info(f"✅ Event '{event_data["id"]}' upserted successfully.")
        except Exception as e:
            logger.error(f"❌ Error upserting event '{event_data.get("id", "N/A")}' to Qdrant: {e}")
            raise

    def delete_events(self, ids: List[str]):
        logger.info(f"🗄️ Deleting events with IDs: {ids} from collection '{self.collection_name}'.")
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=ids)
            )
            logger.info(f"✅ Deleted {len(ids)} events from collection '{self.collection_name}'.")
        except Exception as e:
            logger.error(f"❌ Error deleting events from Qdrant: {e}")
            raise

    def count_events(self) -> int:
        logger.info(f"🗄️ Counting events in collection '{self.collection_name}'.")
        try:
            count_result = self.client.count(collection_name=self.collection_name, exact=True)
            logger.info(f"✅ Total events in collection '{self.collection_name}': {count_result.count}.")
            return count_result.count
        except Exception as e:
            logger.error(f"❌ Error counting events in Qdrant: {e}")
            raise
