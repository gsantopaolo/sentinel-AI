# Sentinel-AI

Sentinel-AI is an **event-driven**, **microservice** platform for real-time feed ingestion, filtering, ranking, and anomaly detection—designed to run on Kubernetes and scale to millions of users. 🚀🐳

This project implements a scalable, real-time newsfeed platform that aggregates, filters, stores, and ranks IT-related event data from multiple sources. It is built with an asynchronous, microservice-based architecture, where each service has a distinct responsibility and communicates via a message bus.

> 💡 **Tip:** If you are interested in a full agentic AI solution, please have a look at [Reforge-AI](https://github.com/gsantopaolo/reforge-ai)

**Key Features:**

* 🔗 [**Dynamic Ingestion](docs/api.md):** Subscribe to any data feed (RSS, APIs, webhooks, etc.) and ingest events in real time.
* 🧹 [**Smart Filtering](docs/filter.md):** Apply custom relevance rules or plug in ML models to filter events.
* ⚖️ [**Deterministic Ranking](docs/ranker.md):** Balance importance & recency with a configurable scoring algorithm; support on-the-fly reordering via APIs.
* 🔍 [**Searchable Storage](docs/inspector.md):** Persist full event metadata, embeddings, and scores in a vector database for fast semantic search.
* 🚨 [**Anomaly Detection**](docs/inspector.md): Automatically detect and flag unusual or malformed events.
* 📈 [**High Scalability](docs/architecture.md):** Built on NATS JetStream and Kubernetes auto-scaling to serve millions of users with minimal latency.
* 🖥️ [**Interactive Dashboard:](docs/web.md)** List, filter, rerank, delete events and sources, and visualize feeds in real time through a web UI.

---

## Documentation

- [**Overview**](docs/overview.md): A high-level summary of the platform's requirements and how they map to the different services.
- [**Architecture**](docs/architecture.md): A detailed look at the microservices architecture, data flows, and technologies used.
- [**API Service**](docs/api.md): Describes the main entry point for the system, responsible for ingestion, source management, and data retrieval.
- [**Scheduler Service**](docs/scheduler.md): Describes how the platform manages and schedules data collection from sources.
- [**Connector Service**](docs/connector.md): Explains how the platform fetches and normalizes data from external sources.
- [**Filter Service**](docs/filter.md): Details the intelligent filtering and enrichment process using LLMs.
- [**Ranker Service**](docs/ranker.md): Explains the configurable ranking algorithm that scores events based on importance and recency.
- [**Inspector Service**](docs/inspector.md): Describes the service responsible for detecting and flagging anomalous or fake news events.
- [**Guardian Service**](docs/guardian.md): Outlines the role of the system's monitoring and health-checking component.
- [**Web Service**](docs/web.md): Describes the interactive web UI for managing and visualizing platform data.

---

## 🚀 Installation

> *To be completed: prerequisites, Helm charts, Docker Compose commands, etc.*

---

## ⚠️ Known Issues and Future Improvements

- **Qdrant Update Race Condition**:
  - Both the `ranker` and `inspector` services use a `retrieve-then-update` pattern to modify event records in Qdrant. This can create a race condition where concurrent updates might overwrite each other, leading to data loss.
  - **Recommendation**: Modify the `QdrantLogic` class to support the `set_payload` operation, which allows for atomic, partial updates to a record without overwriting the entire object.

- **Externalize NATS Retry Policy**:
  - The message redelivery attempt count (`max_deliver`) is currently hardcoded to `3` in the subscriber services (`filter`, `ranker`, `inspector`).
  - **Recommendation**: This should be moved to a `.env` variable (e.g., `NATS_MAX_DELIVER_COUNT`) to allow for easier configuration without code changes.

- **Service Startup Dependencies**:
  - When the cluster starts, the Web UI may become available before all backend services are ready, leading to initial errors.
  - **Recommendation**: Implement health checks or dependencies in the Docker Compose configuration to ensure a graceful startup sequence.

- **Readiness Probes**:
  - The readiness probes for the `inspector` and `web` services are not fully functional and need to be corrected.

---

## 🚧 Next Steps

- **Scheduler Scalability**: Replace the current `APScheduler` implementation with a more distributed and scalable solution suitable for a multi-node environment.
- **Authentication**: Implement `Authentik` to add user access control and integrate with existing organizational credentials.
- **Helm Chart**: Create a Helm chart for streamlined deployment to a Kubernetes cluster.
- **Improved Web UI**: Enhance the user interface with more advanced features and a more polished design.

---

> check out [my blog](https://genmind.ch)

> Powered by ❤️ for intelligent, AI-driven insights!