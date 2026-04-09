import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# DATA_DIR env var lets Docker (or any deployment) redirect the database to a
# mounted volume. Falls back to <repo-root>/data for local development.
_data_dir = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
DB_PATH = _data_dir / "brokerage.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
