# sentinel-AI
Wen I read the specs for this project, and one of the requirements was to make the application to work at scale 
i suddenly told myself, to make it work at scale agents needs to become microservice able to work asynchronously whit an orchestrator logic, 
spread over various microservices driven by a message bus to deliver asynchronous operations requests.
In this scenario each agent has become a microservice with its own responsibility driven by an orchestrator, the scheduler.
You can see the full list of microservice and their own responsibility on the [**service matrix**](docs/architecture.md#service-matrix):
<br />
> 💡 **Tip:** If you are interested in a full agentic AI solution, please have a look at [Reforge-AI](https://github.com/gsantopaolo/reforge-ai)

<br />
Sentinel-AI is an **event-driven**, **microservice** platform for real-time feed ingestion, filtering, ranking, 
and anomaly detection—designed to run on Kubernetes and scale to millions of users. 🚀🐳



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

### Guardian

The Guardian service acts as the central nervous system and watchdog for the entire Sentinel AI platform. Unlike other services that process event data, the Guardian's primary role is to ensure the reliability, stability, and security of the system as a whole.

Its key responsibilities include:
- **Dead-Letter Queue (DLQ) Monitoring**: It subscribes to all DLQ subjects (`dlq.>`) across NATS. When a message fails processing in any service after multiple retries, it lands in the DLQ and is immediately intercepted by the Guardian.
- **Pluggable Alerting**: Upon receiving a failed message, the Guardian uses a configurable set of alerters (e.g., logging, Slack, email) to notify administrators with detailed information about the failure, including the original message, the service that failed, and the reason for the failure.

This provides centralized, real-time insight into message processing failures anywhere in the system, enabling rapid diagnosis and resolution.

---

## Known Issues and Future Improvements

- **Qdrant Update Race Condition**:
  - **ranker service**: The service currently uses a `retrieve-then-update` pattern to add scores to event records in Qdrant. This could create a race condition if another service modifies the same record concurrently, potentially leading to data loss. A more robust solution would be to use a partial update (`set_payload`) operation.
  - **inspector service**: Shares the same potential race condition as the `ranker` service. The recommendation is the same: modify `QdrantLogic` to use a `set_payload` operation for atomic field updates.
- **Externalize NATS Retry Policy**:
  - The message redelivery attempt count (`max_deliver`) is currently hardcoded to `3` in the subscriber services (`filter`, `ranker`, `inspector`). This should be moved to a `.env` variable (e.g., `NATS_MAX_DELIVER_COUNT`) to allow for easier configuration without code changes.

---

## 🚀 Installation

> *To be completed: prerequisites, Helm charts, Docker Compose commands, etc.*

---

## ⚠️ Known Issues & Troubleshooting

> *To be completed: common pitfalls, configuration tips, logging and metrics guidance.*
- When the cluster starts and you use the Web UI before all services are ready, the UI will show an error message.
make sure all services are started through the Portainer UI 
- Filter service: There is a potential race condition in the logic that could cause issues under specific circumstances.
The ranker service retrieves an event from Qdrant, modifies it in memory, and then writes it back. If another service (like the inspector) were to perform the same retrieve-then-update operation on the exact same event at the exact same time, one of the updates could be overwritten and lost. For example:
  - Ranker retrieves event E.
  - Inspector retrieves event E.
  - Ranker adds its scores to E and writes it back to Qdrant.
  - Inspector adds its analysis to its copy of E (which does not have the ranker's scores) and writes it back to Qdrant.
Result: The ranker's scores are lost.
Recommendation: While this is a low-probability event in the current architecture, the best practice to prevent this is to use Qdrant's set_payload operation instead of a full 
upsert. The set_payload method allows us to update specific fields of a point without overwriting the entire record.
Suggested improvement to prevent the issue described above:
  - Modify the QdrantLogic class to support set_payload and updating the ranker to use it. This would make the service more resilient and align it with best practices for concurrent data modification.


- inspector service:Potential Issue (Same as ranker): The inspector service shares the same potential race condition as the ranker service. It uses a retrieve-then-update pattern with a full 
upsert. This means if the inspector and ranker process the same event at the same time, one service's update could overwrite and erase the other's. As before, this is a low-risk issue for a proof-of-concept, but for a production system, the recommendation would be to modify 
QdrantLogic to use a set_payload operation, which updates only specific fields without overwriting the entire record.





---

## 🚧 Next Steps


> *To be completed: bonus features, advanced filtering modules, extended monitoring strategies.*
- Scheduler: for full scalability change APScheduler
- Improved web UI
- Implemet dependecies in the Docker Compose so that the container will start correctly and we will avoid any error in the Web UI when the web container starts faster than others and the user will get errors because other containers are still starting 
- Readiness probe for inspector and web are not working
- portainer and authentik needs to be enabled
- Implement Authentik to add user access with existing organization's credentials 
- Creat the HELM chart to deploy the cluster on K8s
---

> check out [my blog](https://genmind.ch)

> Powered by ❤️ for intelligent, AI-driven insights!