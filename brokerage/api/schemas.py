from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

from .models import EntryType, OrderSide, OrderStatus, OrderType, TimeInForce


class AccountCreate(BaseModel):
    name: str


class AccountResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    closed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BalanceResponse(BaseModel):
    account_id: str
    cash_balance: Decimal


class TransferRequest(BaseModel):
    amount: Decimal
    description: str = ""

    @field_validator("amount")
    @classmethod
    def must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v


class PlaceOrderRequest(BaseModel):
    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    time_in_force: TimeInForce = TimeInForce.GTC

    @field_validator("quantity")
    @classmethod
    def must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("must be positive")
        return v

    @field_validator("limit_price")
    @classmethod
    def validate_limit_price_positive(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= 0:
            raise ValueError("limit_price must be positive")
        return v

    @field_validator("stop_price")
    @classmethod
    def validate_stop_price_positive(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= 0:
            raise ValueError("stop_price must be positive")
        return v

    @model_validator(mode="after")
    def validate_order_type_prices(self):
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for LIMIT orders")
        if self.order_type == OrderType.STOP and self.stop_price is None:
            raise ValueError("stop_price is required for STOP orders")
        if self.order_type == OrderType.STOP_LIMIT:
            if self.stop_price is None:
                raise ValueError("stop_price is required for STOP_LIMIT orders")
            if self.limit_price is None:
                raise ValueError("limit_price is required for STOP_LIMIT orders")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("limit_price is not allowed for MARKET orders")
        if self.order_type == OrderType.MARKET and self.stop_price is not None:
            raise ValueError("stop_price is not allowed for MARKET orders")
        if self.order_type == OrderType.LIMIT and self.stop_price is not None:
            raise ValueError("stop_price is not allowed for LIMIT orders")
        if self.order_type == OrderType.STOP and self.limit_price is not None:
            raise ValueError("limit_price is not allowed for STOP orders")
        return self


class OrderResponse(BaseModel):
    id: str
    account_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    fill_price: Optional[Decimal]   # null while PENDING
    total_value: Optional[Decimal]  # null while PENDING
    status: OrderStatus
    reject_reason: Optional[str]
    order_type: OrderType
    limit_price: Optional[Decimal]
    stop_price: Optional[Decimal]
    triggered: bool
    time_in_force: Optional[TimeInForce]
    expires_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class LedgerEntryResponse(BaseModel):
    id: str
    account_id: str
    entry_type: EntryType
    amount: Decimal
    balance_after: Decimal
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PositionResponse(BaseModel):
    id: str
    account_id: str
    symbol: str
    quantity: Decimal
    avg_cost: Decimal
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaxLotResponse(BaseModel):
    id: str
    account_id: str
    symbol: str
    quantity: Decimal
    cost_per_share: Decimal
    cost_basis: Decimal       # cost_per_share × original quantity at acquisition
    acquired_date: datetime
    order_id: Optional[str]
    closed: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MarketStatusResponse(BaseModel):
    is_open: bool
    next_open: datetime  # UTC


class WatcherHealthResponse(BaseModel):
    market_open: bool
    last_cycle_at: Optional[datetime] = None
    last_processed_at: Optional[datetime] = None
    last_order_count: int
    pending_order_count: int


class BuyingPowerResponse(BaseModel):
    account_id: str
    cash_balance: Decimal
    reserved_for_pending_buys: Decimal  # estimated cost of open pending buy orders
    buying_power: Decimal               # cash_balance - reserved_for_pending_buys
    pending_buy_count: int
    unpriced_symbols: list[str]         # pending buy symbols whose quote was unavailable


# ---------------------------------------------------------------------------
# P&L schemas
# ---------------------------------------------------------------------------

class RealizedPnlBySymbol(BaseModel):
    symbol: str
    realized_pnl: Decimal
    closure_count: int    # number of lot-close events contributing to this total


class RealizedPnlResponse(BaseModel):
    account_id: str
    total_realized_pnl: Decimal
    by_symbol: list[RealizedPnlBySymbol]


class UnrealizedPnlBySymbol(BaseModel):
    symbol: str
    quantity: Decimal
    avg_cost: Decimal
    current_price: Optional[Decimal]    # None when quote unavailable
    cost_basis: Decimal                 # avg_cost × quantity
    market_value: Optional[Decimal]     # None when quote unavailable
    unrealized_pnl: Optional[Decimal]   # None when quote unavailable
    unrealized_pnl_pct: Optional[Decimal]


class UnrealizedPnlResponse(BaseModel):
    account_id: str
    total_cost_basis: Decimal
    total_market_value: Decimal         # priced positions only
    total_unrealized_pnl: Decimal       # priced positions only
    by_symbol: list[UnrealizedPnlBySymbol]
    unpriced_symbols: list[str]
