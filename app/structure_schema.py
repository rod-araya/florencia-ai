from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal

TrendT = Literal["UP","DOWN","SIDEWAYS"]
DirT = Literal["BULLISH","BEARISH"]

class Swing(BaseModel):
    type: Literal["H","L"]
    ts: str
    price: float

class Leg(BaseModel):
    high_ts: str
    high_price: float
    low_ts: str
    low_price: float

class Choch(BaseModel):
    detected: bool
    direction: Optional[DirT] = None
    broken_level_type: Optional[Literal["HL","LH"]] = None
    broken_level_price: Optional[float] = None
    break_close_ts: Optional[str] = None
    leg: Optional[Leg] = None

class PostChochSwing(BaseModel):
    exists: bool
    type: Optional[Literal["LH","HL"]] = None
    ts: Optional[str] = None
    price: Optional[float] = None

class Validity(BaseModel):
    broke_on_close: bool
    notes: Optional[str] = ""

class StructureReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    trend: TrendT
    last_swings: List[Swing]
    choch: Choch
    post_choch_swing: PostChochSwing
    validity_checks: Validity
    confidence: float
