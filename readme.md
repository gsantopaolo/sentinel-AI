# Sentinel-AI



When I first read the requirements, it became clear that **scalability** was paramount. Accordingly, I implemented Sentinel-AI as a proof of concept designed to run on Kubernetes and scale seamlessly to millions of users. With the right production-level enhancements—such as optimized provisioning, autoscaling policies, and resilient networking—this prototype can be deployed in a very short timeframe and handle heavy loads at production scale.

<br /> 
> 👉 [Sentinel-AI GitHub repository](https://github.com/gen-mind/sentinel-ai)
<br />

Although this initial version is not fully agentic, it already leverages embeddings and a large language model (LLM) and can be easily connected to a private inference server (currently supporting SaaS providers like OpenAI and Anthropic). For an overview of how to integrate a high-throughput, private inference cluster at scale, 
see the [CogniX architecture](https://github.com/gen-mind/cognix/tree/main/docs#architecture).
<br />
At the moment, the app is not agentic, but converting the AI-powered components into fully agentic systems is straightforward—see the pseudocode in [src/agentic](https://github.com/gen-mind/sentinel-ai/tree/main/src/agentic) for details.
The base idea is that, if needed, every microservice can be easily ocnverted into an agentic service and the pseudo code in [src/agentic](https://github.com/gen-mind/sentinel-ai/tree/main/src/agentic) is a good starting point.
<br /> 
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

## 🚀 Installation & Quick Start

This repository ships **Docker-Compose** manifests (plus helper scripts) that spin up the full micro-service stack in seconds. You can also run an individual service on your laptop for development.

### 0. Prerequisites

* [Docker Desktop](https://www.docker.com/) **or** `docker` ≥ 20.10 and `docker-compose` V2.
* Linux / macOS (the scripts use `bash`).
* An API key for your preferred LLM provider (e.g. OpenAI, Anthropic).

### 1. Configure environment variables

```
deployment/.env.example   # single file used by docker-compose
src/*/.env.example        # one per micro-service (only needed if you run them separately)
```

• **Docker-Compose path (recommended):**  
  Rename `deployment/.env.example` → `deployment/.env` and add your LLM provider key(s).  
  All other variables already have sensible defaults.

• **Local-service path:**  
  When hacking on a service outside Docker, copy its `.env.example` to `.env` and tweak as needed.

### 2. Start the cluster

From one directory **above** the repo root (so the docker build context remains small):

```bash
chmod +x deployment/*.sh          # first time only
sudo deployment/start.sh          # builds & launches the stack
```

The very first run downloads base images and builds all containers, so it can take several minutes. Subsequent starts are faster.

### 3. Stop the cluster

```bash
sudo deployment/stop.sh
```
> Having issues? Check container logs in Portainer or run `docker compose logs -f <service>`.
---

### 4. Monitoring & troubleshooting

After the stack is up, the script prints a **Portainer** URL (e.g. `http://localhost:9000`). On first visit you must create an admin user & password. From the dashboard you can:

* Inspect container logs.
* Restart a service if it failed to start (this PoC occasionally needs manual restarts).

Dashboards exposed by the compose file:

| Service   | URL                      |
|-----------|--------------------------|
| Portainer | `http://localhost:9000`  |
| Qdrant    | `http://localhost:6333`  |
| NATS      | `http://localhost:8222`  |
| Postgres  | `http://localhost:5432`¹ |
¹ psql/GUI only—no web UI included.

> 💡 **Tip:** After adding a few sources and ingesting news, open the Qdrant dashboard to explore the stored vectors.

### 5. Running a single micro-service locally

```bash
cd src/ranker
cp .env.example .env   # edit variables if needed
pip install -r requirements.txt
python main.py
```

Make sure Docker Compose is already running NATS, Postgres, and Qdrant (or point the env vars to your own instances).


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

---
