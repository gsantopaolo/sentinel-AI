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

    def ensure_collection_exists(self) -> None:
        """Ensure the specified collection exists with proper configuration.

        If the collection already exists, it will be deleted and recreated to ensure
        it matches the current model's vector configuration. This is a robust
        approach to prevent configuration mismatch errors.

        Raises:
            RuntimeError: If there's an error creating or verifying the collection.
        """
        self.logger.info(f"🔍 Ensuring collection '{self.collection_name}' is correctly configured...")
        try:
            if self.client.collection_exists(collection_name=self.collection_name):
                self.logger.warning(
                    f"🗑️ Collection '{self.collection_name}' already exists. "
                    f"Recreating it to ensure vector configuration is up-to-date."
                )
                self.client.delete_collection(collection_name=self.collection_name)

            self.logger.info(f"🆕 Creating collection '{self.collection_name}' with vector size {self.vector_size}")
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=models.Distance.COSINE
                )
            )
            self._create_collection_indexes()
            self.logger.info(f"✅ Successfully created and configured collection '{self.collection_name}'")

        except Exception as e:
            error_msg = f"❌ Failed to ensure collection '{self.collection_name}' exists: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from e

    async def list_filtered_events(self, limit: int = 20, offset: int = 0):
        """List events that are marked as relevant but not yet ranked."""
        self.logger.info(f"📋 Listing filtered events (limit={limit}, offset={offset})")
        try:
            loop = asyncio.get_event_loop()
            records, next_page = await loop.run_in_executor(
                None,
                lambda: self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=models.Filter(
                        must=[
                            models.FieldCondition(key="is_relevant", match=models.MatchValue(value=True)),
                            # Must NOT have a final_score
                            models.IsEmptyCondition(is_empty=models.PayloadField(key="final_score"))
                        ]
                    ),
                    limit=limit,
                    offset=offset,
                    with_payload=True,
                    order_by=models.OrderBy(key="timestamp", direction=models.OrderDirection.DESC)
                )
            )
            return [r.payload for r in records], next_page
        except Exception as e:
            self.logger.error(f"❌ Failed to list filtered events: {e}", exc_info=True)
            raise RuntimeError("Failed to list filtered events") from e

    async def list_ranked_events(self, limit: int = 20, offset: int = 0):
        """List events that have been ranked, ordered by final_score."""
        self.logger.info(f"📋 Listing ranked events (limit={limit}, offset={offset})")
        try:
            loop = asyncio.get_event_loop()
            records, next_page = await loop.run_in_executor(
                None,
                lambda: self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=models.Filter(
                        must_not=[
                            # Must have a final_score
                            models.IsEmptyCondition(is_empty=models.PayloadField(key="final_score"))
                        ]
                    ),
                    limit=limit,
                    offset=offset,
                    with_payload=True,
                    order_by=models.OrderBy(key="final_score", direction=models.OrderDirection.DESC)
                )
            )
            return [r.payload for r in records], next_page
        except Exception as e:
            self.logger.error(f"❌ Failed to list ranked events: {e}", exc_info=True)
            raise RuntimeError("Failed to list ranked events") from e

    async def search_events_by_keyword(self, query: str, limit: int = 10):
        """Search for events using a full-text search on the content."""
        self.logger.info(f"🔍 Keyword search for: '{query}'")
        try:
            loop = asyncio.get_event_loop()
            hits = await loop.run_in_executor(
                None,
                lambda: self.client.search(
                    collection_name=self.collection_name,
                    query_text=query,  # This uses the new full-text index
                    limit=limit,
                )
            )
            return [hit.payload for hit in hits]
        except Exception as e:
            self.logger.error(f"❌ Keyword search failed: {e}", exc_info=True)
            raise RuntimeError("Keyword search failed") from e

    def search_events(
            self,
            query_text: str,
            limit: int = 10,
            offset: int = 0,
            filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search for events using semantic similarity to the query text.

        Args:
            query_text (str): The text to search for.
            limit (int): Maximum number of results to return. Defaults to 10.
            offset (int): Number of results to skip. Defaults to 0.
            filters (Optional[Dict[str, Any]]): Optional filters to apply to the search.

        Returns:
            List[Dict[str, Any]]: List of search results with scores and payloads.

        Raises:
            RuntimeError: If there's an error during the search operation.
        """
        self.logger.info(f"🔍 Searching for: '{query_text[:50]}{'...' if len(query_text) > 50 else ''}'")

        if not query_text or not query_text.strip():
            self.logger.warning("⚠️ Empty search query provided")
            return []

        try:
            # Generate query embedding
            query_embedding = self.model.encode(query_text).tolist()

            # Build filters if provided
            qdrant_filters = None
            if filters:
                must_conditions = []
                for key, value in filters.items():
                    must_conditions.append(
                        qdrant_models.FieldCondition(
                            key=key,
                            match=qdrant_models.MatchValue(value=value)
                        )
                    )
                qdrant_filters = qdrant_models.Filter(must=must_conditions)

            # Execute search
            search_results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_embedding,
                query_filter=qdrant_filters,
                limit=limit,
                offset=offset,
                with_payload=True,
                with_vectors=False
            )

            # Format results
            results = [
                {
                    "id": hit.id,
                    "score": hit.score,
                    "payload": hit.payload
                }
                for hit in search_results
            ]

            self.logger.info(f"✅ Found {len(results)} results")
            return results

        except Exception as e:
            error_msg = f"❌ Search failed: {str(e)}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    async def retrieve_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single event by its ID."""
        if not event_id:
            self.logger.warning("⚠️ Cannot retrieve event: empty ID provided")
            return None

        self.logger.info(f"🔍 Retrieving event ID: {event_id}")

        try:
            loop = asyncio.get_event_loop()

            # The scroll method returns a tuple: (list_of_records, next_page_offset)
            records, _ = await loop.run_in_executor(
                None,
                lambda: self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="original_id",
                                match=models.MatchValue(value=str(event_id))
                            )
                        ]
                    ),
                    limit=1,
                    with_payload=True,
                    with_vectors=False
                )
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
        """Retrieve all events from the collection with pagination.

        Args:
            limit (int): Maximum number of events to return. Defaults to 100.
            offset (int): Number of events to skip. Defaults to 0.

        Returns:
            List[Dict[str, Any]]: List of event payloads.

        Raises:
            RuntimeError: If there's an error retrieving events.
        """
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
        """Upsert an event into the Qdrant collection.

        If an event with the same ID exists, it will be updated. Otherwise, a new event will be created.

        Args:
            event_data (Dict[str, Any]): The event data to upsert. Must contain 'id' and 'content'.

        Returns:
            bool: True if the operation was successful, False otherwise.

        Raises:
            ValueError: If required fields are missing.
        """
        event_id = event_data.get('id', 'N/A')
        self.logger.info(f"📥 Received upsert event: {event_id} (store entity inside the vector db)")

        # Validate input
        if not event_id or event_id == 'N/A':
            error_msg = "Event data must contain a valid 'id' field"
            self.logger.error(f"❌ {error_msg}")
            return False

        if "content" not in event_data:
            error_msg = f"Event {event_id} missing 'content' field, cannot generate embedding"
            self.logger.error(f"❌ {error_msg}")
            return False

        try:
            # Generate embedding from content
            content = event_data["content"]
            # Run the CPU-bound operation in a thread pool
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(
                None,
                lambda: self.model.encode(content).tolist()
            )

            # Create point structure with hashed ID
            point_id = self._hash_id(str(event_id))
            point = models.PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    **event_data,
                    "original_id": str(event_id)  # Ensure original_id is always a string
                }
            )

            # Execute upsert in a thread since the Qdrant client is synchronous
            await loop.run_in_executor(
                None,
                lambda: self.client.upsert(
                    collection_name=self.collection_name,
                    points=[point],
                    wait=True
                )
            )

            self.logger.info(f"✅ Successfully upserted event: {event_id}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Failed to upsert event {event_id}: {str(e)}", exc_info=True)
            return False

    async def delete_events(self, ids: List[str]) -> int:
        """Delete multiple events by their original string IDs.

        Args:
            ids (List[str]): List of event IDs to delete.

        Returns:
            int: Number of events successfully deleted.

        Raises:
            ValueError: If no IDs are provided.
            RuntimeError: If there's an error during deletion.
        """
        if not ids:
            raise ValueError("No IDs provided for deletion")

        self.logger.info(f"🗑️ Deleting {len(ids)} events")

        try:
            loop = asyncio.get_event_loop()

            # Delete by filtering on the original_id field
            operations = []
            for id_ in ids:
                operations.append(
                    models.DeleteOperation(
                        delete=models.PointsSelector(
                            filter_=models.Filter(
                                must=[
                                    models.FieldCondition(
                                        key="original_id",
                                        match=models.MatchValue(value=str(id_))  # Ensure string comparison
                                    )
                                ]
                            )
                        )
                    )
                )

            # Execute batch delete in a thread since the Qdrant client is synchronous
            await loop.run_in_executor(
                None,
                lambda: self.client.batch(
                    collection_name=self.collection_name,
                    operations=operations
                )
            )

            self.logger.info(f"✅ Deleted {len(ids)} events")
            return len(ids)

        except Exception as e:
            error_msg = f"❌ Failed to delete events: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from e

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

    def _hash_id(self, id_str: str) -> int:
        """Convert a string ID to a consistent positive integer hash for Qdrant.

        Args:
            id_str: The string ID to hash.

        Returns:
            int: A positive 63-bit integer hash of the input string.
        """
        # Use SHA-256 and take the first 8 bytes (64 bits) for the hash
        hash_bytes = hashlib.sha256(id_str.encode('utf-8')).digest()[:8]
        # Convert to a positive 63-bit integer to ensure it's within Qdrant's limits
        return int.from_bytes(hash_bytes, byteorder='big') & 0x7FFFFFFFFFFFFFFF

    def _create_collection_indexes(self):
        """Create necessary indexes on the collection for better query performance.

        This is an internal method called during collection creation.
        """
        try:
            # Create index on the 'source' field for faster filtering
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="source",
                field_schema=models.PayloadSchemaType.KEYWORD
            )
            self.logger.info("✅ Created index on 'source' field")

            # Index for sorting/filtering ranked events
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="final_score",
                field_schema=models.PayloadSchemaType.FLOAT
            )
            self.logger.info("✅ Created index on 'final_score' field")

            # Index for sorting by timestamp
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="timestamp",
                field_schema=models.PayloadSchemaType.DATETIME
            )
            self.logger.info("✅ Created index on 'timestamp' field")

            # Index for full-text search
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="content",
                field_schema=models.TextIndexParams(
                    type="text",
                    tokenizer=models.TokenizerType.WORD,
                    min_token_len=2,
                    max_token_len=15,
                    lowercase=True
                )
            )
            self.logger.info("✅ Created text index on 'content' field")

            self.logger.info("✅ Created collection indexes")
        except Exception as e:
            self.logger.warning(f"Could not create payload index: {e}")
