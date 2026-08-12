from collections.abc import Generator
import logging
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def wait_for_database(*, max_attempts: int, retry_delay_seconds: float) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1")).scalar_one()
            return
        except OperationalError:
            if attempt == max_attempts:
                logger.error(
                    "Database unavailable after %s startup attempts",
                    max_attempts,
                )
                raise
            logger.warning(
                (
                    "Database unavailable during startup attempt %s/%s; "
                    "retrying in %.1f seconds"
                ),
                attempt,
                max_attempts,
                retry_delay_seconds,
            )
            time.sleep(retry_delay_seconds)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> dict:
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1")).scalar_one()
        return {"status": "ok", "result": result}
    except SQLAlchemyError as exc:
        return {"status": "error", "message": str(exc)}
