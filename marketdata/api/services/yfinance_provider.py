"""yfinance-backed quote provider with a TTL cache.

Price mapping
-------------
field           yfinance source         notes
-----------     -------------------     ------------------------------------------
price           fast_info.last_price    most recent trade; fast lightweight call
bid             ticker.info["bid"]      current bid; from heavier quoteSummary call
ask             ticker.info["ask"]      current ask; from heavier quoteSummary call

bid/ask are fetched from ticker.info in the same cache window as price.
They may be None outside market hours or when yfinance returns 0 for them.

Cache behaviour
---------------
Each symbol is cached for QUOTE_CACHE_TTL seconds (default 60).  Subsequent
requests within that window are served from memory — no yfinance call is made.
Cache entries are evicted lazily (on the next request after TTL expires).
"""
import math
import time
from datetime import datetime, timezone
from typing import NamedTuple

import yfinance as yf

from ..config import QUOTE_CACHE_TTL


class SymbolNotFound(Exception):
    """Raised when yfinance returns no usable data for a symbol."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        super().__init__(f"No market data found for symbol: {symbol}")


class Quote(NamedTuple):
    symbol: str
    price: float         # last trade price (fast_info.last_price)
    bid: float | None    # current bid, or None when unavailable
    ask: float | None    # current ask, or None when unavailable
    timestamp: datetime  # time of the underlying market data (UTC)


# ---------------------------------------------------------------------------
# In-process cache: symbol -> (Quote, monotonic_expiry)
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[Quote, float]] = {}


def _fetch_from_yfinance(symbol: str) -> Quote:
    """Hit yfinance and return a Quote.  Raises SymbolNotFound on bad data.

    yfinance is an unofficial library that can raise a variety of internal
    exceptions (KeyError, TypeError, etc.) for unrecognised or delisted
    symbols.  We catch them all and surface a clean SymbolNotFound.
    """
    # --- last price (fast) ---
    try:
        ticker = yf.Ticker(symbol)
        fi = ticker.fast_info
        raw_price = fi.last_price
    except Exception as exc:
        raise SymbolNotFound(symbol) from exc

    if raw_price is None or (isinstance(raw_price, float) and math.isnan(raw_price)):
        raise SymbolNotFound(symbol)

    price = round(float(raw_price), 4)

    # --- bid / ask / timestamp (from the heavier info call; best-effort) ---
    # ticker.info["bid"] and ticker.info["ask"] are populated during market
    # hours.  Outside hours they are typically 0.0 — we normalise those to None.
    # ticker.info["regularMarketTime"] is a Unix timestamp (int).
    bid: float | None = None
    ask: float | None = None
    ts = datetime.now(timezone.utc)
    try:
        info = ticker.info
        b = info.get("bid")
        a = info.get("ask")
        if b and float(b) > 0:
            bid = round(float(b), 4)
        if a and float(a) > 0:
            ask = round(float(a), 4)
        mt = info.get("regularMarketTime")
        if mt and isinstance(mt, (int, float)) and not math.isnan(float(mt)):
            ts = datetime.fromtimestamp(float(mt), tz=timezone.utc)
    except Exception:
        pass  # bid/ask/timestamp are nice-to-have; never fail the whole quote

    return Quote(symbol=symbol, price=price, bid=bid, ask=ask, timestamp=ts)


def get_quote(symbol: str) -> Quote:
    """Return a Quote for *symbol*, hitting the cache when fresh.

    Raises:
        SymbolNotFound: if yfinance has no usable data for the symbol.
    """
    now_mono = time.monotonic()

    cached = _cache.get(symbol)
    if cached is not None:
        quote, expires = cached
        if now_mono < expires:
            return quote

    quote = _fetch_from_yfinance(symbol)
    _cache[symbol] = (quote, now_mono + QUOTE_CACHE_TTL)
    return quote


def get_quotes(symbols: list[str]) -> list[Quote]:
    """Return quotes for multiple symbols.  Symbols with no data are omitted."""
    results: list[Quote] = []
    for symbol in symbols:
        try:
            results.append(get_quote(symbol))
        except SymbolNotFound:
            pass
    return results


def cache_stats() -> dict:
    """Return basic cache diagnostics (useful for the /health endpoint)."""
    now_mono = time.monotonic()
    total = len(_cache)
    fresh = sum(1 for _, (_, exp) in _cache.items() if now_mono < exp)
    return {"cached_symbols": total, "fresh_entries": fresh, "ttl_seconds": QUOTE_CACHE_TTL}
