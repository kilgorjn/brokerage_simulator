from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import HOST, PORT, QUOTE_CACHE_TTL
from .routers import quotes
from .schemas import CacheStatsResponse
from .services.yfinance_provider import cache_stats

app = FastAPI(
    title="Marketdata API",
    description="Real-time equity quotes via yfinance.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(quotes.router)


@app.get("/", tags=["root"])
def root():
    return {
        "service": "Marketdata API",
        "docs": "/docs",
        "quote_cache_ttl_seconds": QUOTE_CACHE_TTL,
    }


@app.get("/health", tags=["root"], response_model=CacheStatsResponse)
def health():
    """Basic liveness check + cache diagnostics."""
    return cache_stats()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("marketdata.api.main:app", host=HOST, port=PORT, reload=True)
