from crewai_tools import BaseTool
from openai import OpenAI
import os

from ..database.postgres_handler import PostgresHandler
from ..database.qdrant_handler import QdrantHandler
from qdrant_client.http.models import PointStruct

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class FilteringTool(BaseTool):
    name: str = "Content Filtering Tool"
    description: str = "Analyzes a news article's content to determine if it's relevant for IT managers."

    def _run(self, article_title: str, article_body: str) -> bool:
        """Uses an LLM to determine if the article is relevant."""
        prompt = f"""Analyze the following news article to determine if it is relevant to an IT Manager.
        The article should be about major outages, cybersecurity threats, or critical software bugs.

        Title: {article_title}
        Body: {article_body}

        Is this article relevant? Please answer with only 'true' or 'false'."""

        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant for an IT manager."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=10
        )

        result = response.choices[0].message.content.strip().lower()
        return result == 'true'

class StorageTool(BaseTool):
    name: str = "News Storage Tool"
    description: str = "Stores a filtered news article in the PostgreSQL and Qdrant databases."

    def _run(self, article: dict) -> str:
        """Stores the article and its vector embedding."""
        try:
            # Generate embedding for the article content
            content_to_embed = f"{article['title']}\n\n{article['body']}"
            response = client.embeddings.create(
                input=content_to_embed,
                model="text-embedding-3-small" # 1536 dimensions
            )
            embedding = response.data[0].embedding

            # Store in PostgreSQL
            pg_handler = PostgresHandler()
            pg_handler.connect()
            query = """
            INSERT INTO news_articles (id, source, title, body, published_at, is_relevant, ranking_score)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                source = EXCLUDED.source,
                title = EXCLUDED.title,
                body = EXCLUDED.body,
                published_at = EXCLUDED.published_at,
                is_relevant = EXCLUDED.is_relevant,
                ranking_score = EXCLUDED.ranking_score;
            """
            params = (
                article['id'], article['source'], article['title'], article['body'], 
                article['published_at'], True, 0.0 # Placeholder for ranking
            )
            pg_handler.execute_query(query, params)
            pg_handler.close()

            # Store in Qdrant
            qdrant_handler = QdrantHandler()
            qdrant_handler.add_points([
                PointStruct(
                    id=article['id'], 
                    vector=embedding, 
                    payload=article
                )
            ])

            return f"Successfully stored article with ID: {article['id']}."
        except Exception as e:
            return f"Error storing article with ID {article['id']}: {e}"
