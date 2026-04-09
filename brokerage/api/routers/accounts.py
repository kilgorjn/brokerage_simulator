from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_quotes
from ..models import Account, EntryType, LedgerEntry
from ..schemas import (
    AccountCreate,
    AccountResponse,
    BalanceResponse,
    BuyingPowerResponse,
    LedgerEntryResponse,
    TransferRequest,
)
from ..services.order_execution import get_buying_power, get_cash_balance
from ..services.quotes_client import QuotesClient

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _get_account_or_404(account_id: str, db: Session) -> Account:
    account = db.query(Account).filter_by(id=account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _assert_account_open(account: Account) -> None:
    if account.closed_at is not None:
        raise HTTPException(status_code=409, detail="Account is closed")


@router.get("", response_model=list[AccountResponse])
def list_accounts(db: Session = Depends(get_db)):
    """Return all accounts ordered by creation date."""
    return db.query(Account).order_by(Account.created_at.asc()).all()


@router.post("", response_model=AccountResponse, status_code=201)
def create_account(body: AccountCreate, db: Session = Depends(get_db)):
    account = Account(name=body.name)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(account_id: str, db: Session = Depends(get_db)):
    return _get_account_or_404(account_id, db)


@router.get("/{account_id}/balance", response_model=BalanceResponse)
def get_balance(account_id: str, db: Session = Depends(get_db)):
    _get_account_or_404(account_id, db)
    return BalanceResponse(
        account_id=account_id,
        cash_balance=get_cash_balance(db, account_id),
    )


@router.get("/{account_id}/buying-power", response_model=BuyingPowerResponse)
def buying_power(
    account_id: str,
    db: Session = Depends(get_db),
    quotes: QuotesClient = Depends(get_quotes),
):
    """Return available buying power for the account.

    buying_power = cash_balance - estimated cost of all pending buy orders.
    Pending buy costs are estimated using the current ask price from the
    quotes service. Optimistic when any symbols are unpriced (check
    unpriced_symbols in the response).
    """
    _get_account_or_404(account_id, db)
    return get_buying_power(db, account_id, quotes)


@router.post("/{account_id}/deposit", response_model=LedgerEntryResponse, status_code=201)
def deposit(account_id: str, body: TransferRequest, db: Session = Depends(get_db)):
    account = _get_account_or_404(account_id, db)
    _assert_account_open(account)
    cash = get_cash_balance(db, account_id)
    entry = LedgerEntry(
        account_id=account_id,
        entry_type=EntryType.DEPOSIT,
        amount=body.amount,
        balance_after=cash + body.amount,
        description=body.description or f"Deposit {body.amount}",
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/{account_id}/withdraw", response_model=LedgerEntryResponse, status_code=201)
def withdraw(account_id: str, body: TransferRequest, db: Session = Depends(get_db)):
    account = _get_account_or_404(account_id, db)
    _assert_account_open(account)
    cash = get_cash_balance(db, account_id)
    if body.amount > cash:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient cash: have {cash:.2f}, requested {body.amount:.2f}",
        )
    entry = LedgerEntry(
        account_id=account_id,
        entry_type=EntryType.WITHDRAWAL,
        amount=-body.amount,
        balance_after=cash - body.amount,
        description=body.description or f"Withdrawal {body.amount}",
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/{account_id}/fee", response_model=LedgerEntryResponse, status_code=201)
def apply_fee(account_id: str, body: TransferRequest, db: Session = Depends(get_db)):
    account = _get_account_or_404(account_id, db)
    _assert_account_open(account)
    cash = get_cash_balance(db, account_id)
    entry = LedgerEntry(
        account_id=account_id,
        entry_type=EntryType.FEE,
        amount=-body.amount,
        balance_after=cash - body.amount,
        description=body.description or f"Fee {body.amount}",
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/{account_id}/reward", response_model=LedgerEntryResponse, status_code=201)
def apply_reward(account_id: str, body: TransferRequest, db: Session = Depends(get_db)):
    account = _get_account_or_404(account_id, db)
    _assert_account_open(account)
    cash = get_cash_balance(db, account_id)
    entry = LedgerEntry(
        account_id=account_id,
        entry_type=EntryType.REWARD,
        amount=body.amount,
        balance_after=cash + body.amount,
        description=body.description or f"Reward {body.amount}",
        created_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.get("/{account_id}/ledger", response_model=list[LedgerEntryResponse])
def get_ledger(
    account_id: str,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    _get_account_or_404(account_id, db)
    return (
        db.query(LedgerEntry)
        .filter_by(account_id=account_id)
        .order_by(LedgerEntry.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.patch("/{account_id}/close", response_model=AccountResponse)
def close_account(account_id: str, db: Session = Depends(get_db)):
    """Close an account. Closed accounts are read-only and cannot accept new activity."""
    account = _get_account_or_404(account_id, db)
    _assert_account_open(account)
    account.closed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(account)
    return account
