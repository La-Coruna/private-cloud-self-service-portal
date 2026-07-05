from fastapi import FastAPI

from app.config import get_settings
from app.db import check_db_connection
from app.k8s_client import check_kubernetes_connection


settings = get_settings()

app = FastAPI(title=settings.app_name)


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
