import logging
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from ..models import (
    EntryType,
    LedgerEntry,
    LotClosure,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    TaxLot,
    TimeInForce,
)
from .market_hours import earliest_order_processing_time, is_market_open, latest_order_processing_time, next_market_close
from .quotes_client import MarketQuote, QuoteUnavailable, QuotesClient


def _fill_price_from_quote(quote: MarketQuote, side: OrderSide) -> Decimal:
    """Select the appropriate fill price for the order side.

    BUY  → ask price (what the market sells at); falls back to last price.
    SELL → bid price (what the market buys at);  falls back to last price.
    """
    if side == OrderSide.BUY:
        return quote.ask if quote.ask is not None else quote.price
    return quote.bid if quote.bid is not None else quote.price


def _limit_condition_met(order: Order, quote: MarketQuote) -> bool:
    """Check if a limit order's price condition is met.

    BUY limit:  condition met when ask <= limit_price (fallback to price if ask is None)
    SELL limit: condition met when bid >= limit_price (fallback to price if bid is None)
    """
    limit = Decimal(str(order.limit_price))
    if order.side == OrderSide.BUY:
        price = quote.ask if quote.ask is not None else quote.price
        return Decimal(str(price)) <= limit
    else:
        price = quote.bid if quote.bid is not None else quote.price
        return Decimal(str(price)) >= limit


def _stop_condition_met(order: Order, quote: MarketQuote) -> bool:
    """Check if a stop order's trigger condition is met.

    STOP BUY:  triggers when ask >= stop_price (price has risen to entry level)
    STOP SELL: triggers when bid <= stop_price (price has fallen to stop-loss level)
    """
    stop = Decimal(str(order.stop_price))
    if order.side == OrderSide.BUY:
        price = quote.ask if quote.ask is not None else quote.price
        return Decimal(str(price)) >= stop
    else:
        price = quote.bid if quote.bid is not None else quote.price
        return Decimal(str(price)) <= stop


# ---------------------------------------------------------------------------
# Cash balance helper
# ---------------------------------------------------------------------------

def get_cash_balance(db: Session, account_id: str) -> Decimal:
    """Return current cash balance from the most recent ledger entry."""
    entry = (
        db.query(LedgerEntry)
        .filter_by(account_id=account_id)
        .order_by(LedgerEntry.created_at.desc())
        .first()
    )
    return Decimal(str(entry.balance_after)) if entry else Decimal("0")


# ---------------------------------------------------------------------------
# Internal fill logic — operates on an existing Order row
# ---------------------------------------------------------------------------

def _reserved_for_pending_buys(
    db: Session,
    account_id: str,
    exclude_order_id: str,
    quotes: QuotesClient | None = None,
) -> Decimal:
    """Sum the estimated cost of all pending buy orders, excluding the given order.

    Orders that already have total_value set are used directly. Orders queued
    while the market was closed (total_value is None) are priced via quotes when
    available; unpriced orders are skipped (optimistic — acceptable since they
    will be rejected at fill time if cash is insufficient).
    """
    pending = (
        db.query(Order)
        .filter(
            Order.account_id == account_id,
            Order.side == OrderSide.BUY,
            Order.status == OrderStatus.PENDING,
            Order.id != exclude_order_id,
        )
        .all()
    )
    reserved = Decimal("0")
    for o in pending:
        if o.total_value is not None:
            reserved += Decimal(str(o.total_value))
        elif quotes is not None:
            try:
                quote = quotes.get_quote(o.symbol)
                price = quote.ask if quote.ask is not None else quote.price
                reserved += Decimal(str(o.quantity)) * price
            except QuoteUnavailable:
                pass  # skip — will be caught at fill time
    return reserved


def _apply_buy_fill(
    db: Session,
    order: Order,
    fill_price: Decimal,
    quotes: QuotesClient | None = None,
) -> Order:
    account_id = order.account_id
    symbol = order.symbol
    quantity = Decimal(str(order.quantity))
    total_cost = quantity * fill_price
    cash = get_cash_balance(db, account_id)
    reserved = _reserved_for_pending_buys(db, account_id, exclude_order_id=order.id, quotes=quotes)
    available = cash - reserved

    order.fill_price = fill_price
    order.total_value = total_cost

    if total_cost > available:
        order.status = OrderStatus.REJECTED
        order.reject_reason = (
            f"Insufficient buying power: need {total_cost:.2f}, "
            f"available {available:.2f} (cash {cash:.2f}, reserved {reserved:.2f})"
        )
        db.commit()
        db.refresh(order)
        return order

    now = datetime.now(timezone.utc)
    order.status = OrderStatus.FILLED

    db.add(TaxLot(
        account_id=account_id,
        symbol=symbol,
        quantity=quantity,
        cost_per_share=fill_price,
        cost_basis=quantity * fill_price,
        acquired_date=now,
        order_id=order.id,
    ))

    position = db.query(Position).filter_by(account_id=account_id, symbol=symbol).first()
    if position is None:
        db.add(Position(
            account_id=account_id,
            symbol=symbol,
            quantity=quantity,
            avg_cost=fill_price,
            created_at=now,
            updated_at=now,
        ))
    else:
        old_qty = Decimal(str(position.quantity))
        old_avg = Decimal(str(position.avg_cost))
        new_qty = old_qty + quantity
        position.avg_cost = (old_qty * old_avg + quantity * fill_price) / new_qty
        position.quantity = new_qty
        position.updated_at = now

    new_balance = cash - total_cost
    db.add(LedgerEntry(
        account_id=account_id,
        entry_type=EntryType.BUY,
        amount=-total_cost,
        balance_after=new_balance,
        description=f"BUY {quantity} {symbol} @ {fill_price}",
        created_at=now,
    ))

    db.commit()
    db.refresh(order)
    return order


def _apply_sell_fill(db: Session, order: Order, fill_price: Decimal) -> Order:
    account_id = order.account_id
    symbol = order.symbol
    quantity = Decimal(str(order.quantity))
    total_proceeds = quantity * fill_price

    position = db.query(Position).filter_by(account_id=account_id, symbol=symbol).first()
    available = Decimal(str(position.quantity)) if position else Decimal("0")

    order.fill_price = fill_price
    order.total_value = total_proceeds

    if position is None or available < quantity:
        order.status = OrderStatus.REJECTED
        order.reject_reason = (
            f"Insufficient position in {symbol}: need {quantity}, have {available}"
        )
        db.commit()
        db.refresh(order)
        return order

    now = datetime.now(timezone.utc)
    order.status = OrderStatus.FILLED

    # FIFO lot consumption
    lots = (
        db.query(TaxLot)
        .filter_by(account_id=account_id, symbol=symbol, closed=False)
        .order_by(TaxLot.acquired_date.asc())
        .with_for_update()
        .all()
    )
    remaining = quantity
    for lot in lots:
        if remaining <= 0:
            break
        lot_qty = Decimal(str(lot.quantity))
        lot_cost = Decimal(str(lot.cost_per_share))
        consumed = min(lot_qty, remaining)

        db.add(LotClosure(
            tax_lot_id=lot.id,
            account_id=account_id,
            symbol=symbol,
            order_id=order.id,
            quantity_closed=consumed,
            cost_per_share=lot_cost,
            close_price=fill_price,
            realized_pnl=(fill_price - lot_cost) * consumed,
            created_at=now,
        ))

        if lot_qty <= remaining:
            lot.quantity = Decimal("0")
            lot.closed = True
            remaining -= lot_qty
        else:
            lot.quantity = lot_qty - remaining
            remaining = Decimal("0")

    new_qty = available - quantity
    if new_qty == 0:
        db.delete(position)
    else:
        position.quantity = new_qty
        position.updated_at = now

    cash = get_cash_balance(db, account_id)
    new_balance = cash + total_proceeds
    db.add(LedgerEntry(
        account_id=account_id,
        entry_type=EntryType.SELL,
        amount=total_proceeds,
        balance_after=new_balance,
        description=f"SELL {quantity} {symbol} @ {fill_price}",
        created_at=now,
    ))

    db.commit()
    db.refresh(order)
    return order


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def place_order(
    db: Session,
    account_id: str,
    symbol: str,
    side: OrderSide,
    quantity: Decimal,
    quotes: QuotesClient,
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
    stop_price: Decimal | None = None,
    time_in_force: TimeInForce = TimeInForce.GTC,
) -> Order:
    """Submit an order (market, limit, or stop).

    **Market orders:**
    - Market open: fetches current price and fills immediately. If quotes service
      is unreachable, order is rejected.
    - Market closed: queued as PENDING, filled automatically at open.

    **Limit orders:**
    - Queued as PENDING regardless of market state.
    - Checked every polling interval (30s) during market hours.
    - DAY orders expire at market close; GTC orders persist until filled or cancelled.

    **Stop orders:**
    - Always queued as PENDING (even if condition is met at placement).
    - Triggers when price crosses the stop threshold; fills at market price.
    - STOP BUY: triggers when ask >= stop_price (breakout entry).
    - STOP SELL: triggers when bid <= stop_price (stop-loss).
    """
    now = datetime.now(timezone.utc)
    expires_at = None
    if time_in_force == TimeInForce.DAY:
        expires_at = next_market_close(now)

    # For LIMIT orders when market is open, check condition immediately
    if order_type == OrderType.LIMIT and is_market_open():
        try:
            quote = quotes.get_quote(symbol)
            if _limit_condition_met(
                Order(
                    side=side,
                    limit_price=limit_price,
                    symbol=symbol,  # temp object just for condition check
                    quantity=quantity,
                    account_id=account_id,
                ),
                quote,
            ):
                # Condition is met — proceed to fill
                order = Order(
                    account_id=account_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    status=OrderStatus.PENDING,
                    order_type=order_type,
                    limit_price=limit_price,
                    time_in_force=time_in_force,
                    expires_at=expires_at,
                    created_at=now,
                )
                db.add(order)
                db.flush()
                fill_price = _fill_price_from_quote(quote, side)
                if side == OrderSide.BUY:
                    return _apply_buy_fill(db, order, fill_price, quotes=quotes)
                return _apply_sell_fill(db, order, fill_price)
            else:
                # Condition not met — queue as PENDING
                order = Order(
                    account_id=account_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    status=OrderStatus.PENDING,
                    order_type=order_type,
                    limit_price=limit_price,
                    time_in_force=time_in_force,
                    expires_at=expires_at,
                    created_at=now,
                )
                db.add(order)
                db.commit()
                db.refresh(order)
                return order
        except QuoteUnavailable as exc:
            # Quote unavailable — queue PENDING
            order = Order(
                account_id=account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                status=OrderStatus.PENDING,
                order_type=order_type,
                limit_price=limit_price,
                time_in_force=time_in_force,
                expires_at=expires_at,
                created_at=now,
            )
            db.add(order)
            db.commit()
            db.refresh(order)
            return order

    # MARKET orders when market is open
    if order_type == OrderType.MARKET and is_market_open():
        try:
            fill_price = _fill_price_from_quote(quotes.get_quote(symbol), side)
        except QuoteUnavailable as exc:
            order = Order(
                account_id=account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                status=OrderStatus.REJECTED,
                reject_reason=str(exc),
                order_type=order_type,
                created_at=now,
            )
            db.add(order)
            db.commit()
            db.refresh(order)
            return order

        order = Order(
            account_id=account_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            status=OrderStatus.PENDING,
            order_type=order_type,
            created_at=now,
        )
        db.add(order)
        db.flush()
        if side == OrderSide.BUY:
            return _apply_buy_fill(db, order, fill_price, quotes=quotes)
        return _apply_sell_fill(db, order, fill_price)

    # STOP and STOP_LIMIT orders are always queued, never filled immediately
    if order_type == OrderType.STOP or order_type == OrderType.STOP_LIMIT:
        order = Order(
            account_id=account_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            status=OrderStatus.PENDING,
            order_type=order_type,
            limit_price=limit_price,
            stop_price=stop_price,
            triggered=False,
            time_in_force=time_in_force,
            expires_at=expires_at,
            created_at=now,
        )
        db.add(order)
        db.commit()
        db.refresh(order)
        return order

    # Market is closed or LIMIT order — queue for later processing
    order = Order(
        account_id=account_id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        status=OrderStatus.PENDING,
        order_type=order_type,
        limit_price=limit_price,
        stop_price=stop_price,
        triggered=False,
        time_in_force=time_in_force,
        expires_at=expires_at,
        created_at=now,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def process_pending_orders(db: Session, quotes: QuotesClient) -> list[Order]:
    """Fill all PENDING orders at current market prices from the quotes service.

    Called automatically when the market opens (background watcher) and
    continuously during market hours (every 30s).
    Also available via POST /market/process-queue for manual triggers.

    For MARKET orders: fills at current market price.
    For LIMIT orders: fills only if price condition is met.
    For STOP orders: fills only if trigger condition is met (then as market).
    For DAY orders: rejects if past expiry time.
    Orders whose symbol has no available quote are left PENDING.
    """
    now = datetime.now(timezone.utc)

    # Only process orders within the allowed window:
    # - After market open + initial delay (9:45 AM ET)
    # - Before market close + extended delay (4:15 PM ET)
    if now < earliest_order_processing_time(now) or now > latest_order_processing_time(now):
        logger.debug(f"Order processing blocked: outside trading window ({now.strftime('%H:%M:%S')})")
        return []

    pending = (
        db.query(Order)
        .filter_by(status=OrderStatus.PENDING)
        .order_by(Order.created_at.asc())  # time priority: oldest order fills first
        .all()
    )
    processed: list[Order] = []
    for order in pending:
        # Check if DAY order has expired
        if order.time_in_force == TimeInForce.DAY and order.expires_at is not None:
            # Ensure expires_at is timezone-aware for comparison
            expires_at = order.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if now >= expires_at:
                order.status = OrderStatus.REJECTED
                order.reject_reason = "DAY order expired"
                db.commit()
                db.refresh(order)
                logger.info(f"DAY order REJECTED (expired): {order.id} {order.side} {order.quantity} {order.symbol}")
                processed.append(order)
                continue

        try:
            quote = quotes.get_quote(order.symbol)
        except QuoteUnavailable:
            logger.warning(f"Quote unavailable for {order.symbol} — order {order.id} left PENDING")
            continue  # leave pending until price becomes available

        # Check price conditions based on order type
        # LIMIT orders: fill only if price condition is met
        if order.order_type == OrderType.LIMIT:
            if not _limit_condition_met(order, quote):
                logger.debug(f"LIMIT order condition not met: {order.id} {order.symbol} limit={order.limit_price} price={quote.price}")
                continue  # leave pending, condition not met yet
        # STOP orders: fill only if trigger condition is met
        elif order.order_type == OrderType.STOP:
            if not _stop_condition_met(order, quote):
                logger.debug(f"STOP order not triggered: {order.id} {order.symbol} stop={order.stop_price} price={quote.price}")
                continue  # leave pending, not triggered yet
        # STOP_LIMIT orders: two phases
        elif order.order_type == OrderType.STOP_LIMIT:
            if not order.triggered:
                # Phase 1: check if stop is crossed
                if not _stop_condition_met(order, quote):
                    logger.debug(f"STOP_LIMIT stop not triggered: {order.id} {order.symbol} stop={order.stop_price} price={quote.price}")
                    continue  # not triggered yet, stay pending
                # Stop crossed — mark as triggered and persist
                order.triggered = True
                db.commit()
                logger.debug(f"STOP_LIMIT stop triggered: {order.id} {order.symbol}")
            # Phase 2: check limit condition (whether just triggered or already triggered)
            if not _limit_condition_met(order, quote):
                logger.debug(f"STOP_LIMIT limit not met: {order.id} {order.symbol} limit={order.limit_price} price={quote.price}")
                continue  # triggered but limit condition not met yet
        # MARKET orders: fill at any time (no condition check)

        # Fill the order
        fill_price = _fill_price_from_quote(quote, order.side)
        if order.side == OrderSide.BUY:
            _apply_buy_fill(db, order, fill_price, quotes=quotes)
        else:
            _apply_sell_fill(db, order, fill_price)

        # Log the result
        if order.status == OrderStatus.FILLED:
            logger.info(f"Order FILLED: {order.id} {order.side} {order.quantity} {order.symbol} @ {fill_price}")
        elif order.status == OrderStatus.REJECTED:
            logger.warning(f"Order REJECTED: {order.id} — {order.reject_reason}")

        processed.append(order)
    return processed


def get_buying_power(
    db: Session,
    account_id: str,
    quotes: QuotesClient,
) -> dict:
    """Calculate available buying power for an account.

    buying_power = cash_balance - Σ(estimated cost of each pending buy order)

    Estimated cost uses the current ask price (what a fill would cost).
    Symbols whose quote is unavailable are excluded from the reservation and
    reported in unpriced_symbols — buying power is therefore optimistic when
    any symbols are unpriced.
    """
    cash = get_cash_balance(db, account_id)

    pending_buys = (
        db.query(Order)
        .filter_by(account_id=account_id, side=OrderSide.BUY, status=OrderStatus.PENDING)
        .all()
    )

    # Aggregate quantity per symbol to minimise quotes API calls
    qty_by_symbol: dict[str, Decimal] = defaultdict(Decimal)
    for order in pending_buys:
        qty_by_symbol[order.symbol] += Decimal(str(order.quantity))

    reserved = Decimal("0")
    unpriced: list[str] = []

    for symbol, total_qty in qty_by_symbol.items():
        try:
            quote = quotes.get_quote(symbol)
            price = quote.ask if quote.ask is not None else quote.price
            reserved += total_qty * price
        except QuoteUnavailable:
            unpriced.append(symbol)

    return {
        "account_id": account_id,
        "cash_balance": cash,
        "reserved_for_pending_buys": reserved,
        "buying_power": cash - reserved,
        "pending_buy_count": len(pending_buys),
        "unpriced_symbols": sorted(unpriced),
    }
