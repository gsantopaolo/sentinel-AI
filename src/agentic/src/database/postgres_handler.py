import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

class PostgresHandler:
    def __init__(self):
        self.dbname = os.getenv("POSTGRES_DB")
        self.user = os.getenv("POSTGRES_USER")
        self.password = os.getenv("POSTGRES_PASSWORD")
        self.host = os.getenv("POSTGRES_HOST")
        self.port = os.getenv("POSTGRES_PORT")
        self.conn = None

    def connect(self):
        """Establish a connection to the PostgreSQL database."""
        if self.conn is None or self.conn.closed:
            try:
                self.conn = psycopg2.connect(
                    dbname=self.dbname,
                    user=self.user,
                    password=self.password,
                    host=self.host,
                    port=self.port
                )
                print("Connected to PostgreSQL database.")
            except psycopg2.OperationalError as e:
                print(f"Could not connect to PostgreSQL database: {e}")
                # For this exercise, we'll let the app fail if DB is not available.
                # In a future step, you will set up the container.
                pass

    def close(self):
        """Close the database connection."""
        if self.conn and not self.conn.closed:
            self.conn.close()
            print("PostgreSQL connection closed.")

    def execute_query(self, query, params=None):
        """Execute a single SQL query."""
        self.connect()
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            self.conn.commit()

    def fetch_query(self, query, params=None):
        """Execute a query and return the results."""
        self.connect()
        with self.conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def create_news_table(self):
        """Creates the news_articles table if it doesn't exist."""
        query = """
        CREATE TABLE IF NOT EXISTS news_articles (
            id VARCHAR(255) PRIMARY KEY,
            source VARCHAR(255),
            title TEXT,
            body TEXT,
            published_at TIMESTAMPTZ,
            is_relevant BOOLEAN DEFAULT FALSE,
            ranking_score FLOAT DEFAULT 0.0
        );
        """
        self.execute_query(query)
        print("Table 'news_articles' is ready.")
