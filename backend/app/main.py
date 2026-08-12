import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.dependencies import get_platform_status_service, get_repository
from app.repositories import ProjectRepository
from app.routers.platform import router as platform_router
from app.routers.projects import router as projects_router
from app.services.platform_status import PlatformStatusService


logger = logging.getLogger(__name__)
FIRESTORE_UNAVAILABLE_MESSAGE = "Firestore is temporarily unavailable"
settings = get_settings()

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(projects_router)
app.include_router(platform_router)


@app.get("/")
def read_root() -> dict:
    return {
        "app": settings.app_name,
        "env": settings.app_env,
        "message": "Private Cloud Self-Service Portal API",
    }


@app.get("/health")
def health_check(
    repository: ProjectRepository = Depends(get_repository),
    platform_service: PlatformStatusService = Depends(get_platform_status_service),
):
    platform = platform_service.get_status()
    gke_status = {
        "status": platform.status.value,
        "message": platform.message,
        "creation_allowed": platform.creation_allowed,
        "checked_at": platform.checked_at.isoformat(),
    }

    try:
        firestore_status = repository.health_check()
    except Exception:
        logger.info("Firestore health check failed", exc_info=True)
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "app": settings.app_name,
                "env": settings.app_env,
                "dependencies": {
                    "firestore": {
                        "status": "error",
                        "message": FIRESTORE_UNAVAILABLE_MESSAGE,
                    },
                    "gke": gke_status,
                },
            },
        )

    return {
        "status": "ok" if platform.creation_allowed else "degraded",
        "app": settings.app_name,
        "env": settings.app_env,
        "dependencies": {
            "firestore": firestore_status,
            "gke": gke_status,
        },
    }
