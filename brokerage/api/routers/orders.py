from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_quotes
from ..models import Account, Order, OrderStatus
from ..schemas import OrderResponse, PlaceOrderRequest
from ..services.order_execution import place_order
from ..services.quotes_client import QuotesClient

router = APIRouter(prefix="/accounts", tags=["orders"])


def _get_account_or_404(account_id: str, db: Session) -> Account:
    account = db.query(Account).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _assert_account_open(account: Account) -> None:
    if account.closed_at is not None:
        raise HTTPException(status_code=409, detail="Account is closed")


@router.post("/{account_id}/orders", response_model=OrderResponse, status_code=201)
def submit_order(
    account_id: str,
    body: PlaceOrderRequest,
    db: Session = Depends(get_db),
    quotes: QuotesClient = Depends(get_quotes),
):
    """Submit a market, limit, stop, or stop-limit order.

    - **Market orders**: fill immediately when market is open (at current ask/bid).
    - **Limit orders**: fill when price condition is met; checked every 30s during market hours.
    - **Stop orders**: fill when trigger price is crossed; fills at market price.
    - **Stop-limit orders**: fill when both trigger (stop) and limit prices are crossed.
    - **DAY orders**: expire at market close (16:00 ET); GTC orders persist.
    """
    account = _get_account_or_404(account_id, db)
    _assert_account_open(account)
    return place_order(
        db,
        account_id,
        body.symbol.upper(),
        body.side,
        body.quantity,
        quotes,
        order_type=body.order_type,
        limit_price=body.limit_price,
        stop_price=body.stop_price,
        time_in_force=body.time_in_force,
    )


@router.get("/{account_id}/orders", response_model=list[OrderResponse])
def list_orders(
    account_id: str,
    symbol: str | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    _get_account_or_404(account_id, db)
    q = db.query(Order).filter_by(account_id=account_id)
    if symbol:
        q = q.filter_by(symbol=symbol.upper())
    return q.order_by(Order.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/{account_id}/orders/{order_id}", response_model=OrderResponse)
def get_order(account_id: str, order_id: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter_by(id=order_id, account_id=account_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.delete("/{account_id}/orders/{order_id}", response_model=OrderResponse)
def cancel_order(account_id: str, order_id: str, db: Session = Depends(get_db)):
    """Cancel a pending order. Only PENDING orders can be cancelled."""
    order = db.query(Order).filter_by(id=order_id, account_id=account_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel a {order.status.value} order"
        )
    order.status = OrderStatus.REJECTED
    order.reject_reason = "Cancelled by user"
    db.commit()
    db.refresh(order)
    return order
