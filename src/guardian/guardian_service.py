# region imports
import asyncio
import logging
import os
import threading
import time
from dotenv import load_dotenv
import json
from nats.aio.msg import Msg
from nats.js.errors import BadRequestError
from nats.js.api import StreamConfig

from lib_py.gen_types.rembg_data_pb2 import RembgData
from lib_py.gen_types.sticky_detector_data_pb2 import StickyDetectorData
from lib_py.middlewares.jetstream_event_subscriber import JetStreamEventSubscriber
from lib_py.middlewares.readiness_probe import ReadinessProbe
from lib_py.middlewares.jetstream_publisher import JetStreamPublisher

# You can import additional modules as needed
# endregion

# region .env and logs
# Load environment variables from .env file
load_dotenv()

# Get log level from env
log_level_str = os.getenv('GUARDIAN_LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)
# Get log format from env
log_format = os.getenv('GUARDIAN_LOG_FORMAT', '%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(message)s')
# Configure logging
logging.basicConfig(level=log_level, format=log_format)

logger = logging.getLogger(__name__)
logger.info(f"📝 Logging configured with level {log_level_str} and format {log_format}")

# Loading NATS connection parameters from env
nats_url = os.getenv('NATS_CLIENT_URL', 'nats://127.0.0.1:4222')
nats_connect_timeout = int(os.getenv('NATS_CLIENT_CONNECT_TIMEOUT', '30'))
nats_reconnect_time_wait = int(os.getenv('NATS_CLIENT_RECONNECT_TIME_WAIT', '30'))
nats_max_reconnect_attempts = int(os.getenv('NATS_CLIENT_MAX_RECONNECT_ATTEMPTS', '3'))

# DLQ Stream Configuration
dlq_stream_name = os.getenv('NATS_CLIENT_DLQ_STREAM_NAME', 'DLQ')
dlq_subject = os.getenv('NATS_CLIENT_DLQ_SUBJECT', '$JS.EVENT.ADVISORY.CONSUMER.MAX_DELIVERIES.>')


# endregion

# Define the event handler function for DLQ messages
async def dlq_event_handler(msg: Msg):
    start_time = time.time()  # Record the start time
    try:
        logger.info("📥 Received a dead letter queue advisory message")

        # Parse the advisory message
        advisory = json.loads(msg.data.decode())
        stream = advisory['stream']
        consumer = advisory['consumer']
        stream_seq = advisory['stream_seq']
        # delivery_seq = advisory['deliver_seq']

        logger.info(
            f"📄 advisory Details: stream={stream}, consumer={consumer}, stream_seq={stream_seq}")

        # Retrieve the failed message from the original stream
        js = msg._client.jetstream()
        try:
            msg_info = await js.get_msg(stream, stream_seq)
            failed_msg_data = msg_info.data
            failed_msg_subject = msg_info.subject
            # If the message has headers, you can access them as well
            failed_msg_headers = msg_info.headers

            logger.error(f"🚨 failed message from stream '{stream}' at sequence '{stream_seq}': {failed_msg_data}")

            # Log the original message and its metadata
            # logger.error(f"🚨 Original failed message from stream '{stream}' at sequence '{stream_seq}':")
            # logger.error(f"Subject: {failed_msg_subject}")
            # logger.error(f"Headers: {failed_msg_headers}")
            # logger.error(f"Message: {failed_msg_data}")

            # Assume the message type is stored in headers or payload
            if "message-type" in failed_msg_headers:
                message_type = failed_msg_headers["message-type"]
            else:
                # If there's no message type in headers, fallback to some other way
                # Maybe a field in the message body or use a default
                message_type = "RembgData"  # Default type or some identifier

            # Deserialize based on the message type
            # important every message sent from API or from anyone else
            # shall contain the right message data
            # this way they can be correctly deserialized
            # see main.py in api ln 55 and 65 when JetStreamPublisher get instantiated

            if message_type == "RembgData":
                # Deserialize as RembgData
                data = RembgData()
                data.ParseFromString(failed_msg_data)
                logger.info(f"🖼️ RembgData received: {data}")
                # Process rembg_data here
                # send a message to cb api that the operation has failed

            elif message_type == "StickyDetectorData":
                # Deserialize as StickyDetectorData
                data = StickyDetectorData()
                data.ParseFromString(failed_msg_data)
                logger.info(f"🔍 StickyDetectorData received: {data}")
                # Process rembg_data here
                # send a message to cb api that the operation has failed

            else:
                logger.error(f"❓ Unknown message type: {message_type}")
                # Handle unknown types


            # Process the failed message as needed
            # For example, you might log it, send an alert, or store it for later analysis

            # Optionally, move the failed message to a separate queue, or in a database
            # notify that this went wording to the request
            logger.info(f"📤 failed message moved to....")

            # Delete the message from the original stream to keep it clean
            await js.delete_msg(stream, stream_seq)
            logger.info(f"🗑️ deleted message with sequence {stream_seq} from stream '{stream}'")

        except Exception as e:
            logger.exception(f"❌ error retrieving or deleting failed message: {e}")

        # Acknowledge the advisory message
        await msg.ack_sync()
        logger.info(f"👍 advisory message acknowledged successfully")
    except Exception as e:
        error_message = str(e) if e else "Unknown error occurred"
        logger.error(f"❌ failed to process DLQ advisory message: {error_message}")
    finally:
        end_time = time.time()  # Record the end time
        elapsed_time = end_time - start_time
        logger.info(f"⏰ total elapsed time for handling DLQ message: {elapsed_time:.2f} seconds")


async def main():
    # Start the readiness probe server in a separate thread
    readiness_probe = ReadinessProbe()
    readiness_probe_thread = threading.Thread(target=readiness_probe.start_server, daemon=True)
    readiness_probe_thread.start()

    # Circuit breaker for continuous operation
    while True:
        logger.info("🛠️starting guardian...")
        try:
            # Subscribing to JetStream advisories
            subscriber = JetStreamEventSubscriber(
                nats_url=nats_url,
                stream_name=dlq_stream_name,
                subject=dlq_subject,
                connect_timeout=nats_connect_timeout,
                reconnect_time_wait=nats_reconnect_time_wait,
                max_reconnect_attempts=nats_max_reconnect_attempts,
                ack_wait=30,  # Acknowledge wait time for advisory messages
                max_deliver=1,  # Advisory messages should not be redelivered
                proto_message_type=None  # We're dealing with JSON advisories, not Protobuf messages
            )

            subscriber.set_event_handler(dlq_event_handler)
            await subscriber.connect_and_subscribe()

            while True:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            logger.info("🛑 guardian is stopping due to keyboard interrupt")
            break
        except Exception as e:
            logger.exception(f"💀 recovering from a fatal error: {e}. The process will restart in 5 seconds...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
