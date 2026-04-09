import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

from .config import QUOTES_API_URL
from .database import Base, SessionLocal, engine
from .routers import accounts, orders, positions, tax_lots, pnl as pnl_router
from .routers import market as market_router
from .services.market_hours import is_market_open
from .services.order_execution import process_pending_orders
from .services.quotes_client import QuotesClient


async def _market_open_watcher(quotes: QuotesClient, app: FastAPI) -> None:
    """Background task: process pending orders continuously during market hours.

    - Checks every 30 seconds while the market is open.
    - Enables limit orders to be evaluated throughout the trading session.
    - Idempotent: FILLED/REJECTED orders are skipped, no harm from repeated calls.
    """
    logger.info("Order processing watcher started")
    while True:
        await asyncio.sleep(30)
        if is_market_open():
            db = SessionLocal()
            try:
                processed = process_pending_orders(db, quotes)
                now = datetime.now(timezone.utc)
                app.state.watcher_last_cycle_at = now
                if processed:
                    app.state.watcher_last_processed_at = now
                    app.state.watcher_last_order_count = len(processed)
                logger.info(f"Watcher cycle complete: {len(processed)} orders processed")
            except Exception as e:
                logger.error(f"Watcher cycle error: {e}", exc_info=True)
            finally:
                db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Brokerage API starting up")
    Base.metadata.create_all(bind=engine)
    quotes = QuotesClient(QUOTES_API_URL)
    app.state.quotes = quotes
    app.state.watcher_last_cycle_at = None
    app.state.watcher_last_processed_at = None
    app.state.watcher_last_order_count = 0
    task = asyncio.create_task(_market_open_watcher(quotes, app))
    yield
    logger.info("Brokerage API shutting down")
    task.cancel()
    quotes.close()


app = FastAPI(
    title="Brokerage API",
    description="Simulated brokerage for testing trading strategies.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market_router.router)
app.include_router(accounts.router)
app.include_router(orders.router)
app.include_router(positions.router)
app.include_router(tax_lots.router)
app.include_router(pnl_router.router)


@app.get("/", tags=["root"])
def root():
    return {
        "service": "Brokerage API",
        "docs": "/docs",
        "quotes_api": QUOTES_API_URL,
    }


if __name__ == "__main__":
    import uvicorn
    from .config import HOST, PORT
    uvicorn.run("brokerage.api.main:app", host=HOST, port=PORT, reload=True)
