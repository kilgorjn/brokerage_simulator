#!/bin/bash

echo "Testing brokerage database schema..."
echo ""

docker exec tradingstrategies-brokerage-1 python -c "
from sqlalchemy import inspect, create_engine

engine = create_engine('sqlite:////data/brokerage.db')
inspector = inspect(engine)

# Get all columns
cols = {c['name']: str(c['type']) for c in inspector.get_columns('orders')}

# Required new columns
required = ['order_type', 'limit_price', 'stop_price', 'triggered', 'time_in_force', 'expires_at']

print('Orders table columns:')
for col in sorted(cols.keys()):
    marker = '✓' if col in required else ' '
    print(f'  {marker} {col:20} {cols[col]}')

print()
missing = [c for c in required if c not in cols]
if missing:
    print(f'✗ MISSING: {missing}')
    exit(1)
else:
    print('✓ All required columns present!')
    exit(0)
"

if [ $? -eq 0 ]; then
    echo "✓ Database schema is ready for deployment"
else
    echo "✗ Schema check failed - migration incomplete"
    exit 1
fi
