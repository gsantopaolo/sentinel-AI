import logging
from typing import Dict, Any
from .base import Alerter

logger = logging.getLogger(__name__)

class LoggingAlerter(Alerter):
    """An alerter that sends alerts to the system log."""

    async def send_alert(self, subject: str, message: str, details: Dict[str, Any]):
        """Sends a detailed alert to the logger.

        Args:
            subject (str): The subject of the alert.
            message (str): The main alert message.
            details (Dict[str, Any]): A dictionary of additional details.
        """
        logger.critical(
            f"\n🚨 DEAD-LETTER ALERT 🚨\n"
            f"- Subject: {subject}\n"
            f"- Message: {message}\n"
            f"- Details: {details}"
        )
