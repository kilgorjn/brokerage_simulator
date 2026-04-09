from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_quotes
from ..models import Order, OrderStatus
from ..schemas import MarketStatusResponse, OrderResponse, WatcherHealthResponse
from ..services.market_hours import is_market_open, next_market_open
from ..services.order_execution import process_pending_orders
from ..services.quotes_client import QuotesClient

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/status", response_model=MarketStatusResponse)
def market_status():
    """Return whether the US equity market is currently open and when it next opens."""
    now = datetime.now(timezone.utc)
    return MarketStatusResponse(
        is_open=is_market_open(now),
        next_open=next_market_open(now),
    )


@router.post("/process-queue", response_model=list[OrderResponse])
def process_queue(
    db: Session = Depends(get_db),
    quotes: QuotesClient = Depends(get_quotes),
):
    """Manually trigger fill of all PENDING orders at current market prices.

    Normally called automatically when the market opens. Useful when an agent
    wants to advance the simulation or recover from a quotes service outage.
    Orders whose symbol has no available quote remain PENDING.
    """
    return process_pending_orders(db, quotes)


@router.get("/health", response_model=WatcherHealthResponse)
def market_health(request: Request, db: Session = Depends(get_db)):
    """Return watcher health: market state, last cycle time, and pending order count."""
    pending_count = db.query(Order).filter_by(status=OrderStatus.PENDING).count()
    return WatcherHealthResponse(
        market_open=is_market_open(),
        last_cycle_at=getattr(request.app.state, "watcher_last_cycle_at", None),
        last_processed_at=getattr(request.app.state, "watcher_last_processed_at", None),
        last_order_count=getattr(request.app.state, "watcher_last_order_count", 0),
        pending_order_count=pending_count,
    )
