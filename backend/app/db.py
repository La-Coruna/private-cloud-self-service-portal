from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)


def check_db_connection() -> dict:
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1")).scalar_one()
        return {"status": "ok", "result": result}
    except SQLAlchemyError as exc:
        return {"status": "error", "message": str(exc)}
