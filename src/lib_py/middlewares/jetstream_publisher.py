from nats.aio.client import Client as NATS
from nats.errors import TimeoutError, NoRespondersError
from nats.js.api import StreamConfig, RetentionPolicy
from nats.js.errors import BadRequestError
import logging


class JetStreamPublisher:
    def __init__(self, subject: str, stream_name: str, nats_url: str,
                 nats_reconnect_time_wait: int,
                 nats_connect_timeout: int, nats_max_reconnect_attempts:int,
                 message_type:str):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.subject = subject
        self.stream_name = stream_name
        self.nats_url = nats_url
        self.nats_reconnect_time_wait = nats_reconnect_time_wait
        self.nats_connect_timeout = nats_connect_timeout
        self.nats_max_reconnect_attempts = nats_max_reconnect_attempts
        self.nc = NATS()
        self.js = None
        self.message_type = message_type

    async def connect(self):
        # Connect to NATS
        await self.nc.connect(servers=[self.nats_url],
                              connect_timeout=self.nats_connect_timeout,
                              reconnect_time_wait=self.nats_reconnect_time_wait,
                              max_reconnect_attempts=self.nats_max_reconnect_attempts)
        # Create JetStream context
        self.js = self.nc.jetstream()

        # Create the stream configuration
        stream_config = StreamConfig(
            name=self.stream_name,
            subjects=[self.subject],
            # A work-queue retention policy satisfies a very common use case of queuing up messages that are intended
            # to be processed once and only once. https://natsbyexample.com/examples/jetstream/workqueue-stream/go
            retention=RetentionPolicy.WORK_QUEUE
        )

        try:
            await self.js.add_stream(stream_config)
        except BadRequestError as e:
            if e.code == 400:
                self.logger.info(
                    "Jetstream stream was using a different configuration. Destroying and recreating with the right "
                    "configuration")
                try:
                    await self.js.delete_stream(stream_config.name)
                    await self.js.add_stream(stream_config)
                    self.logger.info("Jetstream stream re-created successfully")
                except Exception as e:
                    self.logger.exception(f"Exception while deleting and recreating Jetstream: {e}")

    async def publish(self, message):
        try:
            # Pass the message type as a dictionary header
            headers = {"message-type": self.message_type}

            # Publish the message with the headers
            await self.js.publish(self.subject, message.SerializeToString(), headers=headers)
            self.logger.info("✉️ Message published successfully!")
        except NoRespondersError:
            self.logger.error("❌ No responders available for request")
        except TimeoutError:
            self.logger.error("❌ Request to JetStream timed out")
        except Exception as e:
            self.logger.error(f"❌ Failed to publish message: {e}")

    async def close(self):
        await self.nc.close()