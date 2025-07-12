# Filter Service

## Overview

The `filter` service is a critical component of the Sentinel AI platform, acting as the first line of defense and enrichment for incoming news events. Its primary role is to process raw, uncurated events, determine their relevance, and prepare them for subsequent stages of ranking and analysis.

Its core responsibilities include:
1.  **Subscribe** to `raw.events` from the NATS stream.
2.  **Apply Relevance Filters**: Determine if an event is relevant to a specific domain (e.g., IT management) using a Large Language Model (LLM).
3.  **Discard or Enrich**: Discard irrelevant events with a detailed log, or enrich relevant events by generating vector embeddings and assigning categories.
4.  **Initial Persistence**: For relevant events, perform the first and only initial write to the Qdrant vector database.
5.  **Publish**: Publish the successfully persisted events as `filtered.events` to a NATS stream for downstream services.

## Core Functionality: Intelligent Filtering and Persistence

The `filter` service leverages the power of LLMs to perform nuanced content analysis and acts as the gatekeeper to the vector database.

### 1. Relevance Filtering with LLM

Upon receiving a `raw.event`, the `filter` service first assesses its relevance. This is achieved by sending the event's content to a configured LLM. Events deemed irrelevant are **discarded** and never enter the database. A detailed warning is logged, including the event ID, title, and the LLM's reasoning, to ensure full traceability for rejected events.

**Example Configuration (`filter_config.yaml` - Relevance Prompt):**
```yaml
llm_config:
  provider: "openai"
  model_name: "gpt-4o-mini"
  api_key_env_var: "OPENAI_API_KEY"

filtering_rules:
  relevance_prompt: |
    You are an expert in IT news analysis. Your task is to determine if the following news article is relevant to an IT manager.
    Consider topics such as cybersecurity, cloud computing, network infrastructure, software development, data management, IT strategy, and compliance.
    Respond with "RELEVANT" if the article is highly relevant, "POTENTIALLY_RELEVANT" if it has some relevance but might require further review, and "IRRELEVANT" otherwise.
    ---
    Article: {article_content}
    ---
    Relevance:
```

### 2. Categorization and Embedding Generation

For events that pass the relevance filter, the service performs two key actions:
1.  **Categorization**: It makes a second LLM call to classify the event into one or more predefined categories.
2.  **Embedding Generation**: It uses a `SentenceTransformer` model to generate vector embeddings for the event's content. This is the primary point where the computationally intensive embedding process occurs.

### 3. Initial Persistence to Qdrant

This is a critical new responsibility. The `filter` service is the **first and only service** to write an event to Qdrant. It constructs a complete record—including original metadata, LLM-derived categories, and the vector embedding—and upserts it into the database. If this persistence step fails, the event is not published downstream, ensuring data consistency.

## Why YAML Configuration?

The `filter` service's reliance on `filter_config.yaml` is a cornerstone of its flexible design:

*   **Domain Agnosticism**: By externalizing LLM prompts and filtering rules, the service is not hardcoded to a specific domain (e.g., IT news). It can be repurposed for finance, medical, or any other industry by simply modifying the YAML configuration, without requiring code changes.
*   **Dynamic Adaptability**: The criteria for relevance and categorization can be updated on the fly by adjusting the prompts and rules in the YAML file, allowing the system to adapt to evolving requirements or new trends.
*   **Separation of Concerns**: It clearly separates the business logic of filtering from the specific content and parameters of the LLM interactions, promoting cleaner code and easier maintenance.
*   **Experimentation**: Different filtering strategies and LLM prompts can be easily experimented with by modifying the YAML, facilitating rapid iteration and optimization.

## Technical Deep Dive

The `filter` service is implemented as a Python microservice, utilizing asynchronous programming with `asyncio` and NATS JetStream for efficient event processing.

### Data Flow and Processing Sequence

The following sequence diagram illustrates how a raw event is processed by the `filter` service:

```mermaid
sequenceDiagram
    participant API as API Service
    participant NATS as NATS JetStream
    participant Filter as Filter Service
    participant LLM as LLM Provider
    participant Qdrant as Qdrant DB

    API->>NATS: Publish raw.events
    NATS-->>Filter: raw.events message
    Filter->>Filter: Parse RawEvent Protobuf
    Filter->>LLM: Request Relevance
    LLM-->>Filter: Relevance Response
    alt Event is Relevant
        Filter->>LLM: Request Categories
        LLM-->>Filter: Categories Response
        Filter->>Filter: Generate Embeddings
        Filter->>Qdrant: Upsert event payload
        Qdrant-->>Filter: Acknowledge upsert
        Filter->>Filter: Construct FilteredEvent Protobuf
        Filter->>NATS: Publish filtered.events
    else Event is Irrelevant
        Filter->>Filter: Log detailed warning (ID, Title, Reason)
    end
    Filter->>NATS: Acknowledge raw.events message
```

### Internal Logic Flow

The internal processing of a `raw.events` message within the `filter` service follows these steps:

```mermaid
flowchart TD
    A["Start: Receive raw.events message"] --> B{"Parse RawEvent Protobuf"}
    B --> C["Extract Event Content"]
    C --> D{"Call LLM for Relevance (relevance_prompt)"}
    D -->|LLM Response: IRRELEVANT| E["Log detailed warning: 🗑️ Event discarded..."]
    D -->|LLM Response: RELEVANT/POTENTIALLY_RELEVANT| F{"Call LLM for Categories (category_prompt)"}
    F --> G["Generate Embeddings"]
    G --> H["Upsert Event to Qdrant"]
    H -->|Success| I["Construct FilteredEvent Protobuf"]
    H -->|Failure| L["Log Error & NACK message"]
    I --> J["Publish FilteredEvent to NATS"]
    J --> K["Acknowledge raw.events message"]
    E --> K
    L --> M[End]
    K --> M
```

### Key Components and Dependencies

*   **NATS JetStream**: Used for asynchronous message passing between services (`raw.events` subscription, `filtered.events` publication).
*   **Qdrant**: The vector database where enriched event metadata and embeddings are stored.
*   **LLM Provider (OpenAI/Anthropic)**: External service used for natural language understanding, relevance classification, and categorization.
*   **`src/lib_py/middlewares/JetStreamEventSubscriber`**: Handles subscribing to NATS streams.
*   **`src/lib_py/middlewares/JetStreamPublisher`**: Handles publishing messages to NATS streams.
*   **`src/lib_py/middlewares/ReadinessProbe`**: Ensures the service's health can be monitored.
*   **`src/lib_py/logic/QdrantLogic`**: Provides an abstraction layer for interacting with Qdrant, including upserting event data.
*   **`src/lib_py/models/qdrant_models.py`**: Defines the data structures for events stored in Qdrant.
*   **`src/lib_py/gen_types/raw_event_pb2`**: Protobuf definition for incoming raw events.
*   **`src/lib_py/gen_types/filtered_event_pb2`**: Protobuf definition for outgoing filtered events.
*   **`SentenceTransformer`**: Used for generating vector embeddings from text content.
*   **`PyYAML`**: Used for loading the `filter_config.yaml` file.

This comprehensive overview should provide a clear understanding of the `filter` service's role, its internal workings, and its configurable nature within the Sentinel AI platform.