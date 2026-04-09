from fastapi import APIRouter, HTTPException, Query

from ..schemas import QuoteResponse
from ..services.yfinance_provider import SymbolNotFound, get_quote, get_quotes

router = APIRouter(prefix="/quotes", tags=["quotes"])


@router.get("/{symbol}", response_model=QuoteResponse)
def quote_single(symbol: str):
    """Return the current market price for a single symbol.

    Prices are cached for QUOTE_CACHE_TTL seconds to avoid overwhelming yfinance.
    """
    try:
        q = get_quote(symbol.upper())
    except SymbolNotFound:
        raise HTTPException(status_code=404, detail=f"No market data for {symbol.upper()}")
    return QuoteResponse(symbol=q.symbol, price=q.price, bid=q.bid, ask=q.ask, timestamp=q.timestamp)


@router.get("", response_model=list[QuoteResponse])
def quote_batch(
    symbols: str = Query(..., description="Comma-separated list of ticker symbols, e.g. AAPL,MSFT,GOOGL"),
):
    """Return current market prices for multiple symbols in one call.

    Symbols with no available data are silently omitted from the response.
    """
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not symbol_list:
        raise HTTPException(status_code=422, detail="At least one symbol is required")
    results = get_quotes(symbol_list)
    return [QuoteResponse(symbol=q.symbol, price=q.price, bid=q.bid, ask=q.ask, timestamp=q.timestamp) for q in results]
