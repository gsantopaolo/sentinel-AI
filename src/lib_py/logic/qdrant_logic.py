import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient, models
from qdrant_client.http import models as qdrant_models
from sentence_transformers import SentenceTransformer


class QdrantLogic:
    """
    A class to handle all Qdrant vector database operations with consistent error handling and logging.

    Attributes:
        client (QdrantClient): The Qdrant client instance.
        collection_name (str): Name of the Qdrant collection.
        model (SentenceTransformer): Model for generating text embeddings.
        vector_size (int): Dimensionality of the vector embeddings.
        logger (logging.Logger): Logger instance for this class.
    """

    def __init__(self, host: str, port: int, collection_name: str, embedding_model_name: str):
        """Initialize the QdrantLogic with connection parameters and model.

        Args:
            host (str): Qdrant server hostname or IP.
            port (int): Qdrant server port.
            collection_name (str): Name of the collection to work with.
            embedding_model_name (str): Name of the SentenceTransformer model to use.
        """
        self.client = QdrantClient(host=host, port=port)
        self.collection_name = collection_name
        self.model = SentenceTransformer(embedding_model_name)
        self.vector_size = self.model.get_sentence_embedding_dimension()
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"🗄️ Initializing QdrantLogic for collection '{collection_name}' with model '{embedding_model_name}'")

        # Ensure the collection and its indexes exist (final_score, timestamp, content)
        try:
            self.initialize_collection()
        except Exception as e:
            # Do not fail hard on startup; log and continue. Queries that rely on missing indexes
            # will be handled gracefully by sorting client-side.
            self.logger.warning(f"⚠️ Could not verify/create collection indexes: {e}")

    def initialize_collection(self) -> None:
        try:
            # Create collection if it does not exist
            if not self.client.collection_exists(collection_name=self.collection_name):
                self.logger.info(f"Collection '{self.collection_name}' not found. Creating collection.")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(size=self.vector_size, distance=models.Distance.COSINE),
                )
                self.logger.info(f"Collection '{self.collection_name}' created successfully.")

            # Get existing collection info to check for indexes
            collection_info = self.client.get_collection(collection_name=self.collection_name)
            existing_indexes = set(collection_info.payload_schema.keys())
            self.logger.debug(f"Existing payload indexes: {existing_indexes}")

            # Define required indexes
            required_indexes = {
                "final_score": models.PayloadSchemaType.FLOAT,
                "timestamp": models.PayloadSchemaType.DATETIME,
                "content": qdrant_models.TextIndexParams(
                    type=qdrant_models.TextIndexType.TEXT,
                    tokenizer=qdrant_models.TokenizerType.WHITESPACE,
                    min_token_len=2,
                    max_token_len=20,
                    lowercase=True
                )
            }

            # Create any missing indexes
            for field_name, field_schema in required_indexes.items():
                if field_name not in existing_indexes:
                    self.logger.info(f"Index for '{field_name}' not found. Creating and waiting for completion...")
                    self.client.create_payload_index(
                        collection_name=self.collection_name,
                        field_name=field_name,
                        field_schema=field_schema,
                        wait=True,  # Wait for the index to be ready
                    )
                    self.logger.info(f"✅ Index for '{field_name}' is ready.")
            self.logger.info("✅ All required indexes are present.")

        except Exception as e:
            self.logger.error(f"❌ Failed to initialize collection: {e}", exc_info=True)
            raise

    def ensure_collection_exists(self) -> None:
        """Legacy alias for `initialize_collection` retained for backward-compatibility.

        Several micro-services (e.g. `filter`, `inspector`) still invoke
        `ensure_collection_exists()` on startup.  The underlying logic was
        renamed to `initialize_collection`, so this thin wrapper simply
        forwards the call, avoiding AttributeError and service restarts.
        """
        self.initialize_collection()

    async def list_filtered_events(self) -> List[Dict[str, Any]]:
        """List ALL events that are marked as relevant but not yet ranked."""
        self.logger.info("📋 Listing all filtered events with full pagination.")
        try:
            loop = asyncio.get_running_loop()
            all_records = []
            next_offset = None

            while True:
                records, next_offset = await loop.run_in_executor(
                    None,
                    lambda: self.client.scroll(
                        collection_name=self.collection_name,
                        scroll_filter=models.Filter(
                            must=[
                                models.FieldCondition(key="is_relevant", match=models.MatchValue(value=True)),
                                models.IsEmptyCondition(is_empty=models.PayloadField(key="final_score")),
                            ]
                        ),
                        limit=250,  # Fetch in batches of 250
                        offset=next_offset,
                        with_payload=True
                    )
                )
                all_records.extend(records)
                if next_offset is None:
                    break

            payloads = [r.payload for r in all_records]
            # Sort by timestamp descending in application code
            def _ts_val(p):
                ts = p.get("timestamp")
                if ts is None:
                    return 0
                if isinstance(ts, (int, float)):
                    return ts
                # assume ISO8601 string
                try:
                    from datetime import datetime
                    return datetime.fromisoformat(ts).timestamp()
                except Exception:
                    return 0
            payloads.sort(key=_ts_val, reverse=True)
            self.logger.info(f"✅ Found {len(payloads)} filtered events in total.")
            return payloads
        except Exception as e:
            self.logger.error(f"❌ Failed to list filtered events: {e}", exc_info=True)
            raise RuntimeError("Failed to list filtered events") from e

    async def list_ranked_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List events that have a final_score (i.e., are ranked)."""
        self.logger.info(f"📋 Listing ranked events (limit={limit})")
        try:
            loop = asyncio.get_running_loop()
            records, _ = await loop.run_in_executor(
                None,
                lambda: self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=models.Filter(
                        must=[
                            models.FieldCondition(key="final_score", range=models.Range(gte=0))
                        ]
                    ),
                    limit=limit,
                    with_payload=True
                    # order_by removed — we will sort client-side to avoid index issues
                )
            )
            payloads = [r.payload for r in records]
            # Ensure deterministic ordering by final_score descending
            payloads.sort(key=lambda p: p.get("final_score", 0), reverse=True)
            self.logger.info(f"✅ Found {len(payloads)} ranked events.")
            return payloads
        except Exception as e:
            self.logger.error(f"❌ Failed to list ranked events: {e}", exc_info=True)
            raise RuntimeError("Failed to list ranked events") from e

    async def list_all_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List the most recent events irrespective of ranking status."""
        self.logger.info(f"📋 Listing all events (limit={limit})")
        try:
            loop = asyncio.get_running_loop()
            records, _ = await loop.run_in_executor(
                None,
                lambda: self.client.scroll(
                    collection_name=self.collection_name,
                    limit=limit,
                    with_payload=True
                )
            )
            payloads = [r.payload for r in records]
            # Sort by timestamp descending if present
            def _ts(p):
                t = p.get("timestamp")
                if isinstance(t, (int, float)):
                    return t
                return 0
            payloads.sort(key=_ts, reverse=True)
            self.logger.info(f"✅ Found {len(payloads)} total events.")
            return payloads
        except Exception as e:
            self.logger.error(f"❌ Failed to list all events: {e}", exc_info=True)
            raise RuntimeError("Failed to list all events") from e

    async def search_events_by_keyword(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for events using a full-text search on the 'content' field."""
        self.logger.info(f"🔍 Keyword search for: '{query}'")
        try:
            loop = asyncio.get_running_loop()
            # Use full-text search via payload filter with MatchText – avoids requiring a query_vector
            records, _ = await loop.run_in_executor(
                None,
                lambda: self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="content",
                                match=models.MatchText(text=query)
                            )
                        ]
                    ),
                    limit=limit,
                    with_payload=True,
                )
            )
            return [rec.payload for rec in records]
        except Exception as e:
            self.logger.error(f"❌ Keyword search failed: {e}", exc_info=True)
            raise RuntimeError("Keyword search failed") from e

    async def search_events_by_vector(self, query_text: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for events using semantic similarity to the query text."""
        self.logger.info(f"🔍 Vector search for: '{query_text[:50]}...'" if len(query_text) > 50 else f"🔍 Vector search for: '{query_text}'")
        if not query_text or not query_text.strip():
            self.logger.warning("⚠️ Empty search query provided")
            return []

        try:
            loop = asyncio.get_running_loop()
            query_embedding = await loop.run_in_executor(None, lambda: self.model.encode(query_text).tolist())

            search_results = await loop.run_in_executor(
                None,
                lambda: self.client.search(
                    collection_name=self.collection_name,
                    query_vector=query_embedding,
                    limit=limit,
                    with_payload=True,
                )
            )
            results = [hit.payload for hit in search_results]
            self.logger.info(f"✅ Found {len(results)} vector search results")
            return results
        except Exception as e:
            self.logger.error(f"❌ Vector search failed: {e}", exc_info=True)
            raise RuntimeError("Vector search failed") from e

    async def retrieve_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single event by its ID."""
        if not event_id:
            self.logger.warning("⚠️ Cannot retrieve event: empty ID provided")
            return None

        self.logger.info(f"🔍 Retrieving event ID: {event_id}")

        try:
            loop = asyncio.get_running_loop()
            point_id = self._hash_id(str(event_id))
            records = await loop.run_in_executor(
                None,
                lambda: self.client.retrieve(collection_name=self.collection_name, ids=[point_id], with_payload=True)
            )

            if not records:
                self.logger.warning(f"⚠️ Event not found: {event_id}")
                return None

            self.logger.info(f"✅ Retrieved event: {event_id}")
            return records[0].payload

        except Exception as e:
            error_msg = f"❌ Failed to retrieve event {event_id}: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from e

    def get_all_events(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Retrieve all events from the collection with pagination."""
        self.logger.info(f"📋 Retrieving up to {limit} events (offset: {offset})")

        try:
            scroll_result, _ = self.client.scroll(
                collection_name=self.collection_name,
                limit=limit,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )

            events = [point.payload for point in scroll_result]
            self.logger.info(f"✅ Retrieved {len(events)} events")
            return events

        except Exception as e:
            error_msg = f"❌ Failed to retrieve events: {str(e)}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    async def upsert_event(self, event_data: Dict[str, Any]) -> bool:
        """Upsert or partially update an event.

        Behaviour:
        1. If *content* is present ⇒ full upsert with vector (embedding generated).
        2. If *content* missing  ⇒ assume only payload fields must be patched; we
           call Qdrant `set_payload` for the existing point.  No vector is
           created, so the record *must* already exist.
        """
        event_id = event_data.get('id', 'N/A')
        self.logger.info("📥 Received upsert event: %s", event_id)

        if not event_id or event_id == 'N/A':
            self.logger.error("❌ Event data must contain a valid 'id'")
            return False

        try:
            loop = asyncio.get_running_loop()
            point_id = self._hash_id(str(event_id))

            # Full insert/update when we have content
            if 'content' in event_data and event_data['content']:
                content = event_data['content']
                embedding = await loop.run_in_executor(None, lambda: self.model.encode(content).tolist())
                point = models.PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={**event_data, "original_id": str(event_id)},
                )
                await loop.run_in_executor(
                    None,
                    lambda: self.client.upsert(
                        collection_name=self.collection_name, points=[point], wait=True
                    ),
                )
                self.logger.info("✅ Vector+payload upserted for event %s", event_id)
                return True

            # --- Payload-only patch (no vector) ---
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda: self.client.set_payload(
                        collection_name=self.collection_name,
                        payload=event_data,
                        points=[point_id],
                        wait=True,
                    ),
                )
                if result.status == qdrant_models.UpdateStatus.COMPLETED:
                    self.logger.info("✅ Payload updated for event %s (no embedding)", event_id)
                    return True
                else:
                    self.logger.warning(
                        "⚠️ set_payload status %s for event %s; falling back to fresh point upsert",
                        result.status,
                        event_id,
                    )
            except Exception as e:
                # Typical when point doesn't exist (404)
                self.logger.warning(
                    "⚠️ set_payload failed for event %s (%s); inserting new stub point", event_id, e
                )

            # fall back: create dummy vector (zeros) to insert new point
            dummy_vector = [0.0] * self.vector_size
            point = models.PointStruct(
                id=point_id,
                vector=dummy_vector,
                payload={**event_data, "original_id": str(event_id)},
            )
            await loop.run_in_executor(
                None,
                lambda: self.client.upsert(
                    collection_name=self.collection_name, points=[point], wait=True
                ),
            )
            self.logger.info("✅ Inserted new stub point for event %s", event_id)
            return True

        except Exception as e:
            self.logger.error("❌ Failed to upsert/update event %s: %s", event_id, str(e), exc_info=True)
            return False

    async def delete_events(self, ids: List[str]) -> int:
        """Delete multiple events by their original string IDs."""
        if not ids:
            raise ValueError("No IDs provided for deletion")

        self.logger.info(f"🗑️ Deleting {len(ids)} events")

        try:
            loop = asyncio.get_running_loop()
            point_ids = [self._hash_id(str(id_)) for id_ in ids]

            result = await loop.run_in_executor(
                None,
                lambda: self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=models.PointIdsList(points=point_ids),
                    wait=True
                )
            )

            if result.status == qdrant_models.UpdateStatus.COMPLETED:
                self.logger.info(f"✅ Successfully deleted {len(ids)} events")
                return len(ids)
            else:
                self.logger.warning(f"⚠️ Deletion status: {result.status}")
                return 0

        except Exception as e:
            self.logger.error(f"❌ Failed to delete events: {e}", exc_info=True)
            raise RuntimeError("Failed to delete events") from e

    def _hash_id(self, event_id: str) -> str:
        """Create a consistent UUID from a string ID."""
        hashed = hashlib.sha256(event_id.encode('utf-8')).hexdigest()
        return f"{hashed[:8]}-{hashed[8:12]}-{hashed[12:16]}-{hashed[16:20]}-{hashed[20:32]}"

    def count_events(self) -> int:
        """Count the total number of events in the collection.

        Returns:
            int: The total count of events.

        Raises:
            RuntimeError: If there's an error counting events.
        """
        self.logger.info("🔢 Counting events in collection...")

        try:
            count_result = self.client.count(
                collection_name=self.collection_name,
                exact=True
            )

            count = count_result.count
            self.logger.info(f"📊 Found {count} events in collection")
            return count

        except Exception as e:
            error_msg = f"❌ Failed to count events: {str(e)}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg) from e
