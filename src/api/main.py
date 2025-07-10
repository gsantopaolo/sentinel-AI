from fastapi import FastAPI, Response, status

app = FastAPI()

@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
def ingest_data():
    return {"message": "Data ingestion accepted"}

@app.get("/retrieve", status_code=status.HTTP_200_OK)
def retrieve_data(batch_id: str):
    return {"batch_id": batch_id, "data": "some retrieved data"}

@app.get("/news", status_code=status.HTTP_200_OK)
def get_news():
    return [{"id": 1, "title": "News 1"}, {"id": 2, "title": "News 2"}]

@app.get("/news/filtered", status_code=status.HTTP_200_OK)
def get_filtered_news():
    return [{"id": 1, "title": "Filtered News 1"}]

@app.get("/news/ranked", status_code=status.HTTP_200_OK)
def get_ranked_news():
    return [{"id": 1, "title": "Ranked News 1", "score": 100}]

@app.post("/news/rerank", status_code=status.HTTP_200_OK)
def rerank_news():
    return {"message": "News reranked successfully"}

@app.get("/sources", status_code=status.HTTP_200_OK)
def get_sources():
    return [{"id": 1, "name": "Source 1"}]

@app.post("/sources", status_code=status.HTTP_201_CREATED)
def create_source():
    new_source = {"id": 2, "name": "New Source"}
    return new_source

@app.put("/sources/{source_id}", status_code=status.HTTP_200_OK)
def update_source(source_id: int):
    return {"message": f"Source {source_id} updated successfully"}

@app.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: int):
    return Response(status_code=status.HTTP_204_NO_CONTENT)
