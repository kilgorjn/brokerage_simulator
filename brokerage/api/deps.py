"""FastAPI dependency helpers."""
from fastapi import Request

from .services.quotes_client import QuotesClient


def get_quotes(request: Request) -> QuotesClient:
    """Inject the shared QuotesClient stored on app.state."""
    return request.app.state.quotes
