from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_quotes
from ..models import Account
from ..schemas import RealizedPnlResponse, UnrealizedPnlResponse
from ..services.pnl_service import get_realized_pnl, get_unrealized_pnl
from ..services.quotes_client import QuotesClient

router = APIRouter(prefix="/accounts", tags=["pnl"])


def _get_account_or_404(account_id: str, db: Session) -> Account:
    account = db.query(Account).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.get("/{account_id}/pnl/realized", response_model=RealizedPnlResponse)
def realized_pnl(account_id: str, db: Session = Depends(get_db)):
    """Return realized P&L aggregated by symbol.

    Derived from lot_closures — one record is written for every partial or
    full lot consumed by a sell order. No quotes API call required.
    """
    _get_account_or_404(account_id, db)
    return get_realized_pnl(db, account_id)


@router.get("/{account_id}/pnl/unrealized", response_model=UnrealizedPnlResponse)
def unrealized_pnl(
    account_id: str,
    db: Session = Depends(get_db),
    quotes: QuotesClient = Depends(get_quotes),
):
    """Return unrealized P&L for all open positions, marked to current market price.

    Positions whose symbol cannot be quoted are included with null price/pnl
    fields and listed in unpriced_symbols.
    """
    _get_account_or_404(account_id, db)
    return get_unrealized_pnl(db, account_id, quotes)
