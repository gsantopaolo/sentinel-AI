import argparse

from utils import *
import os
import logging
from dotenv import load_dotenv, find_dotenv


# Load environment and configure logging
load_dotenv(find_dotenv())

log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)
# get log format from env
log_format = os.getenv('LOG_FORMAT', '%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(message)s')
# Configure logging
logging.basicConfig(level=log_level, format=log_format)

logger = logging.getLogger(__name__)


def main(pdf_path: Path, collection: str):
    text = extract_text_from_pdf(str(pdf_path))
    chunks = chunk_text(text)
    embeddings = embed_with_hf(chunks)
    metadata = [{"source": str(pdf_path), "chunk_index": i} for i in range(len(chunks))]
    store_embeddings(embeddings, metadata, collection)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Embed PDF text into Qdrant using Sentence‑Transformers",
    )
    parser.add_argument("--pdf_path", type=Path, required=True, help="Path to the PDF file")
    parser.add_argument("--collection", type=str, required=True, help="Qdrant collection name")
    args = parser.parse_args()

    main(args.pdf_path, args.collection)
