from pydantic import BaseModel
from typing import List, Optional


class ForecastReq(BaseModel):
    horizons: List[int] = [7, 14, 28]


class AckReq(BaseModel):
    id: str


class ForecastResp(BaseModel):
    status: str
    run_id: Optional[str] = None
    skus: Optional[int] = None

