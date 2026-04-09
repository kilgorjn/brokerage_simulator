from datetime import datetime

from pydantic import BaseModel


class QuoteResponse(BaseModel):
    symbol: str
    price: float          # last trade price
    bid: float | None     # current bid; None when unavailable (after hours, etc.)
    ask: float | None     # current ask; None when unavailable
    timestamp: datetime   # UTC time of the underlying market data


class CacheStatsResponse(BaseModel):
    cached_symbols: int
    fresh_entries: int
    ttl_seconds: int
