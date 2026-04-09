import os
from pathlib import Path

from dotenv import load_dotenv

# Load from project-root .env (TradingStrategies/.env)
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

HOST: str = os.getenv("MARKETDATA_HOST", "0.0.0.0")
PORT: int = int(os.getenv("MARKETDATA_PORT", "8001"))

# How long a fetched quote is served from cache before going back to yfinance.
QUOTE_CACHE_TTL: int = int(os.getenv("QUOTE_CACHE_TTL", "60"))
