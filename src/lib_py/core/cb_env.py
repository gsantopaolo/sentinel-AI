from pydantic import BaseModel
from typing import List, Optional

class CBEnv(BaseModel):
    origin: str
    secret_key: str
    base_endpoint: Optional[str]
    cb_api_key: Optional[str]
