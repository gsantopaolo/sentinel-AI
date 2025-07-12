import logging
from typing import Dict, Any
from .base import Alerter

logger = logging.getLogger(__name__)

class FakeMessageAlerter(Alerter):
    """A fake alerter that simulates sending a message to an external service."""

    async def send_alert(self, subject: str, message: str, details: Dict[str, Any]):
        """Simulates sending an alert by logging to the console.

        Args:
            subject (str): The subject of the alert.
            message (str): The main alert message.
            details (Dict[str, Any]): A dictionary of additional details.
        """
        logger.info(
            f"\n--- FAKE MESSAGE SENT TO SLACK/EMAIL ---\n"
            f"Subject: {subject}\n"
            f"Message: {message}\n"
            f"Details: {details}\n"
            f"-----------------------------------------"
        )
