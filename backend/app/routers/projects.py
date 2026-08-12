import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse

from app.dependencies import get_project_service, get_repository
from app.repositories import (
    DemoCapacityExceeded,
    ProjectAlreadyExists,
    ProjectNotFound,
    ProjectRepository,
)
from app.schemas import (
    AuditLogResponse,
    PodResponse,
    ProjectCreateRequest,
    ProjectEventResponse,
    ProjectResponse,
)
from app.services import GkeUnavailable, InvalidLifecycleOperation, ProjectService


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])
NamespaceId = Annotated[
    str,
    Path(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    ),
]
DEMO_SERVICE_PREFIXES = ("demo-", "portfolio-", "broken-")
GKE_UNAVAILABLE_MESSAGE = "GKE 상태를 일시적으로 확인할 수 없습니다."
GKE_UNAVAILABLE_DETAIL = "Kubernetes API connection failed"


def _demo_allowed_images(settings) -> list[str]:
    return [
        image.strip()
        for image in settings.demo_allowed_images.split(",")
        if image.strip()
    ]


def _validate_demo_request(
    request: ProjectCreateRequest,
    service: ProjectService,
) -> None:
    settings = service.settings
    if not settings.demo_mode:
        return
    if not request.service_name.startswith(DEMO_SERVICE_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Demo mode allows only demo-, portfolio-, or broken- service names",
        )
    if request.image not in _demo_allowed_images(settings):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Image is not allowed in demo mode: {request.image}",
        )
    if request.replicas > settings.demo_max_replicas:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Demo mode replicas cannot exceed {settings.demo_max_replicas}",
        )


def _not_found(project_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Project not found: {project_id}",
    )


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _gke_unavailable() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "error": {
                "code": "GKE_UNAVAILABLE",
                "message": GKE_UNAVAILABLE_MESSAGE,
                "detail": GKE_UNAVAILABLE_DETAIL,
            }
        },
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    request: ProjectCreateRequest,
    service: ProjectService = Depends(get_project_service),
):
    _validate_demo_request(request, service)
    try:
        return service.create_project(request)
    except ProjectAlreadyExists as exc:
        raise _conflict(f"Project already exists: {exc}") from exc
    except DemoCapacityExceeded as exc:
        raise _conflict(
            f"demo project limit reached: {service.settings.demo_max_projects}"
        ) from exc
    except InvalidLifecycleOperation as exc:
        raise _conflict(str(exc)) from exc
    except GkeUnavailable:
        logger.info("GKE unavailable during project creation", exc_info=True)
        return _gke_unavailable()


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    repository: ProjectRepository = Depends(get_repository),
):
    return repository.list_projects()


@router.get("/{project_id}/pods", response_model=list[PodResponse])
def get_project_pods(
    project_id: NamespaceId,
    service: ProjectService = Depends(get_project_service),
):
    try:
        return service.list_pods(project_id)
    except ProjectNotFound as exc:
        raise _not_found(project_id) from exc
    except GkeUnavailable:
        logger.info("GKE unavailable during Pod read", exc_info=True)
        return _gke_unavailable()


@router.get("/{project_id}/events", response_model=list[ProjectEventResponse])
def get_project_events(
    project_id: NamespaceId,
    limit: int = Query(default=50, ge=1, le=200),
    service: ProjectService = Depends(get_project_service),
):
    try:
        return service.list_events(project_id, limit=limit)
    except ProjectNotFound as exc:
        raise _not_found(project_id) from exc
    except GkeUnavailable:
        logger.info("GKE unavailable during Event read", exc_info=True)
        return _gke_unavailable()


@router.post("/{project_id}/sync-status", response_model=ProjectResponse)
def sync_project_status(
    project_id: NamespaceId,
    service: ProjectService = Depends(get_project_service),
):
    try:
        return service.sync_status(project_id)
    except ProjectNotFound as exc:
        raise _not_found(project_id) from exc
    except InvalidLifecycleOperation as exc:
        raise _conflict(str(exc)) from exc
    except GkeUnavailable:
        logger.info("GKE unavailable during status sync", exc_info=True)
        return _gke_unavailable()


@router.delete("/{project_id}", response_model=ProjectResponse)
def delete_project(
    project_id: NamespaceId,
    service: ProjectService = Depends(get_project_service),
):
    try:
        return service.delete_project(project_id)
    except ProjectNotFound as exc:
        raise _not_found(project_id) from exc
    except InvalidLifecycleOperation as exc:
        raise _conflict(str(exc)) from exc
    except GkeUnavailable:
        logger.info("GKE unavailable during project deletion", exc_info=True)
        return _gke_unavailable()


@router.get("/{project_id}/audit-logs", response_model=list[AuditLogResponse])
def get_project_audit_logs(
    project_id: NamespaceId,
    repository: ProjectRepository = Depends(get_repository),
):
    if repository.get_project(project_id) is None:
        raise _not_found(project_id)
    return repository.list_audit_logs(project_id)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: NamespaceId,
    repository: ProjectRepository = Depends(get_repository),
):
    project = repository.get_project(project_id)
    if project is None:
        raise _not_found(project_id)
    return project
