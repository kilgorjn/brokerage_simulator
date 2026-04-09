"""HTTP client for the marketdata quotes service.

Expected quotes API contract:
    GET /quotes/{symbol}
    200 OK  → {"symbol":"AAPL","price":255.92,"bid":255.90,"ask":255.94,"timestamp":"..."}
    404     → symbol not found / no data
"""
from datetime import datetime
from decimal import Decimal
from typing import NamedTuple

import httpx


class QuoteUnavailable(Exception):
    """Raised when the quotes service cannot supply a price for a symbol."""

    def __init__(self, symbol: str, reason: str) -> None:
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"Quote unavailable for {symbol}: {reason}")


class MarketQuote(NamedTuple):
    symbol: str
    price: Decimal        # last trade price — fallback when bid/ask are None
    bid: Decimal | None   # None outside market hours or when feed lacks data
    ask: Decimal | None   # None outside market hours or when feed lacks data
    timestamp: datetime


class QuotesClient:
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = httpx.Client(timeout=5.0)

    def get_quote(self, symbol: str) -> MarketQuote:
        """Fetch a full quote (price, bid, ask) for *symbol*.

        Raises QuoteUnavailable if the service is unreachable, returns a
        non-2xx status, or the response body is malformed.
        """
        url = f"{self._base_url}/quotes/{symbol.upper()}"
        try:
            r = self._http.get(url)
            r.raise_for_status()
            body = r.json()
            bid_raw = body.get("bid")
            ask_raw = body.get("ask")
            return MarketQuote(
                symbol=body["symbol"],
                price=Decimal(str(body["price"])),
                bid=Decimal(str(bid_raw)) if bid_raw is not None else None,
                ask=Decimal(str(ask_raw)) if ask_raw is not None else None,
                timestamp=datetime.fromisoformat(body["timestamp"]),
            )
        except httpx.HTTPStatusError as exc:
            raise QuoteUnavailable(
                symbol, f"quotes service returned {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise QuoteUnavailable(
                symbol, f"quotes service unreachable: {exc}"
            ) from exc
        except (KeyError, ValueError) as exc:
            raise QuoteUnavailable(
                symbol, f"unexpected response format: {exc}"
            ) from exc

    def close(self) -> None:
        self._http.close()
