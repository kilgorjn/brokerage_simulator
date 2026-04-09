from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Account, TaxLot
from ..schemas import TaxLotResponse

router = APIRouter(prefix="/accounts", tags=["tax-lots"])


def _get_account_or_404(account_id: str, db: Session) -> Account:
    account = db.query(Account).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.get("/{account_id}/tax-lots", response_model=list[TaxLotResponse])
def list_tax_lots(
    account_id: str,
    include_closed: bool = False,
    db: Session = Depends(get_db),
):
    _get_account_or_404(account_id, db)
    q = db.query(TaxLot).filter_by(account_id=account_id)
    if not include_closed:
        q = q.filter_by(closed=False)
    return q.order_by(TaxLot.acquired_date.asc()).all()


@router.get("/{account_id}/tax-lots/{symbol}", response_model=list[TaxLotResponse])
def get_tax_lots_for_symbol(
    account_id: str,
    symbol: str,
    include_closed: bool = False,
    db: Session = Depends(get_db),
):
    _get_account_or_404(account_id, db)
    q = db.query(TaxLot).filter_by(account_id=account_id, symbol=symbol.upper())
    if not include_closed:
        q = q.filter_by(closed=False)
    return q.order_by(TaxLot.acquired_date.asc()).all()
