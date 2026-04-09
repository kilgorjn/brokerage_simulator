from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Account, Position
from ..schemas import PositionResponse

router = APIRouter(prefix="/accounts", tags=["positions"])


def _get_account_or_404(account_id: str, db: Session) -> Account:
    account = db.query(Account).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.get("/{account_id}/positions", response_model=list[PositionResponse])
def list_positions(account_id: str, db: Session = Depends(get_db)):
    _get_account_or_404(account_id, db)
    return db.query(Position).filter_by(account_id=account_id).all()


@router.get("/{account_id}/positions/{symbol}", response_model=PositionResponse)
def get_position(account_id: str, symbol: str, db: Session = Depends(get_db)):
    _get_account_or_404(account_id, db)
    position = db.query(Position).filter_by(
        account_id=account_id, symbol=symbol.upper()
    ).first()
    if not position:
        raise HTTPException(status_code=404, detail=f"No open position for {symbol.upper()}")
    return position
