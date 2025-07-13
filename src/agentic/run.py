# Main entry point for the application
import uvicorn
from dotenv import load_dotenv
import os

from src.database.postgres_handler import PostgresHandler
from src.database.qdrant_handler import QdrantHandler

def setup_environment():
    """Loads environment variables and sets up database connections and schemas."""
    load_dotenv()
    
    print("Setting up PostgreSQL...")
    pg_handler = PostgresHandler()
    pg_handler.connect()
    pg_handler.create_news_table()
    pg_handler.close()
    
    print("Setting up Qdrant...")
    qdrant_handler = QdrantHandler()
    qdrant_handler.setup_collection()

if __name__ == "__main__":
    setup_environment()
    print("Launching FastAPI server...")
    uvicorn.run("src.api.main:app", host="0.0.0.0", port=8000, reload=True)
