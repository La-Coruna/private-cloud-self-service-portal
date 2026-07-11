from fastapi import FastAPI
from sqlalchemy import inspect, text

from app import models  # noqa: F401
from app.config import get_settings
from app.db import Base, check_db_connection, engine
from app.k8s_client import check_kubernetes_connection
from app.routers.projects import router as projects_router


settings = get_settings()

app = FastAPI(title=settings.app_name)
app.include_router(projects_router)


@app.on_event("startup")
def create_database_tables() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        columns = {
            column["name"]
            for column in inspect(connection).get_columns("projects")
        }
        if "ingress_host" not in columns:
            connection.execute(
                text("ALTER TABLE projects ADD COLUMN ingress_host VARCHAR(255) NULL")
            )


@app.get("/")
def read_root() -> dict:
    return {
        "app": settings.app_name,
        "env": settings.app_env,
        "message": "Private Cloud Self-Service Portal API",
    }


@app.get("/health")
def health_check() -> dict:
    database = check_db_connection()
    kubernetes = check_kubernetes_connection()
    dependency_statuses = [database["status"], kubernetes["status"]]
    status = "ok" if all(item == "ok" for item in dependency_statuses) else "degraded"

    return {
        "status": status,
        "app": settings.app_name,
        "env": settings.app_env,
        "dependencies": {
            "database": database,
            "kubernetes": kubernetes,
        },
    }
