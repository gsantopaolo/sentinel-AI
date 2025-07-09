

# Guardian
Guardian is a **dedicated dead letter queue handler service**. This service focuses solely on handling messages that have exceeded their maximum delivery attempts. 

## This service is responsible for:

- **Subscribing to the advisory subjects** that JetStream emits when messages reach their maximum delivery attempts.
- **Parsing the advisory messages** to extract information about the failed message, such as the stream name, consumer name, and sequence number.
- **Retrieving the failed message** from the original stream using the sequence number.
- **Logging or processing the failed message** as required by the application logic.
- **Deleting or acknowledging the failed message** from the original stream to keep it clean.
- **Optionally moving the failed message** to a separate DLQ stream for further analysis or reprocessing.


## Advantages of this approach:

- **Separation of concerns:** Keeps the DLQ handling logic separate from the main application logic, making the system easier to maintain and scale.
- **Centralized error handling:** Provides a single place to monitor and manage all failed messages.
- **Resource optimization:** Allows main services to focus on processing valid messages without the overhead of DLQ management.
- **Scalability:** Enables independent scaling of the DLQ handler based on the volume of failed messages.


## How it works:

- **Connection to NATS:**
  - The `DeadLetterQueueHandler` class initializes a connection to the NATS server and creates a JetStream context.
  - Connection parameters are loaded from environment variables for flexibility.

- **Subscription to Advisory Subject:**
  - The service subscribes to the advisory subject `"$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.>"` to listen for any message that has exceeded its maximum delivery attempts across all streams and consumers.

- **Processing Advisories:**
  - The `process_advisory` method parses the advisory message to extract the stream name, consumer name, and stream sequence number.
  - It retrieves the failed message from the stream using `self.js.get_msg(stream, stream_seq)`.
  - The failed message is logged for auditing or debugging purposes.
  - The message is deleted from the original stream using `self.js.delete_msg(stream, stream_seq)` to keep the stream clean.

- **Optional DLQ Stream:**
  - You can uncomment and modify the line `await self.js.publish("DLQ_STREAM", failed_msg)` to move the failed message to a dedicated DLQ stream for further processing or analysis.

- **Running the Service:**
  - The `run` method sets up the connection and subscriptions, then enters an infinite loop to keep the service running.
  - Graceful shutdown is handled by catching `KeyboardInterrupt` and closing the NATS connection.
