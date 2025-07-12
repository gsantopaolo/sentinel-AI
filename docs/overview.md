# Sentinel AI: System Overview and Requirements

## Introduction

This document provides a high-level overview of the Sentinel AI platform, mapping its core requirements to the specific microservices responsible for their implementation. The requirements are derived from the official project specification (`samples/specs.txt`) and supplemented with details from the project's [architecture documentation](./architecture.md), service-specific markdown files, and source code.

The platform is an [event-driven system](./architecture.md) composed of several microservices that communicate asynchronously via NATS JetStream. Each service has a distinct responsibility, working in concert to ingest, analyze, and present news data.

---

## Core Requirements Mapping

### 1. Data Ingestion and Collection

**Requirement:** The platform must ingest data both manually via an [API](./api.md) and automatically by polling external sources.

| Service | Responsibility | Implementation File(s) | Documentation |
| :--- | :--- | :--- | :--- |
| [**API**](./api.md) | Provides a REST endpoint (`/ingest`) for manual data submission. | `src/api/main.py` | `docs/api.md` |
| [**Connector**](./connector.md) | Fetches data from external sources when triggered by the [scheduler](./scheduler.md). | `src/connector/main.py` | `docs/connector.md` |
| [**Scheduler**](./scheduler.md) | Orchestrates the polling of data sources. | `src/scheduler/main.py` | `docs/scheduler.md` |

### 2. Source Management

**Requirement:** The system must provide a way to create, read, update, and delete data sources. Changes in sources must be communicated to relevant services.

| Service | Responsibility | Implementation File(s) | Documentation |
| :--- | :--- | :--- | :--- |
| [**API**](./api.md) | Exposes CRUD endpoints (`/sources`) for managing sources in the database. | `src/api/main.py` | `docs/api.md` |
| [**Scheduler**](./scheduler.md)| Listens for `new.source` and `removed.source` events to manage polling jobs. | `src/scheduler/main.py` | `docs/scheduler.md` |
| **lib_py** | Contains the shared business logic for database interactions. | `src/lib_py/logic/source_logic.py` | N/A |

### 3. Intelligent Content Filtering

**Requirement:** Raw data must be processed to determine its relevance and be categorized using intelligent, configurable logic.

| Service | Responsibility | Implementation File(s) | Documentation |
| :--- | :--- | :--- | :--- |
| [**Filter**](./filter.md) | Subscribes to `raw.events`, uses an LLM to check relevance and assign categories, and stores the result in the Qdrant vector DB. | `src/filter/main.py` | `docs/filter.md` |
| **(config)** | Defines the LLM prompts and filtering rules. | `src/filter/filter_config.yaml` | `docs/filter.md` |

### 4. Event Ranking and Scoring

**Requirement:** Filtered events must be ranked based on configurable parameters like importance (by category) and recency.

| Service | Responsibility | Implementation File(s) | Documentation |
| :--- | :--- | :--- | :--- |
| [**Ranker**](./ranker.md) | Subscribes to `filtered.events`, calculates importance, recency, and final scores, and updates the event data in Qdrant. | `src/ranker/main.py` | `docs/ranker.md` |
| **(config)** | Defines the weights and scoring parameters for the ranking algorithm. | `src/ranker/ranker_config.yaml` | `docs/ranker.md` |

### 5. Data Persistence and Modeling

**Requirement:** The platform must persist data, including source configurations and processed event data with its vector embeddings.

| Service | Responsibility | Implementation File(s) | Documentation |
| :--- | :--- | :--- | :--- |
| [**API**](./api.md) | Manages source data in a relational database (PostgreSQL). | `src/lib_py/logic/source_logic.py` | `docs/api.md` |
| [**Filter**](./filter.md) | Upserts event data and vector embeddings into Qdrant. | `src/lib_py/logic/qdrant_logic.py` | `docs/filter.md` |
| [**Ranker**](./ranker.md) | Updates event data in Qdrant with calculated scores. | `src/lib_py/logic/qdrant_logic.py` | `docs/ranker.md` |
| **lib_py** | Defines the data structures for the database and vector DB. | `src/lib_py/models/models.py`, `src/lib_py/models/qdrant_models.py` | N/A |

### 6. Asynchronous Event-Driven Communication

**Requirement:** Services must be decoupled and communicate asynchronously using a message broker to ensure scalability and resilience.

| Service | Responsibility | Implementation File(s) | Documentation |
| :--- | :--- | :--- | :--- |
| **All** | All services use NATS JetStream for publishing and subscribing to events. | `src/lib_py/middlewares/jetstream_publisher.py`, `src/lib_py/middlewares/jetstream_event_subscriber.py` | `docs/architecture.md` |

### 7. User Interface

**Requirement:** A web-based user interface must be available to interact with the system's core functionalities.

| Service | Responsibility | Implementation File(s) | Documentation |
| :--- | :--- | :--- | :--- |
| [**Web**](../readme.md) | Provides a Streamlit application for ingesting data, viewing news, and managing sources. | `src/web/app.py` | `readme.md` |

### 8. Service Health and Monitoring

**Requirement:** All microservices must expose a health check endpoint for monitoring by orchestration platforms.

| Service | Responsibility | Implementation File(s) | Documentation |
| :--- | :--- | :--- | :--- |
| **All** | Each service implements a readiness probe that starts a `/healthz` endpoint. | `src/lib_py/middlewares/readiness_probe.py` | `docs/guardian.md` |
