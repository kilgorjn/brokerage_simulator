import os
from pathlib import Path

from dotenv import load_dotenv

# Load from project-root .env (TradingStrategies/.env)
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

HOST: str = os.getenv("BROKERAGE_HOST", "0.0.0.0")
PORT: int = int(os.getenv("BROKERAGE_PORT", "8000"))

# Base URL of the marketdata quotes service
QUOTES_API_URL: str = os.getenv("QUOTES_API_URL", "http://localhost:8001")

# Delay order processing after market opens (in minutes) to allow quotes to stabilize
MARKET_OPEN_PROCESSING_DELAY_MINUTES: int = int(os.getenv("MARKET_OPEN_PROCESSING_DELAY_MINUTES", "15"))

# Extended order processing after market close (in minutes) for end-of-day volatility
MARKET_CLOSE_PROCESSING_DELAY_MINUTES: int = int(os.getenv("MARKET_CLOSE_PROCESSING_DELAY_MINUTES", "15"))
