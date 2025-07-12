from abc import ABC, abstractmethod
from typing import Dict, Any

class Alerter(ABC):
    """Abstract base class for an alerter."""

    @abstractmethod
    async def send_alert(self, subject: str, message: str, details: Dict[str, Any]):
        """Send an alert."""
        pass
