from functools import lru_cache

from fastapi import Depends
from google.cloud import firestore

from app import k8s_client
from app.config import get_settings
from app.repositories import InMemoryProjectRepository, ProjectRepository
from app.repositories.firestore import FirestoreProjectRepository
from app.services.project_service import ProjectService
from app.services.platform_status import PlatformStatusService


@lru_cache
def get_repository() -> ProjectRepository:
    settings = get_settings()
    if settings.repository_backend == "memory":
        return InMemoryProjectRepository(
            max_active_projects=settings.demo_max_projects,
        )

    client_options = {"database": settings.firestore_database}
    if settings.firestore_project_id:
        client_options["project"] = settings.firestore_project_id
    client = firestore.Client(**client_options)
    return FirestoreProjectRepository(
        client=client,
        max_active_projects=settings.demo_max_projects,
    )


@lru_cache
def get_platform_status_service() -> PlatformStatusService:
    return PlatformStatusService(settings=get_settings())


def get_project_service(
    repository: ProjectRepository = Depends(get_repository),
) -> ProjectService:
    return ProjectService(
        repository=repository,
        kubernetes=k8s_client,
        platform_status=get_platform_status_service(),
        settings=get_settings(),
    )
