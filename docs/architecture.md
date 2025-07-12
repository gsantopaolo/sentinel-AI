## Architecture Overview

This is a microservice, event-driven design built to run on a Kubernetes cluster 
(docker cluster suggested only for development or test purposes). 
Each service is independently deployable, horizontally scalable, and communicates via NATS pub/sub 
for high throughput and low latency. With Kubernetes’ auto-scaling and NATS JetStream for 
durable streams, this architecture can effortlessly serve millions of users in real time.

```mermaid
flowchart LR
    %% Left Services (vertical)
    subgraph ServicesLeft["Services"]
      direction TB
      scheduler["scheduler"]:::service
      connector["connector"]:::service
      filter["filter"]:::service
    end

    %% Wide Infrastructure (horizontal)
    subgraph Infrastructure["Infrastructure"]
      direction LR
      NATS["NATS"]:::nats
      DLQ["Dead-letter Queue"]:::dlq
      Postgres["Postgres"]:::postgres
      Qdrant["Qdrant"]:::qdrant
    end

    %% Right Services (vertical)
    subgraph ServicesRight["Services"]
      direction TB
      ranker["ranker"]:::service
      inspector["inspector"]:::service
      api["api"]:::service
      web["web (UI)"]:::service
      guardian["guardian"]:::service
    end

    %% Publications: services → infra
    scheduler -- "poll.source" --> NATS
    connector -- "normalized → raw.events" --> NATS
    filter -- "filtered.events" --> NATS
    filter -- "persist + embeddings" --> Qdrant

    %% Subscriptions: infra → services
    NATS -- "poll.source" --> connector
    NATS -- "raw.events" --> filter
    NATS -- "filtered.events" --> ranker
    NATS -- "filtered.events" --> inspector
    NATS -- "dead-letter →" --> DLQ

    %% Additional infra flows
    ranker -- "ranked.events" --> NATS
    ranker -- "upsert score" --> Qdrant
    inspector -- "flag anomalies / fake news" --> Qdrant
    DLQ -- "notifies" --> guardian

    %% API & UI interactions
    api -- "publish raw.events, new/removed.source" --> NATS
    api -- "CRUD sources" --> Postgres
    api -- "read/write events & scores" --> Qdrant
    web -- "HTTP calls" --> api

    classDef service   fill:#e0f7fa,stroke:#006064,stroke-width:1px;
    classDef nats      fill:#ffecb3,stroke:#bf360c,stroke-width:1px;
    classDef dlq       fill:#ffe0b2,stroke:#f57c00,stroke-width:1px;
    classDef postgres  fill:#c8e6c9,stroke:#1b5e20,stroke-width:1px;
    classDef qdrant    fill:#d1c4e9,stroke:#4a148c,stroke-width:1px;
```

## Service Matrix

| Service       | Description                                                                                          | Responsibility                                                                                                                                                                                                                                                                                                                                          | Publishes to                                     | Subscribes to                              | DB Access                                                              |
|---------------|------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------|--------------------------------------------|------------------------------------------------------------------------|
| [**api**](./api.md)       | Unified gateway for ingestion, retrieval, news listing, UI ranking, re-ranking, and source management | • Ingestion: POST `/ingest` → `raw.events`  <br>• Retrieval: GET `/retrieve?batch_id=`  <br>• List all news: GET `/news`  <br>• List filtered news: GET `/news/filtered`  <br>• Default ranking & UI: GET `/news/ranked`  <br>• Dynamic re-rank: POST `/news/rerank`  <br>• Source Manager (CRUD): GET/POST/PUT/DELETE `/sources` → `new.source` / `removed.source` | `raw.events`<br>`new.source`<br>`removed.source` | —                                          | Reads from: Qdrant (events & scores) Reads/Writes PostgreSQL (sources) |
| [**scheduler**](./scheduler.md) | Schedules polling jobs for live feeds                                                                | Maintain poll schedules (via APScheduler); emit `poll.source` when sources are added/removed                                                                                                                                                                                                                                                            | `poll.source`                                    | `new.source`<br>`removed.source`            | —                                                                      |
| [**connector**](./connector.md) | Fetches & normalizes data from live sources                                                          | Subscribe to `poll.source`; fetch & normalize each live source; publish normalized events                                                                                                                                                                                                                                                               | `raw.events`                                     | `poll.source`                              | —                                                                      |
| [**filter**](./filter.md)    | Filters events for relevance, enriches with embeddings, and persists them                            | Subscribe to `raw.events`; apply relevance filters; compute embeddings; persist full event (metadata + embedding) to Qdrant; publish `filtered.events`; ack only on success                                                                                                                                                                            | `filtered.events`                                | `raw.events`                               | Writes to Qdrant (events & embeddings)                                 |
| [**ranker**](./ranker.md)    | Computes and persists deterministic event scores                                                     | Subscribe to `filtered.events`; compute Importance×Recency scores; upsert score into Qdrant; publish `ranked.events`; ack only on success                                                                                                                                                                                                                 | `ranked.events`                                  | `filtered.events`                          | Writes to Qdrant (scores)                                              |
| [**inspector**](./inspector.md) | Detects anomalous or fake items and flags them in the datastore                                      | Subscribe to `filtered.events`; detect anomalies and fake news; update anomaly flag on the corresponding Qdrant record; ack only on success                                                                                                                                                                                                             | —                                                | `filtered.events`                          | Writes anomaly flag to Qdrant                                          |
| [**guardian**](./guardian.md)  | Monitors NATS dead-letter queue and alerts on messages that exhaust retries                          | Subscribe to NATS dead-letter queue; after configured retries are exhausted, send alerts/notifications (e.g., email, Slack, PagerDuty)                                                                                                                                                                                                                  | Alerts/Notifications (external)                  | NATS dead-letter queue                      | —                                                                      |
| [**web**](../readme.md)       | User-facing UI for listing, filtering, reranking, deleting events and managing sources               | Render dashboards and lists; call API endpoints (`/news*`, `/sources*`, `/ingest`, `/retrieve`, etc.); provide controls for reranking and CRUD ops                                                                                                                                                                                                    | —                                                | HTTP API endpoints on `api`                | —                                                                      |


This layout and matrix ensure every requirement—from ingestion through filtering, ranking, 
anomaly detection, retries, and UI—has clear ownership, data flow, and persistence.
