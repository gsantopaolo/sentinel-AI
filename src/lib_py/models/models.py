#region imports
from pydantic import BaseModel, PositiveFloat
from typing import Tuple


#endregion

class Item(BaseModel):
    project_id: int
    tile_id: str
    image_url: str
    target_coordinates: Tuple[float, float]  # Tuple for x and y as integers
    scale: PositiveFloat  # Ensures scale is a positive float
    signalr_connection_id: str
