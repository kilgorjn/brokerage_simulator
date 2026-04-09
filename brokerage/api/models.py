import enum
import uuid
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class EntryType(str, enum.Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    BUY = "BUY"
    SELL = "SELL"
    FEE = "FEE"
    REWARD = "REWARD"


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"


class OrderType(str, enum.Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, enum.Enum):
    GTC = "GTC"
    DAY = "DAY"


class Account(Base):
    __tablename__ = "accounts"

    id = Column(String, primary_key=True, default=_new_id)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    closed_at = Column(DateTime, nullable=True, default=None)

    ledger_entries = relationship("LedgerEntry", back_populates="account")
    orders = relationship("Order", back_populates="account")
    positions = relationship("Position", back_populates="account")
    tax_lots = relationship("TaxLot", back_populates="account")
    lot_closures = relationship("LotClosure", back_populates="account")


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id = Column(String, primary_key=True, default=_new_id)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    entry_type = Column(SAEnum(EntryType), nullable=False)
    amount = Column(Numeric(18, 8), nullable=False)
    balance_after = Column(Numeric(18, 8), nullable=False)
    description = Column(String, nullable=False, default="")
    created_at = Column(DateTime, default=_utcnow)

    account = relationship("Account", back_populates="ledger_entries")


class Order(Base):
    __tablename__ = "orders"

    id = Column(String, primary_key=True, default=_new_id)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(SAEnum(OrderSide), nullable=False)
    quantity = Column(Numeric(18, 8), nullable=False)
    fill_price = Column(Numeric(18, 8), nullable=True)   # null while PENDING
    total_value = Column(Numeric(18, 8), nullable=True)  # null while PENDING
    status = Column(SAEnum(OrderStatus), nullable=False)
    reject_reason = Column(String, nullable=True)
    order_type = Column(SAEnum(OrderType), nullable=False, default=OrderType.MARKET)
    limit_price = Column(Numeric(18, 8), nullable=True)
    stop_price = Column(Numeric(18, 8), nullable=True)
    triggered = Column(Boolean, default=False, nullable=False)
    time_in_force = Column(SAEnum(TimeInForce), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    account = relationship("Account", back_populates="orders")
    tax_lots = relationship("TaxLot", back_populates="order")
    lot_closures = relationship("LotClosure", back_populates="order")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("account_id", "symbol"),)

    id = Column(String, primary_key=True, default=_new_id)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False)
    quantity = Column(Numeric(18, 8), nullable=False)
    avg_cost = Column(Numeric(18, 8), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)

    account = relationship("Account", back_populates="positions")


class TaxLot(Base):
    __tablename__ = "tax_lots"

    id = Column(String, primary_key=True, default=_new_id)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    quantity = Column(Numeric(18, 8), nullable=False)
    cost_per_share = Column(Numeric(18, 8), nullable=False)
    cost_basis = Column(Numeric(18, 8), nullable=False)  # cost_per_share × original quantity; immutable
    acquired_date = Column(DateTime, nullable=False)
    order_id = Column(String, ForeignKey("orders.id"), nullable=True)
    closed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    account = relationship("Account", back_populates="tax_lots")
    order = relationship("Order", back_populates="tax_lots")
    closures = relationship("LotClosure", back_populates="tax_lot")


class LotClosure(Base):
    """Records each partial or full consumption of a tax lot during a sell fill.

    One row is written per lot touched per sell order, enabling precise
    realized P&L calculation even across partially-consumed lots.
    """
    __tablename__ = "lot_closures"

    id = Column(String, primary_key=True, default=_new_id)
    tax_lot_id = Column(String, ForeignKey("tax_lots.id"), nullable=False, index=True)
    account_id = Column(String, ForeignKey("accounts.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    order_id = Column(String, ForeignKey("orders.id"), nullable=False)
    quantity_closed = Column(Numeric(18, 8), nullable=False)
    cost_per_share = Column(Numeric(18, 8), nullable=False)  # copied from lot at close time
    close_price = Column(Numeric(18, 8), nullable=False)
    realized_pnl = Column(Numeric(18, 8), nullable=False)    # (close_price - cost_per_share) × quantity_closed
    created_at = Column(DateTime, default=_utcnow)

    tax_lot = relationship("TaxLot", back_populates="closures")
    account = relationship("Account", back_populates="lot_closures")
    order = relationship("Order", back_populates="lot_closures")
