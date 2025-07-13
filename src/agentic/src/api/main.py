from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List
import datetime

from ..database.postgres_handler import PostgresHandler
from ..agents.news_agents import NewsAgents, NewsTasks
from crewai import Crew

app = FastAPI(
    title="Sentinel-AI Newsfeed Platform",
    description="A real-time newsfeed platform for IT-related events.",
    version="0.1.0"
)

# Initialize Agents and Tasks
agents = NewsAgents()
filtering_agent = agents.filtering_agent()
storage_agent = agents.storage_agent()

# Assemble the Crew
crew = Crew(
    agents=[filtering_agent, storage_agent],
    tasks=[], # Tasks will be created dynamically
    verbose=2
)

class NewsItem(BaseModel):
    id: str
    source: str
    title: str
    body: str | None = None
    published_at: datetime.datetime

def run_crew_workflow(events: List[dict]):
    """Function to run the crewai workflow in the background."""
    tasks = NewsTasks()
    # Create the task with the context of the news items
    filter_task = tasks.filter_and_store_task(filtering_agent, events)
    
    # Assign the task to the crew and kick it off
    crew.tasks = [filter_task]
    result = crew.kickoff()
    print("Crew workflow finished with result:", result)

@app.post("/ingest", status_code=202) # Use 202 Accepted for background tasks
async def ingest_events(events: List[NewsItem], background_tasks: BackgroundTasks):
    """
    Accepts a list of news events and processes them in the background.
    """
    print(f"Received {len(events)} events to ingest.")
    event_dicts = [event.dict() for event in events]
    background_tasks.add_task(run_crew_workflow, event_dicts)
    return {"status": "processing_started"}

@app.get("/retrieve", response_model=List[NewsItem])
async def retrieve_events():
    """
    Retrieves the filtered and ranked news events from the database.
    """
    print("Retrieving filtered events.")
    pg_handler = PostgresHandler()
    pg_handler.connect()
    # Fetch articles marked as relevant
    query = "SELECT id, source, title, body, published_at FROM news_articles WHERE is_relevant = TRUE ORDER BY published_at DESC;"
    articles_data = pg_handler.fetch_query(query)
    pg_handler.close()
    
    # Convert database rows to NewsItem models
    articles = [
        NewsItem(
            id=row[0],
            source=row[1],
            title=row[2],
            body=row[3],
            published_at=row[4]
        )
        for row in articles_data
    ]
    return articles

@app.get("/")
def read_root():
    return {"message": "Welcome to the Sentinel-AI Newsfeed API"}
