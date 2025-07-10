# sentinel-AI

An **event-driven**, **microservice** platform for real-time feed ingestion, filtering, ranking, and anomaly detection—designed to run on Kubernetes and scale to millions of users. 🚀🐳

**Key Features:**

* 🔗 **Dynamic Ingestion:** Subscribe to any data feed (RSS, APIs, webhooks, etc.) and ingest events in real time.
* 🧹 **Smart Filtering:** Apply custom relevance rules or plug in ML models to filter events.
* ⚖️ **Deterministic Ranking:** Balance importance & recency with a configurable scoring algorithm; support on-the-fly reordering via APIs.
* 🔍 **Searchable Storage:** Persist full event metadata, embeddings, and scores in a vector database for fast semantic search.
* 🚨 **Anomaly Detection:** Automatically detect and flag unusual or malformed events.
* 📈 **High Scalability:** Built on NATS JetStream and Kubernetes auto-scaling to serve millions of users with minimal latency.
* 🖥️ **Interactive Dashboard:** List, filter, rerank, delete events and sources, and visualize feeds in real time through a web UI.

---

## Documentation

- [**Overview**](docs/overview.md): A high-level summary of the platform's requirements and how they map to the different services.
- [**Architecture**](docs/architecture.md): A detailed look at the microservices architecture, data flows, and technologies used.
- [**API Service**](docs/api.md): Describes the main entry point for the system, responsible for ingestion, source management, and data retrieval.
- [**Scheduler Service**](docs/scheduler.md): Describes how the platform manages and schedules data collection from sources.
- [**Connector Service**](docs/connector.md): Explains how the platform fetches and normalizes data from external sources.
- [**Filter Service**](docs/filter.md): Details the intelligent filtering and enrichment process using LLMs.
- [**Ranker Service**](docs/ranker.md): Explains the configurable ranking algorithm that scores events based on importance and recency.
- [**Guardian Service**](docs/guardian.md): Outlines the role of the system's monitoring and health-checking component.
---

## 🚀 Installation

> *To be completed: prerequisites, Helm charts, Docker Compose commands, etc.*

---

## ⚠️ Known Issues & Troubleshooting

> *To be completed: common pitfalls, configuration tips, logging and metrics guidance.*

---

## 🚧 Next Steps


> *To be completed: bonus features, advanced filtering modules, extended monitoring strategies.*
- Scheduler: for full scalability change APScheduler
- Improved web UI
- Implement Authentik to add user access with existing organization's credentials 
- Creat the HELM chart to deploy the cluster on K8s
---

> check out [my blog](https://genmind.ch)

> Powered by ❤️ for intelligent, AI-driven insights!
