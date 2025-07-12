import os
import sys
import logging
import time
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
from typing import List, Dict
import PyPDF2
import numpy as np

load_dotenv(find_dotenv()) # also search parent dirs for .env

local_model_path = os.getenv("LOCAL_MODEL_PATH")
CACHE_ROOT = Path(os.getenv(local_model_path, "../data/models")).resolve()
os.environ["HF_HOME"] = str(CACHE_ROOT)
os.environ["HF_HUB_CACHE"] = str(CACHE_ROOT)
# os.environ["TRANSFORMERS_CACHE"] = str(CACHE_ROOT)
os.environ["FASTEMBED_CACHE"] = str(CACHE_ROOT)   # optional
HF_EMBEDDING_MODEL = os.environ["HF_EMBEDDING_MODEL"]
Q_EMBEDDING_MODEL = os.getenv("QDRANT_EMBEDDING_MODEL")
EMBEDDING_MODEL_DIMENSION = int(os.environ["EMBEDDING_MODEL_DIMENSION"])


from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models
from fastembed import TextEmbedding
from fastembed.common.model_description import PoolingType, ModelSource
import torch


log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)
# get log format from env
log_format = os.getenv('LOG_FORMAT', '%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(message)s')
# Configure logging
logging.basicConfig(level=log_level, format=log_format)

logger = logging.getLogger(__name__)

qdrant_host = os.getenv("QDRANT_HOST", "localhost")
qdrant_port = int(os.getenv("QDRANT_PORT", 6333))

# Function to read PDF and extract text
def extract_text_from_pdf(path: str) -> str:
    logger.info(f"📚 opening pdf: {path}")
    text = []
    start_time = time.perf_counter()
    with open(path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            logger.info(f"🗒️ page {i+1}: {len(page_text)} characters extracted")
            text.append(page_text)
    end_time = time.perf_counter()
    logger.info(f"👉👉👉 ⏱️ total time to open pdf: {end_time - start_time:.3f} (s.ms)")
    return "\n".join(text)

# Semantic chunking into overlapping token windows
def chunk_text(text: str, max_tokens: int = 500, overlap_tokens: int = 50) -> List[str]:
    tokens = text.split()
    chunks = []
    start = 0
    total_tokens = len(tokens)
    start_time = time.perf_counter()
    while start < total_tokens:
        end = min(start + max_tokens, total_tokens)
        chunk = " ".join(tokens[start:end])
        logger.info(f"✂️ chunk tokens {start}-{end} (length={len(chunk.split())})")
        chunks.append(chunk)
        if end == total_tokens:
            break
        start = end - overlap_tokens
    end_time = time.perf_counter()
    logger.info(f"✨ Total chunks created: {len(chunks)}")
    logger.info(f"👉👉👉 ⏱️ total chunking time: {end_time - start_time:.3f} (s.ms)")
    return chunks

def recreate_collection(client: QdrantClient, model_name:str, collection: str):
    """Drop *name* if it exists and create a fresh collection."""
    if client.collection_exists(collection):
        logging.info(f"🗑️ deleting existing collection '{collection}' (incompatible vectors)")
        start = time.perf_counter()
        client.delete_collection(collection_name=collection)
        end = time.perf_counter()
        logger.info(f"👉👉👉 ⏱️ total time to delete collection: {end - start:.3f} (s.ms)")

    # todo: important, verify hnsw_config inside vector_config
    start = time.perf_counter()
    vectors_cfg = client.get_fastembed_vector_params()  # includes the model name key
    client.create_collection(collection_name=collection,
                             vectors_config=vectors_cfg)
    # client.create_collection(
    #     collection_name=collection,
        # vectors_config=models.VectorParams(
        #     size=EMBEDDING_MODEL_DIMENSION, distance=models.Distance.COSINE)
        #     # size=client.get_embedding_size(model_name), distance=models.Distance.COSINE)
    # )
    end = time.perf_counter()
    logger.info(f"📚 collection '{collection}' ready")
    logger.info(f"👉👉👉 ⏱️ total time to create collection: {end - start:.3f} (s.ms)")

def store_chunks_fastembed(chunks: List[str], collection_name: str, metadata: List[Dict]):

    if not Q_EMBEDDING_MODEL:
        logger.error("🛑 QDRANT_EMBEDDING_MODEL is not set in .env")
        sys.exit(1)
    logger.info(f"🤖 using qdrant embedding model: {Q_EMBEDDING_MODEL}")

    custom_model_name = "my_model_quadrant"

    # register a custom model to avid fastembedd warning
    # Warning: The model intfloat/multilingual-e5-large now uses mean pooling instead of CLS embedding. In order to preserve the previous behaviour, consider either pinning fastembed version to 0.5.1 or using `add_custom_model` functionality.
    #  model = TextEmbedding(model_name=model_name, **options)
    TextEmbedding.add_custom_model(
        model=custom_model_name,
        pooling=PoolingType.MEAN,
        normalization=True,
        sources=ModelSource(hf=Q_EMBEDDING_MODEL),
        dim=EMBEDDING_MODEL_DIMENSION,
        model_file="model.onnx",  # match repository root
        additional_files=["model.onnx_data"],  # download the external-data file
    )

    client = QdrantClient(url=qdrant_host, port=qdrant_port, prefer_grpc=True)
    client.set_model(embedding_model_name=custom_model_name, cache_dir=str(CACHE_ROOT))
    recreate_collection(client, custom_model_name, collection_name)

    logger.info(f"💾 storing {len(chunks)} chunks into collection '{collection_name}'")

    # FastEmbed mixin: embed & upsert in one call
    ids = list(range(1, len(chunks) + 1))
    client.add(
        collection_name=collection_name,
        documents=chunks,
        metadata=metadata,
        ids=ids
    )
    logger.info("✅ storage complete")

def recreate_collection_for_hf(client: QdrantClient, collection: str):
    # Delete if it already exists
    if client.collection_exists(collection):
        client.delete_collection(collection_name=collection)

    # Create a collection with a single vector named "vector"
    client.create_collection(
        collection_name=collection,
        vectors_config=models.VectorParams(
            size=EMBEDDING_MODEL_DIMENSION,
            distance=models.Distance.COSINE,
        ),
    )
    logger.info(f"📚 collection '{collection}' ready")


def store_embeddings(embeddings: np.ndarray, metadata: List[Dict], collection: str, batch_size: int = 32):
    """Upsert *embeddings* with *metadata* into Qdrant *collection*."""

    custom_model_name = HF_EMBEDDING_MODEL


    client = QdrantClient(url=qdrant_host, port=qdrant_port, prefer_grpc=True)
    # client.set_model(embedding_model_name=custom_model_name, cache_dir=str(CACHE_ROOT))

    recreate_collection_for_hf(client, collection)
    start = time.perf_counter()

    # 2) Build PointStructs
    points = [
        models.PointStruct(
            id=i,
            vector=embeddings[i].tolist(),  # this goes into the "vector" field
            payload=metadata[i],
        )
        for i in range(len(embeddings))
    ]

    logger.info(f"🛢️ inserting {len(points)} entities into '{collection}'")
    # 3) Upsert all points at once
    client.upsert(collection_name=collection, points=points)
    end = time.perf_counter()
    logger.info(f"👉👉👉 ⏱️ total time to store in qdrant: {end - start:.3f} (s.ms)")
    logger.info(f"✅ inserted {len(points)} embeddings into '{collection}'")

    # start = time.perf_counter()
    # # Qdrant can accept everything at once, but batching keeps memory stable
    # for start in range(0, len(embeddings), batch_size):
    #     end = start + batch_size
    #     client.upload_collection(
    #         collection_name=collection,
    #         vectors=embeddings[start:end],  # (batch, dim) NumPy
    #         payload=metadata[start:end],  # lista di dict
    #         ids=list(range(start, end)),  # or UUID,
    #         wait=True,
    #     )
    # end = time.perf_counter()
    # logger.info(f"👉👉👉 ⏱️ total time to store in qdrant: {end - start:.3f} (s.ms)")


    # ids = list(range(1, len(embeddings) + 1))
    # points = [
    #     models.PointStruct(id=i, vector=vec, payload=meta)
    #     for i, vec, meta in zip(ids, embeddings.tolist(), metadata)
    # ]
    #
    # logger.info(f"🛢️ inserting {len(points)} entities into '{collection}'")
    # start = time.perf_counter()
    # client.upsert(collection_name=collection, points=points)
    # end = time.perf_counter()
    # logger.info(f"👉👉👉 ⏱️ total time to store in qdrant: {end - start:.3f} (s.ms)")

def _pick_device() -> str:
    """Return 'cuda', 'mps', or 'cpu' depending on what’s available."""
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"

def embed_with_hf(
    texts: List[str],
    batch_size: int = 32,
    normalize: bool = True,
) -> np.ndarray:
    """
    Embed a list of texts using Sentence-Transformers.

    Parameters
    ----------
    texts : List[str]
        Sentences/passages already prefixed as required by the model
        (e.g. "query: …" or "passage: …").
    batch_size : int
        How many sentences to process per forward pass.
    normalize : bool
        If True, L2-normalise the embeddings.

    Returns
    -------
    np.ndarray
        Matrix of shape (len(texts), embed_dim) on CPU.
    """
    hf_model = os.getenv("HF_EMBEDDING_MODEL")
    if not hf_model:
        logger.error("🛑 HF_EMBEDDING_MODEL is not set in .env")
        sys.exit(1)
    logger.info(f"🤖 using HF embedding model: {hf_model}")

    device = _pick_device()
    logger.info(f"🤖 using {device} device")

    # Load once per call (no extra caching layer).
    model = SentenceTransformer(hf_model, device=device)
    logger.info(f"🤖 using HF embedding model: {hf_model}")
    start = time.perf_counter()
    # The ST `.encode` helper handles batching, padding and device transfer.
    # `convert_to_numpy=True` gives a NumPy array directly on CPU.
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=normalize,
        show_progress_bar=len(texts) >= batch_size,
    )


    end = time.perf_counter()
    logging.info(f"✅ embedded {len(texts)} texts ➜ shape {embeddings.shape}")
    logger.info(f"👉👉👉 ⏱️ total embedding time with HF SentenceTransformers: {end - start:.3f} (s.ms)")
    return embeddings
