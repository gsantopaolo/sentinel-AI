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

from typing import Dict, Any, Optional, List, TypedDict
import json
from dataclasses import dataclass

# Import from src.lib_py
from src.lib_py.middlewares.jetstream_event_subscriber import JetStreamEventSubscriber
from src.lib_py.middlewares.readiness_probe import ReadinessProbe
from src.lib_py.middlewares.jetstream_publisher import JetStreamPublisher

# Define type aliases for message handling
class MessageHeaders(TypedDict, total=False):
    """Type definition for message headers."""
    message_type: str
    # Add other expected headers here

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

@dataclass
class MessageInfo:
    data: bytes
    subject: str
    headers: dict

# Define the event handler function for DLQ messages
async def dlq_event_handler(msg: Msg) -> None:
    """Handle dead letter queue advisory messages.
    
    Args:
        msg: The message from the dead letter queue.
    """
    start_time = time.time()
    logger.info("📥 Received a dead letter queue advisory message")
    
    try:
        # Parse the advisory message
        try:
            advisory = json.loads(msg.data.decode())
            stream = advisory.get('stream')
            consumer = advisory.get('consumer')
            stream_seq = advisory.get('stream_seq')
            
            if not all([stream, consumer, stream_seq]):
                raise ValueError("Missing required fields in advisory message")
                
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            logger.error(f"❌ Failed to parse advisory message: {str(e)}")
            await msg.ack_sync()
            return
            
        logger.info(f"📄 Advisory Details - Stream: {stream}, Consumer: {consumer}, Sequence: {stream_seq}")
        
        # Process the failed message
        js = msg._client.jetstream()
        await _process_failed_message(js, stream, stream_seq)
        
        # Acknowledge the advisory message
        await msg.ack_sync()
        logger.info("👍 Advisory message acknowledged successfully")
        
    except Exception as e:
        logger.error(f"❌ Failed to process DLQ advisory message: {str(e)}", exc_info=True)
    finally:
        elapsed_time = time.time() - start_time
        logger.info(f"⏰ Total elapsed time for handling DLQ message: {elapsed_time:.2f} seconds")

async def _process_failed_message(js, stream: str, stream_seq: int) -> None:
    """Process a single failed message from the stream.
    
    Args:
        js: JetStream context
        stream: Name of the stream
        stream_seq: Sequence number of the message
    """
    try:
        # Get the failed message
        msg_info = await js.get_msg(stream, stream_seq)
        if not msg_info:
            logger.error(f"❌ Failed to retrieve message {stream_seq} from stream '{stream}'")
            return
            
        # Extract message details
        message_info = MessageInfo(
            data=msg_info.data,
            subject=msg_info.subject,
            headers=getattr(msg_info, 'headers', {}) or {}
        )
        
        logger.error(f"🚨 Failed message from stream '{stream}' at sequence {stream_seq}")
        
        # Process based on message type
        message_type = message_info.headers.get("message-type", "unknown").lower()
        
        try:
            # Try to decode as JSON first
            try:
                message_data = json.loads(message_info.data.decode('utf-8'))
                logger.info(f"📨 Processing JSON message of type: {message_type}")
                logger.debug(f"Message data: {message_data}")
                
                # Here you can add specific processing based on message_type
                # For example:
                # if message_type == "some_type":
                #     await _process_some_type(message_data)
                # else:
                #     logger.warning(f"No specific handler for message type: {message_type}")
                
            except json.JSONDecodeError:
                # If not JSON, process as binary data
                logger.info(f"📨 Processing binary message of type: {message_type} (size: {len(message_info.data)} bytes)")
                # Here you can add binary data processing if needed
                
        except Exception as e:
            logger.error(f"❌ Error processing message: {str(e)}", exc_info=True)
            
        # Clean up the failed message
        await js.delete_msg(stream, stream_seq)
        logger.info(f"🗑️ Deleted message with sequence {stream_seq} from stream '{stream}'")
        
    except Exception as e:
        logger.error(f"❌ Error processing failed message: {str(e)}", exc_info=True)
        raise

async def _process_generic_message(data: bytes, message_type: str) -> None:
    """Process a generic message.
    
    Args:
        data: The message data (bytes)
        message_type: Type of the message
    """
    try:
        # Try to decode as JSON first
        try:
            message = json.loads(data.decode('utf-8'))
            logger.info(f"📨 Processed {message_type} message: {json.dumps(message, indent=2)}")
        except json.JSONDecodeError:
            # If not JSON, log as binary data
            logger.info(f"📨 Processed binary {message_type} message (size: {len(data)} bytes)")
            
        # Here you can add any generic message processing logic
        # For example, you might want to:
        # 1. Log the message
        # 2. Send notifications
        # 3. Store the message in a database
        # 4. Forward to another service
        
    except Exception as e:
        logger.error(f"❌ Error processing {message_type} message: {str(e)}", exc_info=True)
        raise


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
