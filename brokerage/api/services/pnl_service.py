from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import LotClosure, Position
from .quotes_client import QuoteUnavailable, QuotesClient


def get_realized_pnl(db: Session, account_id: str) -> dict:
    """Return realized P&L aggregated by symbol for all closed lot events.

    Each row in lot_closures represents one partial or full lot close.
    P&L is summed across all closures per symbol.
    """
    rows = (
        db.query(
            LotClosure.symbol,
            func.sum(LotClosure.realized_pnl).label("realized_pnl"),
            func.count(LotClosure.id).label("closure_count"),
        )
        .filter_by(account_id=account_id)
        .group_by(LotClosure.symbol)
        .order_by(LotClosure.symbol)
        .all()
    )

    by_symbol = [
        {
            "symbol": row.symbol,
            "realized_pnl": Decimal(str(row.realized_pnl)),
            "closure_count": row.closure_count,
        }
        for row in rows
    ]
    total = sum((item["realized_pnl"] for item in by_symbol), Decimal("0"))

    return {
        "account_id": account_id,
        "total_realized_pnl": total,
        "by_symbol": by_symbol,
    }


def get_unrealized_pnl(db: Session, account_id: str, quotes: QuotesClient) -> dict:
    """Return unrealized P&L for all open positions, marked to current market price.

    Positions whose symbol cannot be quoted are included with null price/pnl
    fields and listed in unpriced_symbols. Totals exclude unpriced positions.
    """
    positions = db.query(Position).filter_by(account_id=account_id).all()

    by_symbol = []
    unpriced: list[str] = []
    total_cost = Decimal("0")
    total_market = Decimal("0")

    for pos in sorted(positions, key=lambda p: p.symbol):
        qty = Decimal(str(pos.quantity))
        avg_cost = Decimal(str(pos.avg_cost))
        cost_basis = qty * avg_cost

        try:
            quote = quotes.get_quote(pos.symbol)
            current_price = quote.price
            market_value = qty * current_price
            pnl = market_value - cost_basis
            pnl_pct = (pnl / cost_basis * 100).quantize(Decimal("0.0001"))

            by_symbol.append({
                "symbol": pos.symbol,
                "quantity": qty,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "cost_basis": cost_basis,
                "market_value": market_value,
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": pnl_pct,
            })
            total_cost += cost_basis
            total_market += market_value

        except QuoteUnavailable:
            unpriced.append(pos.symbol)
            by_symbol.append({
                "symbol": pos.symbol,
                "quantity": qty,
                "avg_cost": avg_cost,
                "current_price": None,
                "cost_basis": cost_basis,
                "market_value": None,
                "unrealized_pnl": None,
                "unrealized_pnl_pct": None,
            })
            total_cost += cost_basis  # cost basis is always known

    return {
        "account_id": account_id,
        "total_cost_basis": total_cost,
        "total_market_value": total_market,
        "total_unrealized_pnl": total_market - total_cost,
        "by_symbol": by_symbol,
        "unpriced_symbols": unpriced,
    }
